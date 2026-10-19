"""Servidor falso con el protocolo de OpenAI para pruebas de carga y de resiliencia.

    python -m app.evalkit.stub_llm            # escucha en :9000

Contesta `POST /chat/completions` con un D2 o un D4 válidos (arma los ids a partir del prompt,
igual que `FakeAgentLLM` de las pruebas) después de esperar una latencia fija. Sirve para medir
**la aplicación**: pool de conexiones, hilos, cola, base de datos. No mide ningún modelo.

Parámetros por variable de entorno (todos son supuestos del escenario, no mediciones):

    STUB_D2_S=40         segundos de espera por llamada de D2
    STUB_D4_S=100        segundos de espera por llamada de D4 (humo de Qwen 3.6 27B: ~98 s)
    STUB_JITTER=0.2      variación uniforme de +/- esa fracción
    STUB_D4_OUT_TOK=7000 tokens de salida que declara por llamada de D4 (humo: 6.5-7.1k)
    STUB_D2_OUT_TOK=1500
    STUB_REASONING=0.59  fracción de la salida que declara como razonamiento
    STUB_ERROR_RATE=0    fracción de llamadas que fallan con STUB_ERROR_STATUS
    STUB_ERROR_STATUS=429
    STUB_SEED=1

`GET /stats` devuelve llamadas, concurrencia máxima observada y errores inyectados.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import re
from dataclasses import dataclass, field

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


@dataclass
class StubConfig:
    d2_s: float = 40.0
    d4_s: float = 100.0
    jitter: float = 0.2
    d4_out_tok: int = 7000
    d2_out_tok: int = 1500
    reasoning: float = 0.59
    error_rate: float = 0.0
    error_status: int = 429
    seed: int = 1
    price_in_per_mtok: float = 0.32
    price_out_per_mtok: float = 3.20

    @classmethod
    def from_env(cls) -> StubConfig:
        def f(name: str, default: float) -> float:
            return float(os.environ.get(name, default))

        return cls(
            d2_s=f("STUB_D2_S", 40.0),
            d4_s=f("STUB_D4_S", 100.0),
            jitter=f("STUB_JITTER", 0.2),
            d4_out_tok=int(f("STUB_D4_OUT_TOK", 7000)),
            d2_out_tok=int(f("STUB_D2_OUT_TOK", 1500)),
            reasoning=f("STUB_REASONING", 0.59),
            error_rate=f("STUB_ERROR_RATE", 0.0),
            error_status=int(f("STUB_ERROR_STATUS", 429)),
            seed=int(f("STUB_SEED", 1)),
        )


@dataclass
class Stats:
    calls: int = 0
    in_flight: int = 0
    max_in_flight: int = 0
    injected_errors: int = 0
    by_stage: dict[str, int] = field(default_factory=lambda: {"D2": 0, "D4": 0})


def _h(texto: str, *fuentes: str) -> dict:
    return {"texto": texto, "fuentes": list(fuentes)}


def d2_body(prompt: str) -> dict:
    tools = re.findall(r'<fuente id="(T\d+)"', prompt)
    src = ["NCR", *tools[:1]]
    return {
        k: _h(f"{k}: descrito a partir del reporte y los datos", *src)
        for k in ("que", "por_que", "donde", "cuando", "quien", "como", "cuanto")
    }


def d4_body(prompt: str, occ=("RC-01", "RC-03", "RC-02"), nd="ND-01") -> dict:
    catalog = {
        code: fid
        for fid, code in re.findall(r"- \[(F\d+)\] [^\n]*?(RC-\d\d|ND-\d\d) — ", prompt)
    }
    blocks = re.findall(r'<fuente id="(F\d+|T\d+)"[^>]*>(.*?)</fuente>', prompt, re.DOTALL)

    def cause(code: str) -> dict:
        case = [i for i, b in blocks if i.startswith("F") and code in b]
        return {
            "codigo": code,
            "explicacion": "Desgaste de herramental por operar más ciclos de los permitidos sin mantenimiento.",
            "evidencia": [
                _h("hecho respaldado por las fuentes citadas", *case[:1], catalog.get(code, "F1"))
            ],
            "pregunta_confirmacion": "¿Qué dicen las hojas de verificación del equipo en ese periodo?",
        }

    return {
        "estado": "candidato_respaldado",
        "causas_ocurrencia": [cause(c) for c in occ],
        "causa_no_deteccion": cause(nd),
    }


def make_app(config: StubConfig | None = None) -> FastAPI:
    cfg = config or StubConfig.from_env()
    rng = random.Random(cfg.seed)
    stats = Stats()
    app = FastAPI(title="stub-llm")
    app.state.stats = stats
    app.state.config = cfg

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.get("/stats")
    async def get_stats() -> dict:
        return {
            "calls": stats.calls,
            "in_flight": stats.in_flight,
            "max_in_flight": stats.max_in_flight,
            "injected_errors": stats.injected_errors,
            "by_stage": stats.by_stage,
        }

    @app.post("/v1/chat/completions")
    @app.post("/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        prompt = "\n".join(str(m.get("content") or "") for m in body.get("messages", []))
        stage = "D4" if "D4 (causa raíz)" in prompt else "D2"
        stats.calls += 1
        stats.by_stage[stage] += 1
        stats.in_flight += 1
        stats.max_in_flight = max(stats.max_in_flight, stats.in_flight)
        try:
            wait = cfg.d4_s if stage == "D4" else cfg.d2_s
            wait *= 1 + rng.uniform(-cfg.jitter, cfg.jitter)
            if wait > 0:
                await asyncio.sleep(wait)
            if cfg.error_rate and rng.random() < cfg.error_rate:
                stats.injected_errors += 1
                return JSONResponse(
                    {"error": {"message": "stub: error inyectado", "code": cfg.error_status}},
                    status_code=cfg.error_status,
                    headers={"Retry-After": "1"},
                )
            payload = d4_body(prompt) if stage == "D4" else d2_body(prompt)
            tin = max(1, len(prompt) // 4)
            tout = cfg.d4_out_tok if stage == "D4" else cfg.d2_out_tok
            cost = tin * cfg.price_in_per_mtok / 1e6 + tout * cfg.price_out_per_mtok / 1e6
            return {
                "id": "stub",
                "model": body.get("model", "stub"),
                "provider": "StubLLM",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(payload, ensure_ascii=False),
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": tin,
                    "completion_tokens": tout,
                    "completion_tokens_details": {"reasoning_tokens": int(tout * cfg.reasoning)},
                    "cost": cost,
                },
            }
        finally:
            stats.in_flight -= 1

    return app


app = make_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "9000")))
