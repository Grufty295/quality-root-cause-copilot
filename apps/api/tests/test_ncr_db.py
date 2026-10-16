"""NCR por HTTP contra Postgres real: quien abre, alcance y borradores en solo lectura."""

from __future__ import annotations

import re

import pytest
from sqlalchemy import text

from tests.conftest import login

BASE = {
    "plant_id": "JRZ1",
    "line_id": "L1",
    "shift": 3,
    "description": "Terminal con falso contacto intermitente",
}


@pytest.fixture(autouse=True)
def _catalog(catalog_and_users, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO customer (id, name, is_confidential) VALUES "
                "('TC1','Cliente Prueba 1', true), ('TC2','Cliente Prueba 2', false) ON CONFLICT DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO part (id, part_number, customer_id, description) VALUES "
                "('TP-001','TP-001','TC1','Parte de prueba') ON CONFLICT DO NOTHING"
            )
        )


def open_ncr(client, as_user: str, **overrides):
    login(client, as_user)
    return client.post("/ncrs", json={**BASE, **overrides})


def test_inspector_opens_in_own_line(client):
    r = open_ncr(client, "insp.l1")
    assert r.status_code == 201, r.text
    body = r.json()
    assert re.fullmatch(r"NCR-\d{4}-\d{4}", body["code"])
    assert body["status"] == "abierta"
    assert (
        body["detected_level"] == "interno"
    )  # lo fija el clasificador; nunca queda sin clasificar
    assert body["contains_pii"] is False
    assert body["classification_reasons"] == ["sin_hallazgos"]
    assert body["part_number"] is None and body["customer_id"] is None


def test_engineer_can_also_open(client):
    assert open_ncr(client, "ing.l1").status_code == 201


@pytest.mark.parametrize("username", ["gerente.jrz1", "auditor.jrz1"])
def test_manager_and_auditor_cannot_open(client, username):
    assert open_ncr(client, username).status_code == 403


def test_unauthenticated_is_401(client):
    assert client.post("/ncrs", json=BASE).status_code == 401
    assert client.get("/ncrs").status_code == 401


def test_cannot_open_outside_own_line(client):
    assert open_ncr(client, "insp.l2", line_id="L1").status_code == 403
    assert open_ncr(client, "ing.jrz2", line_id="L1").status_code == 403


def test_unknown_line_is_422(client):
    assert open_ncr(client, "insp.l1", line_id="L99").status_code == 422


def test_customer_comes_from_part(client):
    r = open_ncr(client, "insp.l1", part_number="TP-001")
    assert r.status_code == 201
    assert r.json()["customer_id"] == "TC1"


def test_part_and_customer_must_agree(client):
    assert (
        open_ncr(client, "insp.l1", part_number="TP-001", customer_id="TC2").status_code
        == 422
    )
    assert open_ncr(client, "insp.l1", part_number="NO-EXISTE").status_code == 422
    assert open_ncr(client, "insp.l1", customer_id="NO-EXISTE").status_code == 422


@pytest.mark.parametrize(
    "bad",
    [
        {"shift": 0},
        {"shift": 4},
        {"description": "corta"},
        {"description": "x" * 4001},
        {"extra": "campo"},
    ],
)
def test_invalid_payload_is_422(client, bad):
    assert open_ncr(client, "insp.l1", **bad).status_code == 422


def test_codes_increase(client):
    a = open_ncr(client, "insp.l1").json()["code"]
    b = open_ncr(client, "insp.l1").json()["code"]
    assert int(b[-4:]) == int(a[-4:]) + 1


def test_visibility_follows_scope(client):
    ncr = open_ncr(client, "insp.l1").json()
    path = f"/ncrs/{ncr['id']}"

    def sees(username: str) -> tuple[int, bool]:
        login(client, username)
        listed = ncr["id"] in {n["id"] for n in client.get("/ncrs").json()}
        return client.get(path).status_code, listed

    assert sees("insp.l1") == (200, True)
    assert sees("ing.l1") == (200, True)
    assert sees("gerente.jrz1") == (200, True)  # alcance de planta
    assert sees("auditor.jrz1") == (200, True)
    assert sees("ing.l2") == (404, False)  # otra linea: no revela que existe
    assert sees("insp.l2") == (404, False)
    assert sees("ing.jrz2") == (404, False)  # otra planta


