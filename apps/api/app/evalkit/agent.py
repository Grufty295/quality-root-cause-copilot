"""Eval del agente: corre D4 sobre los casos EV-xx y lo puntúa contra `esperado`.

    docker compose exec api python -m app.evalkit.agent                      # dev, base + enlace, 3 repeticiones
    docker compose exec api python -m app.evalkit.agent --repeats 1 --casos EV-01,EV-05
    docker compose exec api python -m app.evalkit.agent --report-only        # rehace el reporte sin llamar al modelo

GASTA DINERO y manda datos a donde diga el router (LLM_*). Los datos son ficticios.

Cada corrida abre una NCR nueva a partir del caso (los casos de evaluación no están en el
corpus, así que no hace falta excluir nada), con fecha de reporte = `as_of` del caso, y
genera solo D4. Cada resultado se agrega como una línea a `<nombre>.runs.jsonl` en cuanto
termina: si se corta, al volver a correr retoma donde se quedó (misma clave
caso/variante/repetición). El reporte se rehace siempre desde ese archivo.

Variantes:
- `base`:   el agente como está.
- `enlace`: con `expand_case_links` (NCR o 8D del top → D4 de ese 8D). Ver docs/evaluacion.md.
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import statistics
import sys
import time
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, date, datetime
from datetime import time as dtime
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, text

from app.evalkit.qrels import DEV_EPISODES, TEST_EPISODES, split_of
from app.evalkit.retrieval import DEFAULT_EVALS, DEFAULT_OUT, load_cases
from app.evalkit.scoring import score_d4

PLANT = "JRZ1"
VARIANTS = {"base": False, "enlace": True}
_SHIFTS = {"T1": 1, "T2": 2, "T3": 3}


# ------------------------------------------------------------------ una corrida


def ncr_draft(case: Mapping[str, Any]) -> Any:
    from app.modules.ncr.models import NcrDraft

    n = case["ncr"]
    return NcrDraft(
        plant_id=PLANT,
        line_id=n["linea"].split(",")[0].strip(),
        # Un reclamo de cliente no trae turno: entra como 1, el turno no es el dato.
        shift=_SHIFTS.get(n.get("turno") or "", 1),
        description=n["descripcion"],
        part_number=n.get("numero_parte") or None,
    )


async def run_once(
    engine: Engine, deps: Any, case: Mapping[str, Any], variant: str, rep: int
) -> dict[str, Any]:
    from app.agent.service import AnalysisService
    from app.modules.auth import repository as auth_repo
    from app.modules.ncr.service import NcrService

    as_of = date.fromisoformat(case["as_of"])
    username = case["usuario"]["usuario_id"]
    with engine.begin() as conn:
        uid = auth_repo.find_active_user_id(conn, username)
        user = auth_repo.get_user(conn, uid) if uid else None
        if user is None:
            raise SystemExit(f"el usuario {username!r} no existe (¿corriste el seed?)")
        ncr = NcrService(conn).open(user, ncr_draft(case))
        conn.execute(
            text("UPDATE ncr SET created_at = :ts WHERE id = :id"),
            {"ts": datetime.combine(as_of, dtime(12), UTC), "id": ncr.id},
        )

    from app.agent.observe import RecordingObserver

    variant_deps = dataclasses.replace(deps, expand_case_links=VARIANTS[variant])
    recorder = RecordingObserver(keep_evidence=True)
    started = time.perf_counter()
    started_at = datetime.now(UTC)
    error = None
    sections: dict[str, Any] = {}
    blocked: dict[str, str] = {}
    events: list[dict[str, str]] = []
    calls: list[dict[str, Any]] = []
    run_info: dict[str, Any] = {}
    try:
        result = await AnalysisService(variant_deps).analyze(
            user, ncr.id, disciplines=("D4",), as_of=as_of, observer=recorder
        )
        sections, blocked, events = result.sections, result.blocked, result.events
        calls = [dataclasses.asdict(c) for c in result.calls]
        run_info = {
            "run_id": result.run_id,
            "run_status": result.status,
            "config_id": result.config_id,
            "stage_ms": result.stage_ms,
        }
    except Exception as exc:  # noqa: BLE001  una corrida rota no detiene el eval; queda registrada
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
    wall_ms = int((time.perf_counter() - started) * 1000)
    record = next(iter(recorder.runs.values()), None)

    with engine.connect() as conn:
        audit = (
            conn.execute(
                text(
                    "SELECT stage::text, provider, model, tokens_in, tokens_out, cost_usd, "
                    "latency_ms, tags FROM audit_log WHERE ncr_id = :n ORDER BY id"
                ),
                {"n": ncr.id},
            )
            .mappings()
            .all()
        )

    content = (sections.get("D4") or {}).get("content")
    reported = [r["tags"].get("reported_cost_usd") for r in audit if r["tags"]]
    return {
        "caso_id": case["caso_id"],
        "episodio": case["episodio"],
        "split": split_of(case["episodio"]),
        "variant": variant,
        "rep": rep,
        "ncr_code": ncr.code,
        "ncr_id": str(ncr.id),
        "user_id": str(user.id),
        **run_info,
        "dims": case_dims(case),
        "error": error,
        "blocked": blocked,
        "score": score_d4(content, case["esperado"]),
        "events": [e.get("event") for e in events],
        "llm_error_classes": [
            str(e.get("detail")) for e in events if e.get("event") == "llm_error"
        ],
        "linked_8d": [
            e.get("detail") for e in events if e.get("event") == "expansion_enlace"
        ],
        "calls": calls,
        "llm_calls": len(audit),
        # "length" = la salida se cortó por max_tokens (sube max_tokens o baja el razonamiento).
        "finish_reasons": [
            str((r["tags"] or {}).get("finish_reason"))
            for r in audit
            if (r["tags"] or {}).get("finish_reason")
        ],
        "providers": sorted({str(r["provider"]) for r in audit}),
        "models": sorted({str(r["model"]) for r in audit}),
        "tokens_in": sum(int(r["tokens_in"] or 0) for r in audit),
        "tokens_out": sum(int(r["tokens_out"] or 0) for r in audit),
        "reasoning_tokens": sum(
            int((r["tags"] or {}).get("reasoning_tokens", 0)) for r in audit
        ),
        "cost_est_usd": float(sum(Decimal(r["cost_usd"] or 0) for r in audit)),
        "cost_reported_usd": (
            float(sum(Decimal(c) for c in reported if c is not None))
            if any(c is not None for c in reported)
            else None
        ),
        "wall_ms": wall_ms,
        # Para medir la concurrencia real de la serie (observed_concurrency).
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        # Tipo y estado HTTP de cada llamada fallida, tal como quedó en audit_log (sin texto libre).
        "llm_errors": [
            str((r["tags"] or {}).get("error"))
            for r in audit
            if (r["tags"] or {}).get("outcome") not in (None, "ok")
        ],
        "content": content,
        "unsafe_output": unsafe_output(content),
        # Texto de lo citado y de lo recuperado, para el juez (app/evalkit/semantic.py). Son
        # datos ficticios y el archivo queda local; con datos reales esto no se escribe.
        **evidence_for_judge(content, record),
    }


def case_dims(case: Mapping[str, Any]) -> dict[str, str]:
    """Dimensiones para desglosar: un promedio alto puede esconder una línea o un tipo de caso
    que falla siempre."""
    exp, ncr = case["esperado"], case["ncr"]
    return {
        "tipo": "recurrente" if exp.get("recurrente") else "causa_nueva",
        "episodio": case["episodio"],
        "detectado_en": ncr.get("detectado_en") or "—",
        "linea": (ncr.get("linea") or "—").split(",")[0].strip(),
        "defecto": ncr.get("defecto_codigo") or "—",
        "nivel": exp.get("nivel_minimo_contexto") or "—",
        "causa_esperada": exp["causa_ocurrencia"],
    }


def unsafe_output(content: Mapping[str, Any] | None) -> list[str]:
    """Vuelve a pasar lo persistido por los chequeos de culpa y cierre. Debe salir vacío siempre:
    si no, un borrador llegó a la base saltándose el guardrail. Es un gate de tolerancia cero."""
    if not content:
        return []
    from app.agent.guardrails import check_blame, check_closing

    texts: list[str] = []
    for c in [
        *(content.get("causas_ocurrencia") or []),
        content.get("causa_no_deteccion"),
    ]:
        if not c:
            continue
        texts += [c.get("explicacion") or "", c.get("pregunta_confirmacion") or ""]
        texts += [c.get("refutaria") or "", c.get("dato_faltante") or ""]
        texts += [
            h.get("texto") or ""
            for h in [
                *(c.get("evidencia") or []),
                *(c.get("evidencia_contradictoria") or []),
            ]
        ]
    return sorted({v.code for v in [*check_blame(texts), *check_closing(texts)]})


def evidence_for_judge(
    content: Mapping[str, Any] | None, record: Any
) -> dict[str, Any]:
    if record is None or not record.evidence:
        return {"evidencia": {}, "recuperados": {}}
    by_fragment = {
        v["fragment_id"]: k for k, v in record.evidence.items() if v.get("fragment_id")
    }
    retrieved = {
        search: [by_fragment.get(str(r.fragment_id)) for r in refs]
        for search, refs in record.retrieved.items()
    }
    cited: set[str] = set()
    for c in [
        *((content or {}).get("causas_ocurrencia") or []),
        (content or {}).get("causa_no_deteccion"),
    ]:
        for h in [
            *((c or {}).get("evidencia") or []),
            *((c or {}).get("evidencia_contradictoria") or []),
        ]:
            cited |= set(h.get("fuentes") or [])
    keep = cited | {i for ids in retrieved.values() for i in ids if i}
    return {
        "evidencia": {k: v for k, v in record.evidence.items() if k in keep},
        "recuperados": retrieved,
    }


_NO_ANSWER = "No se pudo obtener una respuesta del modelo"


# Clases que significan "la infraestructura no entregó una respuesta": no miden al modelo.
_INFRA_ERRORS = frozenset({"LLMTransportError", "LLMRequestError", "LLMResponseError"})
# Clases de política: el router o el inspector bloquearon la llamada. Es un hallazgo, no un fallo del proveedor.
_POLICY_ERRORS = frozenset({"PolicyViolation", "RedactionFailed"})


def _error_classes(row: Mapping[str, Any]) -> set[str]:
    """Clases de excepción de la corrida. Fuente principal: eventos del grafo (nombre exacto).
    Respaldo: tags.error de la auditoría, formato 'Clase: detalle'."""
    classes = {str(c) for c in (row.get("llm_error_classes") or [])}
    classes |= {str(m).split(":", 1)[0].strip() for m in (row.get("llm_errors") or [])}
    return classes


def classify_run(row: Mapping[str, Any]) -> str:
    if row["score"].get("generated"):
        return "ok"
    if row.get("error"):  # excepción del propio harness
        return "invalida"
    errs = _error_classes(row)
    if errs & _POLICY_ERRORS:
        return "bloqueada"
    if errs & _INFRA_ERRORS:
        return "invalida"
    if "StructuredOutputError" in errs:
        return "fail"
    # Clase desconocida, o fila anterior a `llm_error_classes` que dice "sin respuesta":
    # no se puede afirmar que midió al modelo.
    if errs or any(_NO_ANSWER in str(v) for v in (row.get("blocked") or {}).values()):
        return "invalida"
    return "ok"  # sin borrador por guardrails: respuesta real del modelo


def is_invalid(row: Mapping[str, Any]) -> bool:
    return classify_run(row) == "invalida"


# ------------------------------------------------------------------ agregación (pura)


def observed_concurrency(rows: Sequence[Mapping[str, Any]]) -> int | None:
    """Máximo de corridas que estuvieron en curso a la vez (filas con started_at/finished_at)."""
    marks: list[tuple[datetime, int]] = []
    for r in rows:
        if r.get("started_at") and r.get("finished_at"):
            marks.append((datetime.fromisoformat(r["started_at"]), 1))
            marks.append((datetime.fromisoformat(r["finished_at"]), -1))
    if not marks:
        return None
    now = peak = 0
    for _, step in sorted(
        marks, key=lambda m: (m[0], m[1])
    ):  # el fin antes que el inicio
        now += step
        peak = max(peak, now)
    return peak


def _mean(values: Iterable[float | None]) -> float | None:
    present = [float(v) for v in values if v is not None]
    return sum(present) / len(present) if present else None


def _pct(values: Sequence[float], q: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, round(q * (len(ordered) - 1)))]


def _rate(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    """Promedio de una métrica booleana por caso y luego por episodio (macro)."""
    by_ep: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        v = r["score"].get(key)
        if v is not None:
            by_ep[r["episodio"]][r["caso_id"]].append(float(v))
    return _mean(
        _mean(_mean(vals) for vals in cases.values()) for cases in by_ep.values()
    )


def _pass_hat_k(rows: Sequence[Mapping[str, Any]]) -> tuple[float | None, int]:
    """pass^k: fracción de casos que pasan en TODAS sus repeticiones (macro por episodio).

    Devuelve también el k mínimo observado: con k distinto entre casos, pass^k no es comparable.
    """
    per_case: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for r in rows:
        per_case[(r["episodio"], r["caso_id"])].append(bool(r["score"]["pass"]))
    if not per_case:
        return None, 0
    by_ep: dict[str, list[float]] = defaultdict(list)
    for (ep, _), passes in per_case.items():
        by_ep[ep].append(1.0 if all(passes) else 0.0)
    k = min(len(p) for p in per_case.values())
    return _mean(_mean(v) for v in by_ep.values()), k


def aggregate(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        groups[(r["variant"], r["split"])].append(r)
        groups[(r["variant"], "all")].append(r)
    out = []
    for (variant, split), all_rs in sorted(groups.items()):
        # Las corridas inválidas (el modelo no respondió) no miden al modelo: se cuentan
        # aparte y no entran a ninguna tasa. Si todas son inválidas, las tasas salen vacías.
        rs = [r for r in all_rs if not is_invalid(r)]
        recurrent = [r for r in rs if r["score"]["recurrent"]]
        new_cause = [r for r in rs if not r["score"]["recurrent"]]
        pass_k, k = _pass_hat_k(rs)
        kinds = [classify_run(r) for r in all_rs]
        invalid_by_case: dict[str, int] = defaultdict(int)
        for r, kind in zip(all_rs, kinds):
            if kind == "invalida":
                invalid_by_case[r["caso_id"]] += 1
        escalated = [
            any(c.get("stage") == "D4" and c.get("tier") == "large" for c in r["calls"])
            for r in rs
        ]
        costs = [r["cost_est_usd"] for r in rs]
        reported = [
            r["cost_reported_usd"] for r in rs if r["cost_reported_usd"] is not None
        ]
        walls = [float(r["wall_ms"]) for r in rs]
        providers: dict[str, set[str]] = defaultdict(set)
        for r in rs:
            for p in r["providers"]:
                providers[",".join(r["models"])].add(p)
        out.append(
            {
                "variant": variant,
                "split": split,
                "runs": len(all_rs),
                "cases": len({r["caso_id"] for r in all_rs}),
                "episodes": len({r["episodio"] for r in all_rs}),
                "errors": len(all_rs) - len(rs),
                # Respondió pero sin salida válida para el esquema: cuenta como no-pass.
                "structured_fails": kinds.count("fail"),
                # El router o el inspector frenaron la llamada: cuenta como no-pass, se reporta aparte.
                "policy_blocked": kinds.count("bloqueada"),
                "invalid_by_case": dict(sorted(invalid_by_case.items())),
                "llm_calls_mean": _mean(r.get("llm_calls") for r in rs),
                "truncated_calls": sum(
                    (r.get("finish_reasons") or []).count("length") for r in all_rs
                ),
                "generated": _rate(rs, "generated"),
                "pass@1": _rate(rs, "pass"),
                "pass^k": pass_k,
                "k": k,
                "rc_top1": _rate(rs, "rc_top1"),
                "rc_top3": _rate(rs, "rc_top3"),
                "nd_ok": _rate(rs, "nd_ok"),
                "rc_top1_recurrent": _rate(recurrent, "rc_top1"),
                "rc_top1_new_cause": _rate(new_cause, "rc_top1"),
                "top1_cites_precedent": _rate(recurrent, "top1_cites_precedent"),
                "top1_cites_foreign_8d": _rate(rs, "top1_cites_foreign_8d"),
                "top1_cites_foreign_8d_new_cause": _rate(
                    new_cause, "top1_cites_foreign_8d"
                ),
                "expected_rc_discarded": _rate(rs, "expected_rc_discarded"),
                "abstained": _rate(rs, "abstained"),
                "false_abstention": _rate(rs, "false_abstention"),
                "abstention_correct": _rate(rs, "abstention_correct"),
                "estado_downgraded": _rate(rs, "estado_downgraded"),
                "with_contradictions": _mean(
                    1.0 if r["score"].get("contradictions") else 0.0 for r in rs
                ),
                "unsafe_output_runs": sum(1 for r in rs if r.get("unsafe_output")),
                "invalid_rate": (len(all_rs) - len(rs)) / len(all_rs)
                if all_rs
                else None,
                "config_ids": sorted(
                    {r["config_id"] for r in all_rs if r.get("config_id")}
                ),
                "escalated_to_large": _mean(1.0 if e else 0.0 for e in escalated),
                "cost_est_usd_mean": _mean(costs),
                "cost_reported_usd_mean": _mean(reported),
                "tokens_in_mean": _mean(r["tokens_in"] for r in rs),
                "tokens_out_mean": _mean(r["tokens_out"] for r in rs),
                "reasoning_tokens_mean": _mean(r["reasoning_tokens"] for r in rs),
                "wall_ms_p50": statistics.median(walls) if walls else None,
                "wall_ms_p95": _pct(walls, 0.95),
                "providers_by_model": {m: sorted(p) for m, p in providers.items()},
            }
        )
    return out


BREAKDOWN_DIMS = ("tipo", "episodio", "detectado_en", "linea", "defecto", "nivel")


def breakdown(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Por variante y dimensión: pass@1, RC top-1 y abstención en cada valor (corridas válidas).

    Las celdas tienen pocos casos: sirven para encontrar dónde falla, no para comparar valores."""
    out: dict[str, Any] = {}
    valid = [r for r in rows if not is_invalid(r) and r.get("dims")]
    for variant in sorted({r["variant"] for r in valid}):
        vr = [r for r in valid if r["variant"] == variant]
        out[variant] = {}
        for dim in BREAKDOWN_DIMS:
            groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
            for r in vr:
                groups[r["dims"].get(dim, "—")].append(r)
            out[variant][dim] = {
                value: {
                    "casos": len({r["caso_id"] for r in g}),
                    "corridas": len(g),
                    "pass@1": _rate(g, "pass"),
                    "rc_top1": _rate(g, "rc_top1"),
                    "abstained": _rate(g, "abstained"),
                }
                for value, g in sorted(groups.items())
            }
    return out


