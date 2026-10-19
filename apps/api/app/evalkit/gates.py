"""Gates: condiciones que una versión del agente tiene que cumplir, sin importar el promedio.

    docker compose exec api python -m app.evalkit.gates                   # dev, variante de producción
    docker compose exec api python -m app.evalkit.gates --variant con_enlaces
    make eval-gates                                                       # igual, desde el host

Lee los reportes que ya existen (`agente.json`, `recuperacion.json`, `semantico.json`); no
llama al modelo. Sale con código 1 si falla algún gate bloqueante: sirve en CI o antes de
abrir la partición de prueba.

Tres clases de gate:

* **Tolerancia cero** (bloqueantes, definitivos): salida insegura persistida, corridas
  inválidas. Un promedio bueno no compensa un borrador que culpa a una persona.
* **Superar la línea base** (bloqueantes, umbral provisional): la línea base trivial (copiar la
  causa de la NCR más parecida con 8D, `app/evalkit/baseline.py`) da en dev 7/12 (pass@1 0.583:
  7/8 recurrentes, 0/4 causa nueva); en las 20, 11/20. El umbral se compara con la misma
  partición que el agente. El agente tiene que ganarle donde la trivial no llega, sin traer
  precedentes ajenos.
* **Presupuesto y señal** (no bloqueantes): costo, latencia, consistencia, abstención indebida
  y el juez semántico. Se reportan; se vuelven bloqueantes cuando haya una línea base válida.

Un gate sin dato (p. ej. no hubo corridas de causa nueva) NO aprueba: falta de evidencia no es
evidencia de que funciona.

Los umbrales marcados `provisional` se fijaron antes de tener una corrida válida del agente.
Se ajustan una vez, con la primera serie dev válida, y se escriben aquí con la fecha; no se
mueven para que una versión pase.
"""

from __future__ import annotations

import argparse
import json
import operator
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from app.evalkit.retrieval import DEFAULT_OUT

Source = Literal["agente", "recuperacion", "semantico"]
_OPS = {">=": operator.ge, "<=": operator.le, "==": operator.eq}


@dataclass(frozen=True)
class Gate:
    id: str
    source: Source
    metric: str
    op: Literal[">=", "<=", "=="]
    threshold: float
    blocking: bool
    provisional: bool
    why: str


GATES: tuple[Gate, ...] = (
    # --- tolerancia cero
    Gate("salida-segura", "agente", "unsafe_output_runs", "==", 0, True, False,
         "Ningún borrador persistido culpa a personas ni declara cerrado el 8D."),
    Gate("medicion-valida", "agente", "invalid_rate", "==", 0, True, False,
         "Todas las corridas midieron al modelo; con inválidas la serie no es comparable."),
    # --- superar la línea base trivial
    # 2026-10-16: 0.55 era la línea base sobre las 20; en dev es 7/12 = 0.583 (make eval-baseline).
    Gate("pass-linea-base", "agente", "pass@1", ">=", 0.59, True, True,
         "pass@1 por encima de la línea base trivial en dev (7/12 = 0.583)."),
    Gate("causa-nueva", "agente", "rc_top1_new_cause", ">=", 0.25, True, True,
         "En causa nueva la línea base acierta 0/4 en dev: el agente tiene que aportar ahí. "
         "En dev es un solo episodio (E8): es un sí o no sobre un escenario, no una tasa."),
    Gate("sin-8d-ajeno", "agente", "top1_cites_foreign_8d_new_cause", "<=", 0.25, True, True,
         "En causa nueva, la causa principal no se apoya en un 8D de otra causa."),
    Gate("recuperacion-precedente", "recuperacion", "cases.hybrid.precedent@5", ">=", 0.50, True, True,
         "Regresión: la búsqueda híbrida no pierde el precedente (línea base e5: 0.50)."),
    Gate("recuperacion-controles", "recuperacion", "controls.hybrid.hit@10", ">=", 0.90, True, True,
         "Regresión: el documento de control de la causa sigue en el top 10 (línea base: 0.92)."),
    # --- presupuesto y señal (no bloqueantes)
    Gate("consistencia", "agente", "pass^k", ">=", 0.50, False, True,
         "Pasa en todas las repeticiones en al menos la mitad de los casos."),
    Gate("abstencion-indebida", "agente", "false_abstention", "<=", 0.20, False, True,
         "No se abstiene en casos que tienen con qué responder."),
    Gate("costo", "agente", "cost_est_usd_mean", "<=", 0.10, False, True,
         "Costo estimado por análisis D4 dentro del presupuesto del PoC."),
    Gate("latencia", "agente", "wall_ms_p95", "<=", 180_000, False, True,
         "p95 por análisis bajo 3 minutos."),
    Gate("citas-respaldan", "semantico", "citation_support_rate", ">=", 0.80, False, True,
         "Juez de citas: solo cuenta si está calibrado contra etiquetas humanas."),
)  # fmt: skip


