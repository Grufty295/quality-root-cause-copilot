"""Diagnóstico de la conexión con el modelo: por qué falla una llamada y con qué parámetro.

    docker compose exec api python -m app.evalkit.diagnose            # destino local
    docker compose exec api python -m app.evalkit.diagnose --dest api
    docker compose exec api python -m app.evalkit.diagnose --caso EV-01   # agente real, 1 caso
    make llm-diagnose

Corre DENTRO del contenedor, así que ve exactamente las variables LLM_* que ve el agente
(si el .env cambió y el contenedor no se recreó, aquí se nota). Pasos:

1. Configuración efectiva: URL, modelos, extra_body, y una huella de la API key (prefijo,
   largo y últimos 4). Nunca la key completa.
2. Solo OpenRouter: estado de la key (`GET /key`) y proveedores que sirven cada modelo
   (`GET /models/{modelo}/endpoints`): slug, cuantización, contexto, tope de salida y si
   aceptan `reasoning` / `response_format`.
3. Una matriz de llamadas mínimas ("Responde solo: ok", sin datos de casos) que quita un
   parámetro a la vez: así se ve cuál rompe. La última imita lo que pide el agente en D4
   (max_tokens=8192 y, si está activo, json_mode).

A diferencia del cliente del agente, aquí SÍ se imprime el mensaje de error del proveedor:
el prompt es trivial y no hay nada confidencial que se pueda filtrar.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Mapping
from typing import Any

import httpx

AGENT_MAX_TOKENS = 8192  # gateway.complete_structured
PROMPT = [{"role": "user", "content": "Responde solo: ok"}]


def key_fingerprint(key: str | None) -> str:
    if not key:
        return "VACÍA (no llegó LLM_*__API_KEY al contenedor)"
    return f"{key[:9]}… (largo {len(key)}, termina en …{key[-4:]})"


def strip(body: Mapping[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in body.items() if k not in keys}


def variants(
    model: str, extra: Mapping[str, Any], json_mode: bool
) -> list[tuple[str, dict[str, Any]]]:
    """Cada variante quita una cosa respecto de la configuración real."""
    base = {
        **extra,
        "model": model,
        "messages": PROMPT,
        "temperature": 0.0,
        "max_tokens": 256,
    }
    out = [("configuración real (extra_body completo)", base)]
    if "reasoning" in extra:
        out.append(("sin `reasoning`", strip(base, "reasoning")))
    if "provider" in extra:
        out.append(("sin `provider`", strip(base, "provider")))
    if extra:
        out.append(("sin extra_body", strip(base, *extra.keys())))
    agent_like = {**base, "max_tokens": AGENT_MAX_TOKENS}
    label = f"como el agente en D4 (max_tokens={AGENT_MAX_TOKENS}"
    if json_mode:
        agent_like["response_format"] = {"type": "json_object"}
        label += ", json_mode"
    out.append((label + ")", agent_like))
    if extra:
        # Separa "el tope de salida es demasiado alto" de lo que rompa extra_body.
        out.append(
            (
                f"solo max_tokens={AGENT_MAX_TOKENS}, sin extra_body",
                strip(agent_like, *extra.keys()),
            )
        )
    return out


def explain(status: int, err: Mapping[str, Any]) -> str:
    msg = str(err.get("message", ""))
    meta = err.get("metadata") or {}
    hints = {
        400: "parámetro inválido o no soportado por el proveedor (mira qué variante pasa)",
        401: "API key inválida, revocada o vacía",
        402: "sin créditos en la cuenta o en el límite de la key",
        403: "bloqueo de permisos, moderación o presupuesto agotado",
        404: "modelo inexistente, o ningún proveedor cumple `provider`/`data_collection`",
        408: "timeout del proveedor",
        429: "rate limit",
    }
    parts = [f"HTTP {status}", hints.get(status, "")]
    if msg:
        parts.append(f"mensaje: {msg[:400]}")
    if meta:
        parts.append(f"metadata: {json.dumps(meta, ensure_ascii=False)[:600]}")
    return " · ".join(p for p in parts if p)


async def _get(http: httpx.AsyncClient, path: str) -> tuple[int, Any]:
    try:
        r = await http.get(path)
    except httpx.HTTPError as exc:
        return 0, f"{type(exc).__name__}: {exc}"
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, r.text[:400]


def _print_endpoints(model: str, status: int, data: Any) -> None:
    if status != 200 or not isinstance(data, dict):
        print(f"  {model}: no se pudo listar (HTTP {status}) {str(data)[:300]}")
        return
    eps = (data.get("data") or {}).get("endpoints") or []
    if not eps:
        print(f"  {model}: SIN proveedores (¿slug del modelo correcto?)")
        return
    print(f"  {model}: {len(eps)} proveedor(es)")
    for e in eps:
        params = set(e.get("supported_parameters") or [])
        print(
            "   - "
            + " · ".join(
                str(x)
                for x in (
                    e.get("provider_name") or e.get("name"),
                    f"slug={e.get('tag') or e.get('provider_slug') or '?'}",
                    f"quant={e.get('quantization') or '?'}",
                    f"ctx={e.get('context_length') or '?'}",
                    f"max_out={e.get('max_completion_tokens') or '?'}",
                    f"reasoning={'sí' if 'reasoning' in params else 'no'}",
                    f"response_format={'sí' if 'response_format' in params else 'no'}",
                    f"estado={e.get('status', '?')}",
                )
            )
        )


async def diagnose(
    dest_name: str, transport: httpx.AsyncBaseTransport | None = None
) -> int:
    from app.agent.llm import Destination
    from app.agent.llm.config import get_llm_settings

    try:
        settings = get_llm_settings()
    except Exception as exc:  # noqa: BLE001  el diagnóstico debe mostrar cualquier error de config
        print(f"La configuración LLM_* no carga: {type(exc).__name__}: {exc}")
        return 2
    dest = settings.destination(Destination(dest_name))
    key = dest.api_key.get_secret_value() if dest.api_key else None
    base_url = str(dest.base_url).rstrip("/")
    print("== 1. Configuración efectiva dentro del contenedor")
    print(
        f"  destino     {dest_name} · simulado={dest.simulated} · etiqueta {dest.provider_label}"
    )
    print(f"  base_url    {base_url}")
    print(f"  modelos     small={dest.model_small} · large={dest.model_large}")
    print(f"  extra_body  {json.dumps(dest.extra_body, ensure_ascii=False)}")
    print(f"  json_mode   {dest.json_mode} · timeout {dest.timeout_s}s")
    print(f"  api_key     {key_fingerprint(key)}")

    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    models = list(dict.fromkeys((dest.model_small, dest.model_large)))
    failures = 0
    async with httpx.AsyncClient(
        base_url=base_url,
        headers=headers,
        timeout=httpx.Timeout(dest.timeout_s, connect=10),
        transport=transport,
    ) as http:
        if "openrouter.ai" in base_url:
            print("\n== 2. OpenRouter")
            status, data = await _get(http, "/key")
            if status == 200 and isinstance(data, dict):
                d = data.get("data") or data
                print(
                    "  key válida · "
                    + " · ".join(
                        f"{k}={d.get(k)}"
                        for k in (
                            "label",
                            "usage",
                            "limit",
                            "limit_remaining",
                            "is_free_tier",
                        )
                        if k in d
                    )
                )
            else:
                print(f"  key: HTTP {status} {str(data)[:300]}")
                if status == 401:
                    print(
                        "  → la key no sirve: revisa LLM_*__API_KEY en .env y recrea el contenedor"
                    )
            for model in models:
                status, data = await _get(http, f"/models/{model}/endpoints")
                _print_endpoints(model, status, data)

        print("\n== 3. Matriz de llamadas mínimas")
        for model in models:
            for label, body in variants(model, dest.extra_body, dest.json_mode):
                try:
                    r = await http.post("/chat/completions", json=body)
                except httpx.HTTPError as exc:
                    failures += 1
                    print(f"  FALLA  {model} · {label}: {type(exc).__name__}: {exc}")
                    continue
                try:
                    payload = r.json()
                except ValueError:
                    payload = {"error": {"message": r.text[:400]}}
                err = payload.get("error") if isinstance(payload, dict) else None
                if r.status_code >= 400 or isinstance(err, dict):
                    failures += 1
                    print(
                        f"  FALLA  {model} · {label}: {explain(r.status_code, err or {})}"
                    )
                    continue
                usage = payload.get("usage") or {}
                details = usage.get("completion_tokens_details") or {}
                choice = (payload.get("choices") or [{}])[0]
                print(
                    f"  ok     {model} · {label}: proveedor {payload.get('provider', '?')} · "
                    f"{usage.get('prompt_tokens')}→{usage.get('completion_tokens')} tok"
                    f" (razonamiento {details.get('reasoning_tokens', 0)}) · "
                    f"finish={choice.get('finish_reason')} · costo {usage.get('cost', '?')}"
                )
    print(
        "\nSi falla la configuración real y pasa alguna variante, el parámetro que quita esa "
        "variante es el culpable. Si fallan todas con 401/402, es la key o el saldo."
        if failures
        else "\nTodas las llamadas pasaron: la configuración funciona fuera del agente."
    )
    return 1 if failures else 0


def replay_variants(
    body: Mapping[str, Any], provider: str | None
) -> list[tuple[str, dict[str, Any]]]:
    """Variantes del request REAL que falló: separa parámetro, proveedor, tamaño y contenido."""
    b = dict(body)
    out: list[tuple[str, dict[str, Any]]] = [("request real, tal cual", b)]
    if "reasoning" in b:
        out.append(("sin `reasoning`", strip(b, "reasoning")))
    if "provider" in b:
        out.append(("sin `provider`", strip(b, "provider")))
    out.append(("max_tokens=1024", {**b, "max_tokens": 1024}))
    if "response_format" in b:
        out.append(("sin response_format", strip(b, "response_format")))
    if provider:
        prov = dict(b.get("provider") or {})
        prov["ignore"] = [provider]
        out.append((f"ignorando al proveedor {provider}", {**b, "provider": prov}))
    msgs = list(b.get("messages") or [])
    if msgs:
        # Mismo formato, contenido mínimo: si esto pasa, el problema es el texto (tamaño,
        # moderación del proveedor), no los parámetros.
        tiny = [{**m, "content": "Responde solo: ok"} for m in msgs[:1]]
        out.append(("mismos parámetros, mensaje trivial", {**b, "messages": tiny}))
        cut = [
            {**m, "content": (m.get("content") or "")[:3000]}
            if i == len(msgs) - 1
            else m
            for i, m in enumerate(msgs)
        ]
        out.append(
            ("último mensaje recortado a 3000 caracteres", {**b, "messages": cut})
        )
    return out


async def diagnose_case(
    caso_id: str,
    evals_dir: str,
    out_dir: str,
    transport: httpx.AsyncBaseTransport | None = None,
) -> int:
    """Corre el agente real en un caso con LLM_DEBUG_HTTP, captura el request rechazado y lo
    repite con variantes. Gasta lo de una corrida de D4 (o casi nada si falla)."""
    from pathlib import Path

    from app.agent.llm import openai_compat
    from app.agent.llm.config import get_llm_settings
    from app.agent.runtime import build_deps, close_deps
    from app.core.db import get_engine
    from app.evalkit.agent import run_once
    from app.evalkit.retrieval import load_cases

    cases, _, _ = load_cases(Path(evals_dir))
    case = next((c for c in cases if c["caso_id"] == caso_id), None)
    if case is None:
        print(f"no existe {caso_id}")
        return 2
    openai_compat._DEBUG_HTTP = True
    openai_compat.LAST_FAILED.clear()
    print(
        f"Corriendo el agente real en {caso_id}: son varias llamadas al modelo y puede tardar "
        "varios minutos sin imprimir nada; el resultado sale al terminar.",
        flush=True,
    )
    engine = get_engine()
    deps = build_deps(engine)
    try:
        row = await run_once(engine, deps, case, "base", 0)
    finally:
        await close_deps(deps)

    print(f"== Corrida del agente en {caso_id} (NCR {row['ncr_code']})")
    print(
        f"  generado={row['score']['generated']} · causas {row['score']['codes']} · llamadas {row['llm_calls']}"
    )
    for k, v in (row["blocked"] or {}).items():
        print(f"  bloqueado {k}: {v[:300]}")
    for e in row.get("llm_errors") or []:
        print(f"  audit_log: {e}")
    failed = dict(openai_compat.LAST_FAILED)
    if not failed:
        print(
            "\nNingún request fue rechazado por HTTP. Si aun así no hubo D4, el problema está "
            "después de la respuesta (formato, guardrails): mira `bloqueado` arriba."
        )
        return 0 if row["score"]["generated"] else 1

    body = failed["body"]
    try:
        err = json.loads(failed["response"]).get("error") or {}
    except (ValueError, AttributeError):
        err = {"message": failed["response"][:400]}
    print(f"\n== Request rechazado: {explain(failed['status'], err)}")
    msgs = body.get("messages") or []
    print(
        f"  modelo {body.get('model')} · {len(msgs)} mensajes · "
        f"{sum(len(str(m.get('content') or '')) for m in msgs):,} caracteres · "
        f"max_tokens {body.get('max_tokens')} · temperature {body.get('temperature')}"
    )
    dump = Path(out_dir) / f"llm-debug-{caso_id}.json"
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text(json.dumps(failed, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  request y respuesta completos en {dump} (datos ficticios del dataset)")

    settings = get_llm_settings()
    dest = (
        settings.local
        if body.get("model") in (settings.local.model_small, settings.local.model_large)
        else settings.api
    )
    assert dest is not None
    key = dest.api_key.get_secret_value() if dest.api_key else None
    headers = {
        "Content-Type": "application/json",
        **({"Authorization": f"Bearer {key}"} if key else {}),
    }
    provider = (err.get("metadata") or {}).get("provider_name")
    print("\n== Repetición con variantes")
    async with httpx.AsyncClient(
        base_url=str(dest.base_url).rstrip("/"),
        headers=headers,
        timeout=httpx.Timeout(dest.timeout_s, connect=10),
        transport=transport,
    ) as http:
        for label, variant in replay_variants(body, provider):
            try:
                r = await http.post("/chat/completions", json=variant)
            except httpx.HTTPError as exc:
                print(f"  FALLA  {label}: {type(exc).__name__}")
                continue
            try:
                payload = r.json()
            except ValueError:
                payload = {"error": {"message": r.text[:300]}}
            e = payload.get("error") if isinstance(payload, dict) else None
            if r.status_code >= 400 or isinstance(e, dict):
                print(f"  FALLA  {label}: {explain(r.status_code, e or {})}")
            else:
                print(f"  ok     {label}: proveedor {payload.get('provider', '?')}")
    print(
        "\nLa primera variante que pasa dice qué cambiar. Si solo pasa el mensaje trivial, el "
        "problema es el contenido o el tamaño del prompt, no la configuración."
    )
    return 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--dest", choices=("local", "api"), default="local")
    ap.add_argument(
        "--caso",
        help="corre el agente real en este caso (p. ej. EV-01), captura el request que falla y lo repite con variantes",
    )
    ap.add_argument("--evals", default="/workspace/evals")
    ap.add_argument("--out-dir", default="/workspace/traces")
    args = ap.parse_args(argv)
    if args.caso:
        return asyncio.run(diagnose_case(args.caso, args.evals, args.out_dir))
    return asyncio.run(diagnose(args.dest))


if __name__ == "__main__":
    sys.exit(main())