def paired(
    rows: Sequence[Mapping[str, Any]], a: str = "base", b: str = "enlace"
) -> dict[str, Any]:
    """Comparación caso a caso entre dos variantes (tasa de pass por caso).

    Con 12 casos un promedio esconde demasiado: aquí se ve cuántos casos mejoran, empeoran o
    no cambian, y cuáles.
    """
    rate: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        rate[(r["variant"], r["caso_id"])].append(1.0 if r["score"]["pass"] else 0.0)
    cases = sorted({c for (_, c) in rate})
    better, worse, same = [], [], []
    for c in cases:
        ra, rb = _mean(rate.get((a, c), [])), _mean(rate.get((b, c), []))
        if ra is None or rb is None:
            continue
        (better if rb > ra else worse if rb < ra else same).append(c)
    return {"a": a, "b": b, "mejora": better, "empeora": worse, "igual": same}


# ------------------------------------------------------------------ reporte


def render_markdown(report: Mapping[str, Any]) -> str:
    meta = report["meta"]

    def f(v: Any, pct: bool = False) -> str:
        if v is None:
            return "—"
        if isinstance(v, float):
            return f"{v:.2f}" if not pct else f"{v:.0%}"
        return str(v)

    lines = [
        "# Eval del agente (D4)",
        "",
        (
            f"- Modelos local: `{meta['local']['model_small']}` → `{meta['local']['model_large']}`"
            f" · simulado={meta['local']['simulated']} · extra_body `{json.dumps(meta['local']['extra_body'])}`"
        ),
        f"- Índice `{meta['index_version']}` · dataset sha `{meta['dataset_sha']}` · particiones {', '.join(meta['splits'])}",
        f"- Corridas: {meta['runs']} · {meta['generated_at']}",
        "",
        (
            "Tasas promediadas por caso y luego por episodio, solo sobre corridas válidas. "
            "`pass` = causa esperada en primer lugar y no detección aceptable. "
            "`inválidas` = falla de infraestructura (red, HTTP, proveedor): no miden al modelo, se "
            "excluyen de las tasas y se repiten al retomar. `fallo esquema` = el modelo respondió "
            "pero no dio una salida válida; `bloqueadas` = la política de confidencialidad frenó la "
            "llamada. Esas dos sí cuentan como no-pass."
        ),
        "",
        "## Exactitud",
        "",
        "| variante | split | eps | casos | corridas | inválidas | fallo esquema | bloqueadas | pass@1 | pass^k (k) | RC top1 | RC top3 | ND ok | top1 recurrentes | top1 causa nueva |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in report["aggregates"]:
        lines.append(
            f"| {a['variant']} | {a['split']} | {a['episodes']} | {a['cases']} | {a['runs']} | {a['errors']} "
            f"| {a.get('structured_fails', 0)} | {a.get('policy_blocked', 0)} "
            f"| {f(a['pass@1'])} | {f(a['pass^k'])} ({a['k']}) | {f(a['rc_top1'])} | {f(a['rc_top3'])} "
            f"| {f(a['nd_ok'])} | {f(a['rc_top1_recurrent'])} | {f(a['rc_top1_new_cause'])} |"
        )
    lines += [
        "",
        "## Precedentes y proceso",
        "",
        "| variante | split | top1 cita precedente | top1 cita 8D ajeno | ídem en causa nueva | RC esperada descartada | escaló a grande |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in report["aggregates"]:
        lines.append(
            f"| {a['variant']} | {a['split']} | {f(a['top1_cites_precedent'])} | {f(a['top1_cites_foreign_8d'])} "
            f"| {f(a['top1_cites_foreign_8d_new_cause'])} | {f(a['expected_rc_discarded'])} | {f(a['escalated_to_large'])} |"
        )
    lines += [
        "",
        "## Abstención y salida",
        "",
        "| variante | split | se abstuvo | abstención indebida | abstención correcta | bajada por guardrail | con contradicciones | salida insegura |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for a in report["aggregates"]:
        lines.append(
            f"| {a['variant']} | {a['split']} | {f(a.get('abstained'))} | {f(a.get('false_abstention'))} "
            f"| {f(a.get('abstention_correct'))} | {f(a.get('estado_downgraded'))} "
            f"| {f(a.get('with_contradictions'))} | {a.get('unsafe_output_runs', 0)} |"
        )
    lines += [
        "",
        (
            "`abstención indebida`: se abstuvo en un caso que tiene causa esperada y no está "
            "etiquetado como de evidencia insuficiente. `abstención correcta` solo existe cuando el "
            "caso trae `evidencia_suficiente`. `salida insegura` debe ser 0: es un gate."
        ),
    ]
    lines += [
        "",
        "## Costo y latencia (por corrida)",
        "",
        (
            f"Concurrencia pedida {meta.get('concurrency_requested', '—')}, observada "
            f"{meta.get('concurrency_observed') or '—'} (máximo de corridas en curso a la vez). "
            "Con concurrencia > 1 el p95 incluye la cola del proveedor."
        ),
        "",
        "| variante | split | llamadas | costo estimado | costo reportado | tokens in | tokens out | razonamiento | p50 s | p95 s |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for a in report["aggregates"]:

        def usd(v: float | None) -> str:
            return "—" if v is None else f"${v:.4f}"

        def sec(v: float | None) -> str:
            return "—" if v is None else f"{v / 1000:.0f}"

        def num(v: float | None) -> str:
            return "—" if v is None else f"{v:,.0f}"

        def num1(v: float | None) -> str:
            return "—" if v is None else f"{v:.1f}"

        lines.append(
            f"| {a['variant']} | {a['split']} | {num1(a.get('llm_calls_mean'))} | {usd(a['cost_est_usd_mean'])} | {usd(a['cost_reported_usd_mean'])} "
            f"| {num(a['tokens_in_mean'])} | {num(a['tokens_out_mean'])} | {num(a['reasoning_tokens_mean'])} "
            f"| {sec(a['wall_ms_p50'])} | {sec(a['wall_ms_p95'])} |"
        )
    truncated = sum(
        a.get("truncated_calls", 0) for a in report["aggregates"] if a["split"] == "all"
    )
    if truncated:
        lines += [
            "",
            (
                f"> **Aviso:** {truncated} llamadas se cortaron por `max_tokens` (finish_reason=length). "
                "Esas salidas no son un error de esquema del modelo: falta presupuesto de tokens."
            ),
        ]
    # Concentradas = pocas casos acumulan las inválidas. Si todas las corridas de todos los casos
    # fallaron igual (p. ej. un 404 de configuración), no es concentración.
    concentrated: dict[str, int] = {}
    for a in report["aggregates"]:
        if a["split"] != "all":
            continue
        by_case = a.get("invalid_by_case") or {}
        if by_case and len(by_case) <= a["cases"] / 2:
            concentrated.update({c: n for c, n in by_case.items() if n > 1})
    if concentrated:
        lines += [
            "",
            (
                "> **Aviso:** inválidas concentradas en pocos casos. Una falla de infraestructura "
                "se reparte al azar; si se repite en el mismo caso, revisa si es del caso y no de la red."
            ),
        ]
        lines += [f"> - `{c}`: {n} inválidas" for c, n in sorted(concentrated.items())]
    multi = {
        m: p
        for a in report["aggregates"]
        if a["split"] == "all"
        for m, p in a["providers_by_model"].items()
        if len(p) > 1
    }
    if multi:
        lines += [
            "",
            (
                "> **Aviso:** más de un proveedor respondió para el mismo modelo. La varianza entre "
                "repeticiones mezcla modelo y proveedor; fija `provider.only` y `allow_fallbacks=false`."
            ),
        ]
        lines += [f"> - `{m}`: {', '.join(p)}" for m, p in multi.items()]
    bd = report.get("breakdown") or {}
    for variant, dims in bd.items():
        lines += [
            "",
            f"## Desglose `{variant}` (pass@1 · RC top1 · abstención · corridas)",
            "",
        ]
        for dim, values in dims.items():
            cells = [
                f"{v}: {f(x['pass@1'])} · {f(x['rc_top1'])} · {f(x['abstained'])} · {x['corridas']}"
                for v, x in values.items()
            ]
            lines.append(f"- **{dim}** — " + "; ".join(cells))
    configs = {
        c
        for a in report["aggregates"]
        if a["split"] == "all"
        for c in a.get("config_ids", [])
    }
    if configs:
        lines += ["", f"Configuraciones (`config_id`): {', '.join(sorted(configs))}"]
        exp = (report.get("meta") or {}).get("experiment") or {}
        if exp:
            lines.append(
                f"Experimento `{exp.get('experiment_id')}` · código `{exp.get('code_revision') or 'sin GIT_SHA'}`"
            )
    pr = report.get("paired")
    if pr and (pr["mejora"] or pr["empeora"] or pr["igual"]):
        lines += [
            "",
            f"## `{pr['b']}` frente a `{pr['a']}`, caso a caso (tasa de pass)",
            "",
            f"- Mejora: {', '.join(pr['mejora']) or '—'}",
            f"- Empeora: {', '.join(pr['empeora']) or '—'}",
            f"- Igual: {len(pr['igual'])} casos",
        ]
    fails = [
        r
        for r in report["runs"]
        if not r["score"]["pass"] or r["error"] or r["blocked"]
    ]
    if fails:
        lines += [
            "",
            "## Corridas que no pasan",
            "",
            "| caso | variante | rep | causas | ND | descartadas | 8D enlazados | nota |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in fails:
            s = r["score"]
            errs = sorted(set(r.get("llm_errors") or []))
            note = r["error"] or (
                "LLM: " + ", ".join(errs)
                if errs
                else "; ".join(f"{k}: {v[:160]}" for k, v in r["blocked"].items())
            )
            kind = classify_run(r)
            if kind != "ok":
                note = f"**{kind}** · {note}"
            lines.append(
                f"| {r['caso_id']} | {r['variant']} | {r['rep']} | {', '.join(c or '?' for c in s['codes']) or '—'} "
                f"| {s['nd'] or '—'} | {', '.join(c or '?' for c in s['discarded']) or '—'} "
                f"| {'; '.join(r['linked_8d']) or '—'} | {note} |"
            )
    lines.append("")
    return "\n".join(lines)


# ------------------------------------------------------------------ CLI


def _load_runs(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    latest: dict[tuple[str, str, int], dict[str, Any]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            # Al retomar, una corrida inválida se repite y la nueva línea reemplaza a la vieja.
            latest[(row["caso_id"], row["variant"], row["rep"])] = row
    return list(latest.values())


def experiment_manifest(
    args: argparse.Namespace, rows: Sequence[Mapping[str, Any]], dataset_sha: str
) -> dict[str, Any]:
    """Qué se corrió: dataset, partición, variantes, repeticiones y el manifiesto completo de
    cada configuración (de `analysis_run`), para poder decir si un cambio vino del modelo, del
    proveedor, del prompt o del índice."""
    import hashlib

    from app.agent.manifest import code_revision
    from app.core.db import get_engine

    configs: dict[str, Any] = {}
    ids = {
        r["config_id"]: r["run_id"]
        for r in rows
        if r.get("config_id") and r.get("run_id")
    }
    if ids:
        with get_engine().connect() as conn:
            for cid, run_id in ids.items():
                m = conn.execute(
                    text("SELECT manifest FROM analysis_run WHERE id = :id"),
                    {"id": run_id},
                ).scalar_one_or_none()
                configs[cid] = m
    key = json.dumps(
        [
            args.name,
            dataset_sha,
            sorted(ids),
            sorted(args.variants or []),
            args.repeats,
        ],
        sort_keys=True,
    )
    return {
        "experiment_id": hashlib.sha256(key.encode()).hexdigest()[:12],
        "name": args.name,
        "dataset_sha": dataset_sha,
        "splits": sorted({r["split"] for r in rows}),
        "variants": sorted({r["variant"] for r in rows}),
        "repeats": max((r["rep"] for r in rows), default=0),
        "code_revision": code_revision(),
        "configs": configs,
        "run_status": {
            "validas": sum(1 for r in rows if not is_invalid(r)),
            "invalidas": sum(1 for r in rows if is_invalid(r)),
        },
    }


def _settings_meta() -> dict[str, Any]:
    """Qué modelos y opciones se usaron. Nunca la API key."""
    from app.agent.llm.config import get_llm_settings

    s = get_llm_settings()

    def dest(d: Any) -> dict[str, Any] | None:
        if d is None:
            return None
        return {
            "base_url_host": d.base_url.host,
            "provider_label": d.provider_label,
            "model_small": d.model_small,
            "model_large": d.model_large,
            "simulated": d.simulated,
            "json_mode": d.json_mode,
            "extra_body": d.extra_body,
            "price_in_per_mtok": str(d.price_in_per_mtok),
            "price_out_per_mtok": str(d.price_out_per_mtok),
        }

    return {"local": dest(s.local), "api": dest(s.api)}


async def _run_all(
    args: argparse.Namespace, cases: list[dict[str, Any]], runs_path: Path
) -> None:
    from app.agent.runtime import build_deps, close_deps
    from app.core.db import get_engine

    previous = _load_runs(runs_path)
    done = {
        (r["caso_id"], r["variant"], r["rep"]) for r in previous if not is_invalid(r)
    }
    retry = sum(1 for r in previous if is_invalid(r))
    todo = [
        (c, v, rep)
        for rep in range(1, args.repeats + 1)
        for c in cases
        for v in args.variants
        if (c["caso_id"], v, rep) not in done
    ]
    if not todo:
        print(
            f"nada pendiente en {runs_path.name}: NO se llamó al modelo; el reporte se rehace "
            "con las corridas guardadas. Para una serie nueva usa otro --name.",
            file=sys.stderr,
        )
        return
    print(
        f"{len(todo)} corridas pendientes ({len(done)} válidas ya hechas"
        + (f", {retry} inválidas se repiten" if retry else "")
        + ")",
        file=sys.stderr,
    )
    if not args.no_preflight:
        await preflight()
    engine = get_engine()
    deps = build_deps(engine)
    width = max(1, args.concurrency)
    sem = asyncio.Semaphore(width)
    state = {"streak": 0, "finished": 0, "stop": False}
    total = len(todo)

    async def one(case: dict[str, Any], variant: str, rep: int) -> None:
        if state["stop"]:
            return
        async with sem:
            if state["stop"]:
                return
            row = await run_once(engine, deps, case, variant, rep)
        # Fuera del semáforo: todo esto corre en el mismo hilo del loop, sin carreras.
        state["finished"] += 1
        i = state["finished"]
        state["streak"] = state["streak"] + 1 if is_invalid(row) else 0
        if state["streak"] >= MAX_INVALID_STREAK:
            state["stop"] = True
        with runs_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
        s = row["score"]
        print(
            f"[{i}/{total}] {case['caso_id']} {variant} r{rep}: "
            f"{'PASA' if s['pass'] else 'falla'} · causas {s['codes']} · ND {s['nd']} · "
            f"${row['cost_est_usd']:.4f} · {row['wall_ms'] / 1000:.0f}s"
            + (f" · ERROR {row['error']}" if row["error"] else "")
            + (f" · LLM {sorted(set(row['llm_errors']))}" if row["llm_errors"] else ""),
            file=sys.stderr,
        )

    try:
        print(f"concurrencia {width}", file=sys.stderr)
        results = await asyncio.gather(
            *(one(case, variant, rep) for case, variant, rep in todo),
            return_exceptions=True,
        )
        errors = [r for r in results if isinstance(r, BaseException)]
        if errors:
            raise errors[0]
        if state["stop"]:
            raise SystemExit(
                f"{state['streak']} corridas seguidas sin respuesta del modelo: se detiene para no "
                "gastar el resto. Revisa LLM_* (modelo, proveedor, API key); al volver a "
                "correr, las inválidas se repiten."
            )
    finally:
        await close_deps(deps)


MAX_INVALID_STREAK = 3


async def preflight() -> None:
    """Una llamada mínima por modelo antes de abrir NCRs: valida modelo, proveedor y API key.

    Va directo al cliente (sin gateway ni auditoría) y no lleva datos del caso. Un error de
    configuración sale aquí en un segundo, con su estado HTTP, en vez de en 72 corridas.
    """
    from app.agent.llm import LLMError, LLMRequest, Message
    from app.agent.llm.config import get_llm_settings
    from app.agent.llm.factory import build_clients, close_clients

    settings = get_llm_settings()
    clients = build_clients(settings)
    try:
        for dest, client in clients.items():
            d = settings.destination(dest)
            for model in dict.fromkeys((d.model_small, d.model_large)):
                req = LLMRequest(
                    model=model,
                    messages=(Message(role="user", content="Responde solo: ok"),),
                    max_tokens=256,
                )
                try:
                    res = await client.complete(req)
                except LLMError as exc:
                    raise SystemExit(
                        f"preflight {dest.value}/{model}: {type(exc).__name__}: {exc}\n"
                        f"extra_body = {json.dumps(d.extra_body)}\n"
                        "Revisa el slug del modelo, el proveedor de `provider.only`/`order` "
                        "(debe servir ese modelo) y la API key."
                    ) from exc
                print(
                    f"preflight {dest.value}/{model}: ok · proveedor {res.provider or '?'} · "
                    f"{res.usage.input_tokens}→{res.usage.output_tokens} tok"
                    + (
                        f" (razonamiento {res.usage.reasoning_tokens})"
                        if res.usage.reasoning_tokens
                        else ""
                    ),
                    file=sys.stderr,
                )
    finally:
        await close_clients(clients)


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--evals", type=Path, default=DEFAULT_EVALS)
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--name",
        default="agente",
        help="prefijo de los archivos; mismo nombre = retoma",
    )
    ap.add_argument("--variants", default="base,enlace")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument(
        "--concurrency",
        type=int,
        default=3,
        help="corridas en paralelo (el pool de la base admite ~15 conexiones)",
    )
    ap.add_argument(
        "--casos",
        help="lista EV-xx separada por comas (por defecto, toda la partición)",
    )
    ap.add_argument(
        "--test", action="store_true", help="incluye la partición sellada (E9, E10)"
    )
    ap.add_argument(
        "--preflight-only",
        action="store_true",
        help="solo valida modelos y proveedor (una llamada mínima por modelo) y sale",
    )
    ap.add_argument(
        "--no-preflight",
        action="store_true",
        help="no valida modelos y proveedor antes de empezar",
    )
    ap.add_argument(
        "--report-only",
        action="store_true",
        help="no llama al modelo; rehace el reporte",
    )
    args = ap.parse_args(argv)

    if args.preflight_only:
        asyncio.run(preflight())
        return 0
    args.variants = [v for v in args.variants.split(",") if v]
    unknown = set(args.variants) - set(VARIANTS)
    if unknown:
        raise SystemExit(
            f"variantes desconocidas: {sorted(unknown)}; usa {sorted(VARIANTS)}"
        )
    if args.concurrency < 1:
        raise SystemExit("--concurrency debe ser >= 1")
    if args.repeats < 1:
        raise SystemExit("--repeats debe ser >= 1")

    wanted = DEV_EPISODES | (TEST_EPISODES if args.test else frozenset())
    all_cases, _, sha = load_cases(args.evals)
    cases = [c for c in all_cases if c["episodio"] in wanted]
    if args.casos:
        ids = {x.strip() for x in args.casos.split(",") if x.strip()}
        missing = ids - {c["caso_id"] for c in all_cases}
        if missing:
            raise SystemExit(f"casos desconocidos: {sorted(missing)}")
        sealed = {
            c["caso_id"] for c in all_cases if c["episodio"] in TEST_EPISODES
        } & ids
        if sealed and not args.test:
            raise SystemExit(
                f"{sorted(sealed)} son de la partición sellada: agrega --test a propósito"
            )
        cases = [c for c in all_cases if c["caso_id"] in ids]

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.out_dir / f"{args.name}{'-con-test' if args.test else ''}"
    runs_path = stem.with_suffix(".runs.jsonl")
    if not args.report_only:
        asyncio.run(_run_all(args, cases, runs_path))

    rows = _load_runs(runs_path)
    if not rows:
        raise SystemExit(f"no hay corridas en {runs_path}")
    from app.core.db import get_engine
    from app.retrieval.embedder import get_embedder
    from app.retrieval.service import RetrievalService

    with get_engine().connect() as conn:
        index_version = RetrievalService(conn, get_embedder()).index_version
    report = {
        "meta": {
            **_settings_meta(),
            "index_version": index_version,
            "dataset_sha": sha,
            "splits": sorted({r["split"] for r in rows}),
            "runs": len(rows),
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "concurrency_requested": args.concurrency,
            "concurrency_observed": observed_concurrency(rows),
            "experiment": experiment_manifest(args, rows, sha),
        },
        "aggregates": aggregate(rows),
        "breakdown": breakdown(rows),
        "paired": paired(rows),
        "runs": rows,
    }
    stem.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    md = render_markdown(report)
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    print(md)
    print(
        f"guardado en {stem}.json / .md (corridas en {runs_path.name})", file=sys.stderr
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
