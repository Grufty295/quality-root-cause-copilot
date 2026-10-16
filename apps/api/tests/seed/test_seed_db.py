"""El seed contra Postgres real. Cada prueba corre en una transacción que se revierte."""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from pathlib import Path

import pytest
from sqlalchemy import text

from app.seed.service import SeedService
from tests.retrieval.fakes import HashingEmbedder

FIXTURES = Path(__file__).parent.parent / "retrieval" / "fixtures"


@pytest.fixture
def service(db_conn):
    @contextmanager
    def connect():
        with db_conn.begin_nested():
            yield db_conn

    return SeedService(connect, plant_id="JRZ1")


def _scopes(conn, username):
    rows = conn.execute(
        text(
            "SELECT s.plant_id, s.line_id FROM user_scope s JOIN app_user u ON u.id = s.user_id "
            "WHERE u.username = :u ORDER BY 1, 2 NULLS FIRST"
        ),
        {"u": username},
    ).all()
    return [tuple(r) for r in rows]


def test_load_structured_creates_everything(service, db_conn, estructurados):
    report = service.load_structured(estructurados)
    assert (report.customers, report.parts, report.defect_families, report.users) == (
        2,
        2,
        2,
        6,
    )
    roles = dict(
        db_conn.execute(text("SELECT username, role::text FROM app_user")).all()
    )
    assert roles["u-insp-l1"] == "inspector"
    assert roles["u-ingcal-1"] == "ingeniero"
    assert roles["u-gercal"] == "gerente"
    assert roles["u-auditor"] == "auditor"
    assert (
        db_conn.execute(
            text("SELECT is_confidential FROM customer WHERE id='NOR'")
        ).scalar_one()
        is True
    )
    assert (
        db_conn.execute(
            text("SELECT is_confidential FROM customer WHERE id='KES'")
        ).scalar_one()
        is False
    )


def test_scopes(service, db_conn, estructurados):
    service.load_structured(estructurados)
    assert _scopes(db_conn, "u-insp-l1") == [("JRZ1", "L1")]
    assert _scopes(db_conn, "u-insp-l2") == [("JRZ1", "L2")]
    assert _scopes(db_conn, "u-gercal") == [("JRZ1", None)]
    assert _scopes(db_conn, "u-ingcal-jrz2") == [("JRZ2", None)]


def test_idempotent(service, db_conn, estructurados):
    service.load_structured(estructurados)
    before = [
        db_conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
        for t in ("app_user", "user_scope", "part")
    ]
    service.load_structured(estructurados)
    after = [
        db_conn.execute(text(f"SELECT count(*) FROM {t}")).scalar_one()
        for t in ("app_user", "user_scope", "part")
    ]
    assert before == after


def test_rerun_resets_scopes_and_keeps_is_active(service, db_conn, estructurados):
    service.load_structured(estructurados)
    db_conn.execute(
        text("UPDATE app_user SET is_active = false WHERE username = 'u-insp-l1'")
    )
    db_conn.execute(
        text(
            "INSERT INTO user_scope (user_id, plant_id, line_id) SELECT id, 'JRZ1', 'L2' FROM app_user WHERE username='u-insp-l1'"
        )
    )
    service.load_structured(estructurados)
    assert _scopes(db_conn, "u-insp-l1") == [("JRZ1", "L1")]
    assert (
        db_conn.execute(
            text("SELECT is_active FROM app_user WHERE username='u-insp-l1'")
        ).scalar_one()
        is False
    )


def _add_marker_customer(estructurados):
    """Un cliente que no existe en la base, para ver si una carga fallida deja algo."""
    with (estructurados / "catalogo_clientes.csv").open("a", encoding="utf-8") as f:
        f.write("ZZZ,Cliente Marcador,OEM,interno\n")


def _marker_rows(db_conn):
    return db_conn.execute(
        text("SELECT count(*) FROM customer WHERE id = 'ZZZ'")
    ).scalar_one()


def test_invalid_input_writes_nothing(service, db_conn, estructurados):
    _add_marker_customer(estructurados)
    (estructurados / "usuarios_demo.csv").write_text(
        "usuario_id,rol,lineas\nx,superadmin,L1\n", encoding="utf-8"
    )
    with pytest.raises(ValueError):
        service.load_structured(estructurados)
    assert _marker_rows(db_conn) == 0


def test_unknown_line_rolls_back(service, db_conn, estructurados):
    _add_marker_customer(estructurados)
    (estructurados / "usuarios_demo.csv").write_text(
        "usuario_id,rol,lineas\nx,inspector,L99\n", encoding="utf-8"
    )
    with pytest.raises(ValueError, match="no existen"):
        service.load_structured(estructurados)
    assert _marker_rows(db_conn) == 0


def test_end_to_end_with_corpus(service, db_conn, estructurados, tmp_path):
    data = estructurados.parent
    shutil.copytree(FIXTURES, data / "corpus")
    report = service.run(data, embedder=HashingEmbedder())
    assert report.ingest is not None and report.ingest.ok
    assert report.ingest.fragments > 0
    again = service.run(data, embedder=HashingEmbedder())
    assert (
        again.ingest is not None
        and not again.ingest.created
        and not again.ingest.failed
    )


def test_seeded_users_see_only_their_scope(service, db_conn, estructurados):
    data = estructurados.parent
    shutil.copytree(FIXTURES, data / "corpus")
    embedder = HashingEmbedder()
    service.run(data, embedder=embedder)

    def hits(username: str) -> set[str]:
        # Directo sobre visible_fragments: una búsqueda con top_k corta el conjunto y
        # haría depender la comparación de las puntuaciones.
        rows = db_conn.execute(
            text(
                "SELECT DISTINCT d.source_key FROM app_user u "
                "CROSS JOIN LATERAL visible_fragments(u.id) f JOIN document d ON d.id = f.document_id "
                "WHERE u.username = :u"
            ),
            {"u": username},
        )
        return {r[0] for r in rows}

    jrz2 = hits("u-ingcal-jrz2")
    assert jrz2 == set()  # el corpus es de JRZ1
    plant_wide = hits("u-gercal")
    assert plant_wide  # el alcance de planta ve lo que hay
    assert hits("u-insp-l1") <= plant_wide
    assert hits("u-insp-l2") <= plant_wide


def test_two_plants_can_share_a_line_name(service, db_conn, estructurados):
    service.load_structured(estructurados)
    owners = (
        db_conn.execute(
            text("SELECT plant_id FROM line WHERE id = 'L1' ORDER BY plant_id")
        )
        .scalars()
        .all()
    )
    assert owners == ["JRZ1", "JRZ2"]
    # El usuario de la otra planta queda en SU L1, no en la de JRZ1.
    assert _scopes(db_conn, "u-ingcal-jrz2") == [("JRZ2", None)]
    assert _scopes(db_conn, "u-insp-l1") == [("JRZ1", "L1")]
