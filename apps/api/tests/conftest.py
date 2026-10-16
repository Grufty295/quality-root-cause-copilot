"""Configuración común de pruebas.

Dos tipos de prueba:

* Puras (chunker, códigos, router LLM): corren siempre, sin base.
* Con base (`test_auth.py` y `*_db.py`): necesitan un Postgres real con las
  migraciones aplicadas. Sin DATABASE_URL no se recolectan.

    make test                               # dentro del contenedor, base eightd_test
    DATABASE_URL=... python -m pytest       # fuera, contra una base de pruebas

No uses la base de la demo: las pruebas crean y modifican usuarios.

Antes, un pytest.skip a nivel de módulo en este archivo abortaba toda la
recolección sin DATABASE_URL, incluidas las pruebas que no usan base.
"""

import os

import pytest

HAS_DB = "DATABASE_URL" in os.environ

if not HAS_DB:
    collect_ignore = ["test_auth.py"]
    collect_ignore_glob = ["*_db.py"]


# Variables que la app lee del entorno y que el .env de la maquina (env_file del compose)
# mete en el contenedor. Las pruebas definen las suyas con monkeypatch; heredar las del .env
# hace que pasen o fallen segun quien las corra.
_ISOLATED_PREFIXES = ("LLM_", "LANGFUSE_")
_ISOLATED_VARS = ("TRACE_EXPORTER", "GIT_SHA", "ENTORNO")


@pytest.fixture(autouse=True)
def _isolate_app_env(monkeypatch):
    for name in list(os.environ):
        if name.startswith(_ISOLATED_PREFIXES) or name in _ISOLATED_VARS:
            monkeypatch.delenv(name, raising=False)


@pytest.fixture(scope="session")
def db_engine():
    if not HAS_DB:
        pytest.skip("DATABASE_URL no definido")
    from app.core.db import get_engine

    return get_engine()


@pytest.fixture
def db_conn(db_engine):
    """Conexión en una transacción que se revierte al terminar la prueba."""
    with db_engine.connect() as conn:
        trans = conn.begin()
        try:
            yield conn
        finally:
            trans.rollback()


# --- fixtures de test_auth.py (sin cambios de comportamiento) ------------------
# Se importan dentro de las fixtures para que este archivo cargue sin base.


TEST_USERS = (
    ("insp.l1", "Inspector L1", "inspector", [("JRZ1", "L1")]),
    ("insp.l2", "Inspector L2", "inspector", [("JRZ1", "L2")]),
    ("ing.l1", "Ingeniero L1", "ingeniero", [("JRZ1", "L1")]),
    ("ing.l2", "Ingeniero L2", "ingeniero", [("JRZ1", "L2")]),
    ("gerente.jrz1", "Gerente JRZ1", "gerente", [("JRZ1", None)]),
    ("auditor.jrz1", "Auditor JRZ1", "auditor", [("JRZ1", None)]),
    ("ing.jrz2", "Ingeniero JRZ2", "ingeniero", [("JRZ2", None)]),
)


@pytest.fixture(scope="session")
def catalog_and_users(db_engine):
    from sqlalchemy import text

    from app.modules.auth import repository as auth_repo

    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO plant VALUES ('JRZ1','Planta 1'),('JRZ2','Planta 2') ON CONFLICT DO NOTHING"
            )
        )
        conn.execute(
            text(
                "INSERT INTO line VALUES ('L1','JRZ1','Linea 1'),('L2','JRZ1','Linea 2'),('L1','JRZ2','Linea 1') "
                "ON CONFLICT DO NOTHING"
            )
        )
        # Usuarios propios de las pruebas, con nombres que dicen su alcance. No son
        # los de la demo (app.modules.auth.demo_users): esas pruebas no deben
        # depender de que el dataset cambie.
        for username, display_name, role, scopes in TEST_USERS:
            user_id = auth_repo.upsert_user(
                conn, username=username, display_name=display_name, role=role
            )
            auth_repo.replace_scopes(conn, user_id, scopes)
    yield


@pytest.fixture(autouse=True)
def _auth_catalog(request):
    # Antes era autouse para todo el árbol; ahora solo test_auth.py lo necesita
    # y las pruebas puras no deben tocar la base.
    if request.module.__name__.endswith("test_auth"):
        request.getfixturevalue("catalog_and_users")


@pytest.fixture(autouse=True)
def fresh_settings(monkeypatch):
    if not HAS_DB:
        yield
        return
    from app.core.config import get_settings

    monkeypatch.setenv("DEMO_LOGIN", "true")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(catalog_and_users):
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app)


def login(client, username: str):
    return client.post("/auth/demo-login", json={"username": username})
