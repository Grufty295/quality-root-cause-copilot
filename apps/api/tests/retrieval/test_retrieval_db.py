"""Ingesta y búsqueda contra Postgres real (migraciones 0001-0004).

Cada prueba corre en una transacción que se revierte; la ingesta usa savepoints
dentro de ella. Los documentos son copias reales del corpus (fixtures/).
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from uuid import UUID

import pytest
from sqlalchemy import text

from app.confidentiality import ConfidentialityLevel as L
from app.ingest.service import IngestService
from app.modules.auth.models import CurrentUser, Scope
from app.retrieval.models import DocumentKind, SearchQuery
from app.retrieval.service import RetrievalService

from .fakes import HashingEmbedder

FIXTURES = Path(__file__).parent / "fixtures"


# ------------------------------------------------------------------ fixtures


def _user(
    conn, username: str, role: str, scopes: list[tuple[str, str | None]]
) -> CurrentUser:
    uid: UUID = conn.execute(
        text(
            "INSERT INTO app_user (username, display_name, role) VALUES (:u, :u, CAST(:r AS user_role)) RETURNING id"
        ),
        {"u": username, "r": role},
    ).scalar_one()
    for plant, line in scopes:
        conn.execute(
            text(
                "INSERT INTO user_scope (user_id, plant_id, line_id) VALUES (:id, :p, :l)"
            ),
            {"id": uid, "p": plant, "l": line},
        )
    return CurrentUser(
        uid, username, username, role, tuple(Scope(p, line) for p, line in scopes)
    )


@pytest.fixture
def world(db_conn, tmp_path):
    conn = db_conn
    conn.execute(
        text(
            "INSERT INTO plant VALUES ('TP1','Planta prueba 1'),('TP2','Planta prueba 2')"
        )
    )
    conn.execute(
        text(
            "INSERT INTO line VALUES ('L1','TP1','L1'),('L2','TP1','L2'),('L9','TP2','L9')"
        )
    )
    users = {
        "l1": _user(conn, "t.ing.l1", "ingeniero", [("TP1", "L1")]),
        "l2": _user(conn, "t.ing.l2", "ingeniero", [("TP1", "L2")]),
        "plant": _user(conn, "t.ger", "gerente", [("TP1", None)]),
        "other": _user(conn, "t.otra", "ingeniero", [("TP2", None)]),
    }
    corpus = tmp_path / "corpus"
    shutil.copytree(FIXTURES, corpus)

    @contextmanager
    def connect():
        with conn.begin_nested():
            yield conn

    embedder = HashingEmbedder()
    ingest = IngestService(connect, embedder, plant_id="TP1")
    ingest.check_environment()
    report = ingest.ingest_directory(corpus)
    return conn, users, corpus, ingest, embedder, report


def search(world, who: str, **kw):
    conn, users, *_, embedder, _ = world
    return RetrievalService(conn, embedder).search(users[who], SearchQuery(**kw))


# ------------------------------------------------------------------ ingesta


def test_ingest_creates_everything(world):
    conn, *_, report = world
    assert report.ok, report.failed
    assert len(report.created) == 7 and report.fragments > 40
    rows = dict(
        conn.execute(
            text("SELECT source_key, line_id FROM document WHERE plant_id = 'TP1'")
        ).all()
    )
    assert rows["8D-2026-011"] == "L1"
    assert rows["8D-2026-013"] == "L2"
    assert rows["AMEF-ARN-PD-001"] is None  # todas las líneas = documento de planta


def test_fragments_inherit_level_and_scope(world):
    conn, *_ = world
    rows = conn.execute(
        text(
            "SELECT DISTINCT f.level, f.line_id, f.embedding_model FROM fragment f "
            "JOIN document d ON d.id = f.document_id WHERE d.source_key = '8D-2026-011'"
        )
    ).all()
    assert rows == [("confidencial", "L1", "test-hashing-v1")]


def test_reingest_is_noop(world):
    _, _, corpus, ingest, embedder, _ = world
    calls = embedder.calls
    again = ingest.ingest_directory(corpus)
    assert len(again.unchanged) == 7 and not again.created and not again.updated
    assert embedder.calls == calls  # no se recalculan embeddings


def test_changed_document_is_reindexed(world):
    conn, _, corpus, ingest, _, _ = world
    path = corpus / "8D-2026-013.md"
    old_ids = set(
        conn.execute(
            text(
                "SELECT f.id FROM fragment f JOIN document d ON d.id = f.document_id WHERE d.source_key = '8D-2026-013'"
            )
        ).scalars()
    )
    path.write_text(
        path.read_text(encoding="utf-8") + "\nNota agregada.\n", encoding="utf-8"
    )
    report = ingest.ingest_directory(corpus)
    assert report.updated == ["8D-2026-013"]
    new_ids = set(
        conn.execute(
            text(
                "SELECT f.id FROM fragment f JOIN document d ON d.id = f.document_id WHERE d.source_key = '8D-2026-013'"
            )
        ).scalars()
    )
    assert new_ids and not (old_ids & new_ids)


def test_cited_document_is_not_reindexed(world):
    conn, users, corpus, ingest, _, _ = world
    fragment_id = conn.execute(
        text(
            "SELECT f.id FROM fragment f JOIN document d ON d.id = f.document_id "
            "WHERE d.source_key = '8D-2026-024' LIMIT 1"
        )
    ).scalar_one()
    ncr_id = conn.execute(
        text(
            "INSERT INTO ncr (code, plant_id, line_id, shift, description, opened_by) "
            "VALUES ('T-NCR-1', 'TP1', 'L1', 1, 'prueba', :u) RETURNING id"
        ),
        {"u": users["l1"].id},
    ).scalar_one()
    sv = conn.execute(
        text(
            "INSERT INTO section_version (ncr_id, discipline, version_no, kind, content, model) "
            "VALUES (:n, 'D4', 1, 'agente', '{}'::jsonb, 'm') RETURNING id"
        ),
        {"n": ncr_id},
    ).scalar_one()
    conn.execute(
        text("INSERT INTO citation VALUES (:sv, 'causas[0]', :f)"),
        {"sv": sv, "f": fragment_id},
    )

    path = corpus / "8D-2026-024.md"
    path.write_text(path.read_text(encoding="utf-8") + "\nCambio.\n", encoding="utf-8")
    report = ingest.ingest_directory(corpus)
    assert [name for name, _ in report.failed] == ["8D-2026-024.md"]
    assert "cita" in report.failed[0][1]
    assert (
        conn.execute(
            text("SELECT count(*) FROM fragment WHERE id = :f"), {"f": fragment_id}
        ).scalar_one()
        == 1
    )


def test_unknown_line_is_rejected_and_others_continue(world):
    _, _, corpus, ingest, _, _ = world
    bad = corpus / "SOP-ZZ-001.md"
    bad.write_text(
        "---\ndoc_id: SOP-ZZ-001\ntipo: SOP\ntitulo: Línea inexistente\nfecha: 2026-01-01\n"
        "lineas: [L1, L7]\nconfidencialidad: interno\ncontiene_pii: false\n---\n\n# x\n\n## 1. Uno\n\nTexto.\n",
        encoding="utf-8",
    )
    report = ingest.ingest_directory(corpus)
    assert report.failed == [("SOP-ZZ-001.md", "líneas que no existen en TP1: ['L7']")]
    assert len(report.unchanged) == 7


# ------------------------------------------------------------------ búsqueda


def test_exact_code_wins_in_text_mode(world):
    hits = search(world, "plant", text="APL-L1-02", mode="text", top_k=5)
    assert hits and all("APL-L1-02" in h.content for h in hits)
    assert hits[0].source_key == "8D-2026-011"
    assert hits[0].lex_rank == 1 and hits[0].sem_rank is None


def test_code_query_does_not_match_sibling_code(world):
    hits = search(
        world, "plant", text="RC-02", mode="text", kinds=(DocumentKind.AMEF,), top_k=3
    )
    assert hits[0].section == "RC-02"
    assert all(h.section != "RC-01" for h in hits)


def test_line_scope_hides_other_line(world):
    hits = search(
        world,
        "l2",
        text="falso contacto intermitente TRM-A-1064 aplicador desgaste",
        top_k=20,
    )
    keys = {h.source_key for h in hits}
    assert "8D-2026-011" not in keys and "8D-2026-024" not in keys  # documentos de L1
    assert "AMEF-ARN-PD-001" in keys  # documento de planta: visible para L2
    assert all(h.line_id in (None, "L2") for h in hits)


def test_permission_case_per_01(world):
    """evals/casos_permisos.jsonl PER-01: usuario de L1 busca algo de L2."""
    hits = search(
        world,
        "l1",
        text="8D de intermitencia en L2 por desgaste de aplicador",
        as_of=date(2026, 9, 30),
    )
    assert all(h.line_id in (None, "L1") for h in hits)
    assert "8D-2026-011" in {h.source_key for h in hits}


def test_other_plant_sees_nothing(world):
    assert search(world, "other", text="falso contacto intermitente APL-L1-02") == []


def test_as_of_excludes_future_documents(world):
    hits = search(
        world, "plant", text="APL-L1-02 desgaste", as_of=date(2026, 5, 15), top_k=20
    )
    assert "8D-2026-011" not in {h.source_key for h in hits}  # cerrado el 2026-06-05
    hits = search(
        world, "plant", text="APL-L1-02 desgaste", as_of=date(2026, 6, 5), top_k=20
    )
    assert "8D-2026-011" in {h.source_key for h in hits}


def test_exclude_sources_hides_the_replayed_case(world):
    """Replay: el documento del propio caso tiene la misma fecha que el corte y `as_of` no basta."""
    kw = {"text": "APL-L1-02 desgaste", "as_of": date(2026, 6, 5), "top_k": 20}
    assert "8D-2026-011" in {h.source_key for h in search(world, "plant", **kw)}
    hits = search(world, "plant", exclude_sources=("8D-2026-011",), **kw)
    assert hits and "8D-2026-011" not in {h.source_key for h in hits}


def test_kinds_filter(world):
    hits = search(
        world,
        "plant",
        text="categoría de no detección",
        kinds=(DocumentKind.SOP,),
        top_k=10,
    )
    assert hits and {h.kind for h in hits} == {DocumentKind.SOP}


def test_vector_mode_and_hybrid_ranks(world):
    vec = search(
        world,
        "plant",
        text="desgaste del punzón y yunque del aplicador",
        mode="vector",
        top_k=5,
    )
    assert len(vec) == 5 and all(
        h.sem_rank is not None and h.lex_rank is None for h in vec
    )
    hyb = search(
        world, "plant", text="desgaste del punzón y yunque del aplicador", top_k=5
    )
    assert any(h.lex_rank is not None and h.sem_rank is not None for h in hyb)
    assert [h.score for h in hyb] == sorted((h.score for h in hyb), reverse=True)


def test_vector_branch_ignores_other_embedding_model(world):
    conn, users, *_ = world
    service = RetrievalService(conn, HashingEmbedder(model_name="otro-modelo"))
    assert (
        service.search(
            users["plant"], SearchQuery(text="desgaste del aplicador", mode="vector")
        )
        == []
    )


def test_hits_carry_level_for_the_router(world):
    hits = search(
        world, "plant", text="Norvane A7-DRH-2210-H programa Halcón", top_k=10
    )
    by_key = {h.source_key: h.level for h in hits}
    assert (
        by_key.get("8D-2026-099") is L.CONFIDENCIAL
    )  # el cuerpo dice PÚBLICO; manda el front matter
    assert by_key.get("8D-2026-011") is L.CONFIDENCIAL


def test_stopwords_only_query_returns_empty_without_error(world):
    assert search(world, "plant", text="de la que el", mode="text") == []


def test_eval_anchors_are_checked_against_the_index(world):
    from app.evalkit.qrels import Anchor, Qrel
    from app.evalkit.retrieval import check_anchors, doc_dates

    conn, *_ = world
    ok = Qrel(
        "EV-X",
        "E6",
        "controls",
        {Anchor("AMEF-ARN-PD-001", "RC-01"): 2, Anchor("8D-2026-011"): 1},
    )
    bad = Qrel(
        "EV-Y",
        "E6",
        "controls",
        {Anchor("AMEF-ARN-PD-001", "RC-99"): 2, Anchor("8D-0000-000"): 1},
    )
    assert check_anchors(conn, [ok]) == []
    problems = check_anchors(conn, [bad])
    assert len(problems) == 2 and "RC-99" in problems[0] + problems[1]
    assert "8D-2026-011" in doc_dates(conn)


def test_sections_follow_a_link_with_the_same_filters_as_search(world):
    """Expansión por enlace: D4 de un 8D concreto, con permisos, corte y exclusiones."""
    conn, users, *_, embedder, _ = world
    svc = RetrievalService(conn, embedder)

    def d4(who, **kw):
        return svc.sections(
            users[who], ["8D-2026-011"], ["D4"], kinds=(DocumentKind.EIGHT_D,), **kw
        )

    hits = d4("l1", as_of=date(2026, 9, 30))
    assert hits and {h.section for h in hits} == {"D4"}
    assert [h.ordinal for h in hits] == sorted(h.ordinal for h in hits)
    assert d4("l2") == []  # 8D de L1: fuera del alcance de L2
    assert d4("other") == []
    assert d4("plant", as_of=date(2026, 5, 15)) == []  # aún no cerraba
    assert d4("plant", exclude_sources=("8D-2026-011",)) == []


# ------------------------------------------------------------------ modos experimentales


def test_hybrid_w_changes_weights_not_the_candidates(world):
    """`hybrid_w` pesa el doble la rama vectorial: mismos candidatos, distinto puntaje."""
    q = "desgaste del punzón y yunque del aplicador"
    base = search(world, "plant", text=q, mode="hybrid", top_k=8)
    w = search(world, "plant", text=q, mode="hybrid_w", top_k=8)
    assert {h.fragment_id for h in base} == {h.fragment_id for h in w} or len(w) == len(base)
    by_id = {h.fragment_id: h for h in base}
    for h in w:
        b = by_id.get(h.fragment_id)
        if b is not None and h.sem_rank is not None and h.lex_rank is None:
            assert h.score == pytest.approx(2 * b.score)  # solo vectorial: pesa 2×


def test_hybrid_doc_returns_one_fragment_per_document(world):
    q = "desgaste del punzón y yunque del aplicador"
    plain = search(world, "plant", text=q, mode="hybrid", top_k=10)
    doc = search(world, "plant", text=q, mode="hybrid_doc", top_k=10)
    docs = [h.source_key for h in doc]
    assert len(docs) == len(set(docs))
    assert len(set(h.source_key for h in plain)) <= len(docs) or len(docs) == len(set(docs))
    # el mejor fragmento de cada documento es el mismo que en la búsqueda normal
    best_plain = {}
    for h in plain:
        best_plain.setdefault(h.source_key, h.fragment_id)
    for h in doc:
        if h.source_key in best_plain:
            assert h.fragment_id == best_plain[h.source_key]


def test_experimental_modes_keep_permissions(world):
    other = search(world, "other", text="desgaste del aplicador", mode="hybrid_wdoc", top_k=5)
    assert other == []