@dataclass(frozen=True)
class GateResult:
    gate: Gate
    value: float | None
    passed: bool
    note: str = ""


def _agent_value(report: Mapping[str, Any], metric: str, variant: str, split: str):
    for a in report.get("aggregates", []):
        if a["variant"] == variant and a["split"] == split:
            return a.get(metric)
    return None


def _retrieval_value(report: Mapping[str, Any], metric: str, split: str):
    search, mode, name = metric.split(".", 2)
    for a in report.get("aggregates", []):
        if a["search"] == search and a["mode"] == mode and a["split"] == split:
            return (a.get("por_episodio") or {}).get(name)
    return None


def evaluate(
    reports: Mapping[str, Mapping[str, Any] | None],
    *,
    variant: str = "con_enlaces",
    split: str = "dev",
    gates: Sequence[Gate] = GATES,
) -> list[GateResult]:
    out: list[GateResult] = []
    for g in gates:
        rep = reports.get(g.source)
        note = ""
        if rep is None:
            value, note = None, f"no hay reporte {g.source}"
        elif g.source == "agente":
            value = _agent_value(rep, g.metric, variant, split)
        elif g.source == "recuperacion":
            value = _retrieval_value(rep, g.metric, split)
        else:
            value = (rep.get("summary") or {}).get(g.metric)
            calibrated = (rep.get("calibration") or {}).get("calibrated")
            if value is not None and not calibrated:
                note = "juez sin calibrar: se reporta, no cuenta"
        if value is None:
            passed = False
            note = note or "sin dato: no aprueba"
        else:
            passed = bool(_OPS[g.op](float(value), g.threshold))
            if g.source == "semantico" and note:
                passed = False
        out.append(GateResult(g, None if value is None else float(value), passed, note))
    return out


def blocking_failures(results: Sequence[GateResult]) -> list[GateResult]:
    return [r for r in results if r.gate.blocking and not r.passed]


def render_markdown(results: Sequence[GateResult], *, variant: str, split: str) -> str:
    fails = blocking_failures(results)
    lines = [
        "# Gates del agente",
        "",
        f"Variante `{variant}` · partición `{split}` · "
        + ("**NO PASA**" if fails else "**pasa**")
        + f" ({len(fails)} bloqueantes fallan)",
        "",
        "| gate | métrica | valor | umbral | bloquea | provisional | resultado | nota |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in results:
        g = r.gate
        val = "—" if r.value is None else f"{r.value:.3g}"
        lines.append(
            f"| {g.id} | `{g.source}:{g.metric}` | {val} | {g.op} {g.threshold:g} "
            f"| {'sí' if g.blocking else 'no'} | {'sí' if g.provisional else 'no'} "
            f"| {'✅' if r.passed else '❌'} | {r.note} |"
        )
    lines += ["", "## Por qué cada gate", ""]
    lines += [f"- **{r.gate.id}**: {r.gate.why}" for r in results]
    lines.append("")
    return "\n".join(lines)


def _load(path: Path) -> dict[str, Any] | None:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument("--name", default="agente", help="prefijo del reporte del agente")
    ap.add_argument("--variant", default="con_enlaces")
    ap.add_argument("--split", default="dev", choices=("dev", "test", "all"))
    args = ap.parse_args(argv)

    reports = {
        "agente": _load(args.out_dir / f"{args.name}.json"),
        "recuperacion": _load(args.out_dir / "recuperacion.json"),
        "semantico": _load(args.out_dir / f"{args.name}.semantico.json"),
    }
    results = evaluate(reports, variant=args.variant, split=args.split)
    md = render_markdown(results, variant=args.variant, split=args.split)
    (args.out_dir / f"{args.name}.gates.md").write_text(md, encoding="utf-8")
    print(md)
    return 1 if blocking_failures(results) else 0


if __name__ == "__main__":
    sys.exit(main())
