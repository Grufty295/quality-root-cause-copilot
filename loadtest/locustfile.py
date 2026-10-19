"""Prueba de carga de /analyze con el servidor falso de LLM (app/evalkit/stub_llm.py).

Mide la aplicación (pool de conexiones, hilos, base), no un modelo. Ver docs/operacion/prueba-de-carga.md.

    # una ola de 5 ingenieros que pulsan "analizar" a la vez, más un lector que sondea la API
    locust -f loadtest/locustfile.py --headless -u 6 -r 6 -t 10m --host http://localhost:8000 \
        --csv traces/carga/ola-5 Analista Lector

Variables de entorno:
    LOAD_USERS    usuarios ingeniero de la demo, separados por coma (default u-ingcal-1,u-ingcal-2)
    LOAD_PLANT    planta de las NCR que se crean (default JRZ1)
    LOAD_LINE     línea (default L1)
    LOAD_REPEAT   0 = cada Analista hace un análisis y termina (ola); 1 = repite sin parar (default 0)
    LOAD_TIMEOUT  segundos que se espera la respuesta de /analyze (default 900)

Cada análisis usa una NCR nueva con una parte confidencial: así todo va al destino local (el stub) y ninguna
corrida se reutiliza ni se salta por tener ya un borrador.
"""

from __future__ import annotations

import itertools
import os
import uuid

from locust import HttpUser, between, constant, task
from locust.exception import StopUser

USERS = [u.strip() for u in os.environ.get("LOAD_USERS", "u-ingcal-1,u-ingcal-2").split(",") if u.strip()]
PLANT = os.environ.get("LOAD_PLANT", "JRZ1")
LINE = os.environ.get("LOAD_LINE", "L1")
REPEAT = os.environ.get("LOAD_REPEAT", "0") == "1"
TIMEOUT = float(os.environ.get("LOAD_TIMEOUT", "900"))
_next_user = itertools.count()

DESCRIPTION = (
    "Falso contacto intermitente en terminales crimpadas de la línea 1, turno 2, "
    "aplicador con desgaste. Prueba de carga {tag}."
)


def _login(client, username: str) -> None:
    with client.post("/auth/demo-login", json={"username": username}, name="POST /auth/demo-login", catch_response=True) as r:
        if r.status_code != 200:
            r.failure(f"login {username}: {r.status_code} {r.text[:120]}")


class Analista(HttpUser):
    """Un ingeniero de calidad: abre una NCR y pide el análisis."""

    wait_time = constant(1)

    def on_start(self) -> None:
        self.username = USERS[next(_next_user) % len(USERS)]
        _login(self.client, self.username)

    @task
    def analizar(self) -> None:
        tag = uuid.uuid4().hex[:8]
        with self.client.post(
            "/ncrs",
            json={
                "plant_id": PLANT,
                "line_id": LINE,
                "shift": 2,
                "description": DESCRIPTION.format(tag=tag),
                "part_number": "A7-DRH-2210-M",
            },
            name="POST /ncrs",
            catch_response=True,
        ) as r:
            if r.status_code != 201:
                r.failure(f"no se pudo abrir la NCR: {r.status_code} {r.text[:160]}")
                raise StopUser()
            ncr_id = r.json()["id"]

        with self.client.post(
            f"/ncrs/{ncr_id}/analyze",
            json={},
            headers={"Idempotency-Key": f"carga-{tag}-{uuid.uuid4().hex}"},
            name="POST /ncrs/:id/analyze",
            timeout=TIMEOUT,
            catch_response=True,
        ) as r:
            if r.status_code != 200:
                r.failure(f"{r.status_code} {r.text[:160]}")
            else:
                body = r.json()
                if body.get("status") != "completada":
                    r.failure(f"estado {body.get('status')}: {body.get('blocked')}")
        if not REPEAT:
            raise StopUser()


class Lector(HttpUser):
    """Un usuario que solo consulta. Si la aplicación se satura, él lo siente primero."""

    fixed_count = 1
    wait_time = between(1.5, 2.5)

    def on_start(self) -> None:
        _login(self.client, os.environ.get("LOAD_READER", "u-insp-l1"))

    @task(3)
    def yo(self) -> None:
        self.client.get("/auth/me", name="GET /auth/me")

    @task(1)
    def lista(self) -> None:
        self.client.get("/ncrs?limit=20", name="GET /ncrs")
