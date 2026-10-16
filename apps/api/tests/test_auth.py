from fastapi import Depends
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.db import get_engine
from app.main import app
from app.modules.auth import repository as repo
from app.modules.auth.deps import require_role
from app.modules.auth.models import CurrentUser
from app.modules.auth.service import AuthService
from app.utils.crypto import hash_token
from tests.conftest import login


# Endpoint de prueba para require_role
@app.post("/_test/solo-gerente")
def _solo_gerente(user: CurrentUser = Depends(require_role("gerente"))):
    return {"ok": user.username}


# --- capa HTTP ----------------------------------------------------------------

def test_me_sin_cookie_401(client):
    assert client.get("/auth/me").status_code == 401


def test_login_usuario_desconocido_401(client):
    r = login(client, "no.existe")
    assert r.status_code == 401
    assert r.json() == {"detail": "Usuario desconocido o inactivo"}


def test_login_cookie_httponly_y_me(client):
    r = login(client, "ing.l2")
    assert r.status_code == 200
    set_cookie = r.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/" in set_cookie

    me = client.get("/auth/me").json()
    assert me["username"] == "ing.l2"
    assert me["role"] == "ingeniero"
    assert me["scopes"] == [{"plant_id": "JRZ1", "line_id": "L2"}]


def test_logout_revoca_aunque_se_reuse_la_cookie(client):
    login(client, "ing.l1")
    token = client.cookies.get("sid")
    assert client.post("/auth/logout").status_code == 204
    attacker = TestClient(app, cookies={"sid": token})
    assert attacker.get("/auth/me").status_code == 401


def test_demo_login_apagado_404(client, monkeypatch):
    monkeypatch.setenv("DEMO_LOGIN", "false")
    get_settings.cache_clear()
    assert login(client, "ing.l1").status_code == 404
    assert client.get("/auth/demo-users").status_code == 404


def test_demo_users_lista(client):
    users = {u["username"] for u in client.get("/auth/demo-users").json()}
    assert {"ing.l1", "ing.l2", "gerente.jrz1", "auditor.jrz1", "ing.jrz2"} <= users


def test_require_role(client):
    login(client, "ing.l2")
    assert client.post("/_test/solo-gerente").status_code == 403
    login(client, "gerente.jrz1")
    assert client.post("/_test/solo-gerente").json() == {"ok": "gerente.jrz1"}


def test_origin_ajeno_bloqueado_y_propio_permitido(client):
    r = client.post("/auth/demo-login", json={"username": "ing.l1"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/auth/demo-login", json={"username": "ing.l1"}, headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200


# --- sesion (base de datos) ---------------------------------------------------

def test_token_solo_se_guarda_hasheado(client):
    login(client, "ing.l1")
    token = client.cookies.get("sid")
    with get_engine().connect() as conn:
        n_hash = conn.execute(
            text("SELECT count(*) FROM app_session WHERE token_hash = :h"), {"h": hash_token(token)}
        ).scalar_one()
        n_claro = conn.execute(
            text("SELECT count(*) FROM app_session WHERE token_hash = convert_to(:t, 'UTF8')"), {"t": token}
        ).scalar_one()
    assert n_hash == 1 and n_claro == 0


def test_cookie_alterada_401(client):
    login(client, "ing.l1")
    token = client.cookies.get("sid")
    forged = TestClient(app, cookies={"sid": token[:-1] + ("A" if token[-1] != "A" else "B")})
    assert forged.get("/auth/me").status_code == 401


def test_sesion_expirada_401(client):
    login(client, "ing.l1")
    token = client.cookies.get("sid")
    with get_engine().begin() as conn:
        conn.execute(
            text("UPDATE app_session SET created_at = now() - interval '2 days', "
                 "expires_at = now() - interval '1 second' WHERE token_hash = :h"),
            {"h": hash_token(token)},
        )
    assert client.get("/auth/me").status_code == 401


def test_usuario_desactivado_pierde_la_sesion(client):
    login(client, "ing.jrz2")
    with get_engine().begin() as conn:
        conn.execute(text("UPDATE app_user SET is_active = false WHERE username = 'ing.jrz2'"))
    try:
        assert client.get("/auth/me").status_code == 401
        assert login(client, "ing.jrz2").status_code == 401
    finally:
        with get_engine().begin() as conn:
            conn.execute(text("UPDATE app_user SET is_active = true WHERE username = 'ing.jrz2'"))


def test_cambio_de_alcance_aplica_sin_relogin(client):
    login(client, "ing.l1")
    with get_engine().begin() as conn:
        uid = conn.execute(text("SELECT id FROM app_user WHERE username='ing.l1'")).scalar_one()
        conn.execute(text("INSERT INTO user_scope VALUES (:u,'JRZ1','L2')"), {"u": uid})
    try:
        lines = {s["line_id"] for s in client.get("/auth/me").json()["scopes"]}
        assert lines == {"L1", "L2"}
    finally:
        with get_engine().begin() as conn:
            conn.execute(text("DELETE FROM user_scope WHERE user_id=:u AND line_id='L2'"), {"u": uid})


# --- capa de repositorio: reglas de alcance (regresion del bug de 0001) -------

def test_alcance_planta_vs_linea():
    with get_engine().begin() as conn:
        def user(name):
            return repo.get_user(conn, repo.find_active_user_id(conn, name))

        def can(u, plant, line):
            return repo.user_can_access(conn, u.id, plant, line)

        ing_l2, gerente, ing_jrz2 = user("ing.l2"), user("gerente.jrz1"), user("ing.jrz2")

        assert can(ing_l2, "JRZ1", "L2") is True
        assert can(ing_l2, "JRZ1", "L1") is False
        assert can(ing_l2, "JRZ1", None) is False   # antes devolvia True
        assert can(gerente, "JRZ1", None) is True
        assert can(ing_jrz2, "JRZ1", "L2") is False

        assert repo.allowed_lines(conn, ing_l2.id, "JRZ1") == ["L2"]
        assert repo.allowed_lines(conn, gerente.id, "JRZ1") == ["L1", "L2"]
        assert repo.allowed_lines(conn, ing_jrz2.id, "JRZ1") == []


def test_servicio_ensure_access_lanza_403():
    from app.core.errors import Forbidden

    with get_engine().begin() as conn:
        service = AuthService(conn)
        ing_l2 = repo.get_user(conn, repo.find_active_user_id(conn, "ing.l2"))
        service.ensure_access(ing_l2, "JRZ1", "L2")
        try:
            service.ensure_access(ing_l2, "JRZ1", None)
            raise AssertionError("debia lanzar Forbidden")
        except Forbidden as e:
            assert e.status_code == 403