def test_sections_read_only_latest_without_trace_fields(client, db_engine):
    ncr = open_ncr(client, "insp.l1").json()
    with db_engine.begin() as conn:
        for version, note in ((1, "primero"), (2, "segundo")):
            conn.execute(
                text(
                    "INSERT INTO section_version (ncr_id, discipline, version_no, kind, content, model, trace_id) "
                    "VALUES (:n, 'D2', :v, 'agente', CAST(:c AS jsonb), 'mock', 'trace-1')"
                ),
                {"n": ncr["id"], "v": version, "c": f'{{"nota": "{note}"}}'},
            )

    for username in ("insp.l1", "ing.l1", "gerente.jrz1", "auditor.jrz1"):
        login(client, username)
        sections = client.get(f"/ncrs/{ncr['id']}/sections").json()
        assert [(s["discipline"], s["version_no"], s["content"]) for s in sections] == [
            ("D2", 2, {"nota": "segundo"})
        ]
        assert {"model", "trace_id", "prompt_version", "index_version"}.isdisjoint(
            sections[0]
        )

    login(client, "ing.l2")
    assert client.get(f"/ncrs/{ncr['id']}/sections").status_code == 404


def test_inspector_cannot_write_sections(client):
    ncr = open_ncr(client, "insp.l1").json()
    for method in ("post", "put", "patch", "delete"):
        r = getattr(client, method)(f"/ncrs/{ncr['id']}/sections")
        assert r.status_code in (404, 405)


# --- clasificacion al abrir ---------------------------------------------------------


def classified(client, **overrides):
    r = open_ncr(client, "insp.l1", **overrides)
    assert r.status_code == 201, r.text
    return r.json()


def test_confidential_customer_part_makes_the_ncr_confidential(client):
    body = classified(client, part_number="TP-001")
    assert body["detected_level"] == "confidencial"
    assert "campo:confidencial" in body["classification_reasons"]


def test_non_confidential_customer_stays_internal(client):
    body = classified(client, customer_id="TC2")
    assert body["detected_level"] == "interno"


def test_customer_named_in_the_text_is_enough(client):
    body = classified(
        client, description="Reclamo de Cliente Prueba 1 por conector incompleto"
    )
    assert body["detected_level"] == "confidencial"
    assert "cliente:confidencial" in body["classification_reasons"]


def test_unknown_part_shaped_code_is_confidential(client):
    body = classified(
        client, description="Defecto repetido en Z9-QWE-7788 durante el turno"
    )
    assert body["detected_level"] == "confidencial"
    assert "parte_desconocida" in body["classification_reasons"]


def test_pii_is_flagged_without_raising_the_level(client):
    body = classified(
        client, description="El operador Juan Perez cambio el aplicador sin avisar"
    )
    assert body["contains_pii"] is True
    assert body["detected_level"] == "interno"
    assert "pii:persona" in body["classification_reasons"]


def test_classification_is_stored_and_listed(client):
    created = classified(client, part_number="TP-001")
    login(client, "ing.l1")
    got = client.get(f"/ncrs/{created['id']}").json()
    assert (got["detected_level"], got["contains_pii"]) == ("confidencial", False)
    listed = {n["id"]: n for n in client.get("/ncrs").json()}
    assert listed[created["id"]]["detected_level"] == "confidencial"


def test_reasons_do_not_leak_the_matched_text(client):
    body = classified(
        client,
        description="Reclamo de Cliente Prueba 1, operador Juan Perez, nomina 48213",
    )
    joined = " ".join(body["classification_reasons"]).lower()
    assert "prueba" not in joined and "juan" not in joined and "48213" not in joined
