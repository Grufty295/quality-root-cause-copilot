"""Editar, rechazar y aprobar secciones por HTTP, con el trigger de roles de la base."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from tests.conftest import login

NCR = {
    "plant_id": "JRZ1",
    "line_id": "L1",
    "shift": 2,
    "description": "Terminal con falso contacto intermitente",
}
DRAFT = {"resumen": "borrador del agente"}


@pytest.fixture
def ncr(client, db_engine):
    """NCR abierta por un inspector de L1, con un borrador de D2 del agente (version 1)."""
    login(client, "insp.l1")
    created = client.post("/ncrs", json=NCR).json()
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO section_version (ncr_id, discipline, version_no, kind, content, model) "
                "VALUES (:n, 'D2', 1, 'agente', CAST(:c AS jsonb), 'mock')"
            ),
            {"n": created["id"], "c": '{"resumen": "borrador del agente"}'},
        )
    return created


def act(client, username: str, ncr, action: str, discipline: str = "D2", **body):
    login(client, username)
    return client.post(f"/ncrs/{ncr['id']}/sections/{discipline}/{action}", json=body)


def status(client, ncr) -> str:
    login(client, "gerente.jrz1")
    return client.get(f"/ncrs/{ncr['id']}").json()["status"]


def test_engineer_edit_creates_new_version(client, ncr):
    r = act(
        client,
        "ing.l1",
        ncr,
        "edit",
        based_on_version=1,
        content={"resumen": "corregido"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["version_no"], body["kind"], body["author"]) == (
        2,
        "edicion",
        "ing.l1",
    )
    assert body["content"] == {"resumen": "corregido"}
    assert status(client, ncr) == "pendiente_aprobacion"


def test_manager_approves_the_exact_text_reviewed(client, ncr):
    act(
        client,
        "ing.l1",
        ncr,
        "edit",
        based_on_version=1,
        content={"resumen": "corregido"},
    )
    r = act(client, "gerente.jrz1", ncr, "approve", based_on_version=2)
    assert r.status_code == 200, r.text
    assert (r.json()["version_no"], r.json()["kind"]) == (3, "aprobacion")
    assert r.json()["content"] == {"resumen": "corregido"}
    assert status(client, ncr) == "aprobada"


def test_manager_can_approve_an_unedited_agent_draft(client, ncr):
    assert (
        act(client, "gerente.jrz1", ncr, "approve", based_on_version=1).status_code
        == 200
    )


def test_stale_version_is_conflict(client, ncr):
    act(client, "ing.l1", ncr, "edit", based_on_version=1, content={"resumen": "uno"})
    # El gerente aun veia la version 1.
    r = act(client, "gerente.jrz1", ncr, "approve", based_on_version=1)
    assert r.status_code == 409
    assert "version vigente es la 2" in r.json()["detail"]
    r = act(
        client, "ing.l1", ncr, "edit", based_on_version=1, content={"resumen": "dos"}
    )
    assert r.status_code == 409


@pytest.mark.parametrize("username", ["insp.l1", "gerente.jrz1", "auditor.jrz1"])
def test_only_engineer_edits(client, ncr, username):
    assert (
        act(
            client, username, ncr, "edit", based_on_version=1, content={"a": 1}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("username", ["insp.l1", "auditor.jrz1"])
def test_inspector_and_auditor_cannot_reject(client, ncr, username):
    assert (
        act(
            client, username, ncr, "reject", based_on_version=1, feedback="x" * 20
        ).status_code
        == 403
    )


@pytest.mark.parametrize("username", ["insp.l1", "ing.l1", "auditor.jrz1"])
def test_only_manager_approves(client, ncr, username):
    assert act(client, username, ncr, "approve", based_on_version=1).status_code == 403


def test_reject_needs_feedback_and_hands_back_to_the_agent(client, ncr):
    assert (
        act(
            client, "ing.l1", ncr, "reject", based_on_version=1, feedback="no"
        ).status_code
        == 422
    )
    r = act(
        client,
        "ing.l1",
        ncr,
        "reject",
        based_on_version=1,
        feedback="La causa no cita el 8D correcto",
    )
    assert r.status_code == 200, r.text
    assert (r.json()["kind"], r.json()["content"]) == ("rechazo", None)
    assert r.json()["feedback"] == "La causa no cita el 8D correcto"
    assert status(client, ncr) == "en_analisis"


def test_rejected_section_cannot_be_rejected_again_or_approved(client, ncr):
    act(
        client,
        "ing.l1",
        ncr,
        "reject",
        based_on_version=1,
        feedback="Falta evidencia del turno",
    )
    assert (
        act(
            client,
            "ing.l1",
            ncr,
            "reject",
            based_on_version=2,
            feedback="Falta evidencia del turno",
        ).status_code
        == 409
    )
    assert (
        act(client, "gerente.jrz1", ncr, "approve", based_on_version=2).status_code
        == 409
    )


def test_engineer_can_write_after_a_rejection(client, ncr):
    act(
        client,
        "ing.l1",
        ncr,
        "reject",
        based_on_version=1,
        feedback="Falta evidencia del turno",
    )
    r = act(
        client,
        "ing.l1",
        ncr,
        "edit",
        based_on_version=2,
        content={"resumen": "rehecho a mano"},
    )
    assert r.status_code == 200
    assert status(client, ncr) == "pendiente_aprobacion"


def test_approved_section_is_final(client, ncr):
    act(client, "gerente.jrz1", ncr, "approve", based_on_version=1)
    assert (
        act(
            client, "ing.l1", ncr, "edit", based_on_version=2, content={"a": 1}
        ).status_code
        == 409
    )
    assert (
        act(
            client, "ing.l1", ncr, "reject", based_on_version=2, feedback="x" * 20
        ).status_code
        == 409
    )
    assert (
        act(client, "gerente.jrz1", ncr, "approve", based_on_version=2).status_code
        == 409
    )


def test_section_without_draft_is_conflict(client, ncr):
    assert (
        act(
            client, "ing.l1", ncr, "edit", "D4", based_on_version=1, content={"a": 1}
        ).status_code
        == 409
    )


def test_ncr_is_approved_only_when_every_drafted_section_is(client, ncr, db_engine):
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO section_version (ncr_id, discipline, version_no, kind, content, model) "
                "VALUES (:n, 'D4', 1, 'agente', CAST(:c AS jsonb), 'mock')"
            ),
            {"n": ncr["id"], "c": '{"causas": []}'},
        )
    act(client, "gerente.jrz1", ncr, "approve", "D2", based_on_version=1)
    assert status(client, ncr) == "pendiente_aprobacion"
    act(client, "gerente.jrz1", ncr, "approve", "D4", based_on_version=1)
    assert status(client, ncr) == "aprobada"


def test_scope_is_enforced(client, ncr):
    assert (
        act(
            client, "ing.l2", ncr, "edit", based_on_version=1, content={"a": 1}
        ).status_code
        == 404
    )
    assert (
        act(
            client, "ing.jrz2", ncr, "edit", based_on_version=1, content={"a": 1}
        ).status_code
        == 404
    )


def test_who_opened_cannot_approve(client, db_engine):
    """La regla vive en la base: aunque la API deje pasar la peticion, el trigger la frena."""
    with db_engine.begin() as conn:
        manager = conn.execute(
            text("SELECT id FROM app_user WHERE username = 'gerente.jrz1'")
        ).scalar_one()
        ncr_id = conn.execute(
            text(
                "INSERT INTO ncr (code, plant_id, line_id, shift, description, opened_by) "
                "VALUES ('NCR-TEST-' || substr(gen_random_uuid()::text, 1, 8), 'JRZ1', 'L1', 1, 'abierta por el gerente', :u) "
                "RETURNING id"
            ),
            {"u": manager},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO section_version (ncr_id, discipline, version_no, kind, content, model) "
                "VALUES (:n, 'D2', 1, 'agente', CAST('{\"a\": 1}' AS jsonb), 'mock')"
            ),
            {"n": ncr_id},
        )
    r = act(client, "gerente.jrz1", {"id": str(ncr_id)}, "approve", based_on_version=1)
    assert r.status_code == 403
    assert "no puede aprobarla" in r.json()["detail"]


@pytest.mark.parametrize(
    "bad",
    [
        {"based_on_version": 0, "content": {"a": 1}},
        {"based_on_version": 1, "content": {}},
        {"content": {"a": 1}},
    ],
)
def test_invalid_edit_is_422(client, ncr, bad):
    assert act(client, "ing.l1", ncr, "edit", **bad).status_code == 422


def test_unknown_discipline_is_422(client, ncr):
    assert (
        act(
            client, "ing.l1", ncr, "edit", "D9", based_on_version=1, content={"a": 1}
        ).status_code
        == 422
    )


def test_unauthenticated_is_401(client, ncr):
    client.cookies.clear()
    assert (
        client.post(
            f"/ncrs/{ncr['id']}/sections/D2/approve", json={"based_on_version": 1}
        ).status_code
        == 401
    )


def test_manager_sends_an_edited_section_back_with_feedback(client, ncr):
    act(
        client,
        "ing.l1",
        ncr,
        "edit",
        based_on_version=1,
        content={"resumen": "corregido"},
    )
    r = act(
        client,
        "gerente.jrz1",
        ncr,
        "reject",
        based_on_version=2,
        feedback="Falta citar el AMEF del aplicador",
    )
    assert r.status_code == 200, r.text
    assert (r.json()["kind"], r.json()["author"]) == ("rechazo", "gerente.jrz1")
    assert status(client, ncr) == "en_analisis"

    # El ingeniero ve la retroalimentacion del gerente y corrige.
    login(client, "ing.l1")
    sections = client.get(f"/ncrs/{ncr['id']}/sections").json()
    assert sections[0]["feedback"] == "Falta citar el AMEF del aplicador"
    fixed = act(
        client,
        "ing.l1",
        ncr,
        "edit",
        based_on_version=3,
        content={"resumen": "con AMEF"},
    )
    assert fixed.status_code == 200
    assert (
        act(client, "gerente.jrz1", ncr, "approve", based_on_version=4).status_code
        == 200
    )


def test_manager_rejection_needs_feedback(client, ncr):
    assert (
        act(
            client, "gerente.jrz1", ncr, "reject", based_on_version=1, feedback="mal"
        ).status_code
        == 422
    )
