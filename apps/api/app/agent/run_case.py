"""Corre el agente sobre un NCR del dataset, con el corte de fecha del propio NCR.

    docker compose exec api python -m app.agent.run_case NCR-2026-0079
    python -m app.agent.run_case NCR-2026-0078 --line L1 --out caso.json

Crea el NCR en la base a partir de `ncr.csv` y llama al agente con `as_of` igual a la
fecha del NCR: las tools y la recuperación no ven nada posterior. La API no expone
`as_of` a propósito, por eso esta prueba se hace aquí y no desde la interfaz.

Del CSV solo se usan el reporte (línea, turno, parte, descripción). La causa preliminar y
el 8D de la planta NO se le dan al agente; se imprimen al final, aparte, para comparar a mano.
Usa los modelos configurados en LLM_* y, con ellos, gasta dinero y manda datos a donde
diga el router: revisa `.env` antes. Los datos del dataset son ficticios.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any

from sqlalchemy import text

from app.agent.runtime import build_deps, close_deps
from app.agent.service import AnalysisService
from app.core.db import get_engine
from app.modules.auth import repository as auth_repo
from app.modules.ncr.models import NcrDraft
from app.modules.ncr.service import NcrService

PLANT = "JRZ1"
DEFAULT_DATA = Path(
    "/workspace/data/seed/estructurados"
)  # igual que el seed, dentro del contenedor
# Montado desde ./traces del repo: lo que se guarde aquí aparece en el host.
TRACES_DIR = Path("/workspace/traces")
_SHIFTS = {"T1": 1, "T2": 2, "T3": 3}


def load_case(data: Path, ncr_id: str) -> dict[str, str]:
    with (data / "ncr.csv").open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            if row["ncr_id"] == ncr_id:
                return row
    raise SystemExit(f"{ncr_id} no está en {data / 'ncr.csv'}")


def draft_from(row: dict[str, str], line: str | None) -> NcrDraft:
    lines = [part.strip() for part in row["linea"].split(",")]
    chosen = line or lines[0]
    if chosen not in lines:
        raise SystemExit(f"el NCR es de {row['linea']}, no de {chosen}")
    # Un NCR sin turno (reclamo de cliente) entra como turno 1: el turno no es el dato.
    return NcrDraft(
        plant_id=PLANT,
        line_id=chosen,
        shift=_SHIFTS.get(row["turno"], 1),
        description=row["descripcion"],
        part_number=row["numero_parte"] or None,
    )


async def run(args: argparse.Namespace) -> dict[str, Any]:
    row = load_case(args.data, args.ncr_id)
    as_of = date.fromisoformat(args.as_of or row["fecha"])
    engine = get_engine()
    with engine.begin() as conn:
        uid = auth_repo.find_active_user_id(conn, args.user)
        user = auth_repo.get_user(conn, uid) if uid else None
        if user is None:
            raise SystemExit(f"el usuario {args.user!r} no existe (¿corriste el seed?)")
        ncr = NcrService(conn).open(user, draft_from(row, args.line))
        # Replay: el reporte "se abre" el día del caso, no el día en que corre la prueba.
        # Sin esto el prompt dice fecha_reporte = hoy, semanas después del corte.
        conn.execute(
            text("UPDATE ncr SET created_at = :ts WHERE id = :id"),
            {"ts": datetime.combine(as_of, time(12), UTC), "id": ncr.id},
        )
    print(
        f"{ncr.code} creado: línea {ncr.line_id}, parte {ncr.part_number}, "
        f"nivel {ncr.detected_level}, corte {as_of}",
        file=sys.stderr,
    )

    deps = build_deps(engine)
    try:
        disciplines = tuple(args.disciplines.split(",")) if args.disciplines else None
        result = await AnalysisService(deps).analyze(
            user,
            ncr.id,
            disciplines=disciplines,
            as_of=as_of,
            # El NCR original está en el corpus con la misma fecha del corte: sin esto el
            # agente lo recupera y lo cita como precedente de sí mismo.
            exclude_sources=(args.ncr_id,),
        )
    finally:
        await close_deps(deps)

    with engine.connect() as conn:
        audit = (
            conn.execute(
                text(
                    "SELECT stage, destination, provider, model, detected_level, redaction_applied, pseudonymized, "
                    "tokens_in, tokens_out, cost_usd, latency_ms FROM audit_log WHERE ncr_id = :n ORDER BY id"
                ),
                {"n": ncr.id},
            )
            .mappings()
            .all()
        )
    return {
        "ncr": {
            "code": ncr.code,
            "ncr_id_csv": args.ncr_id,
            "as_of": as_of.isoformat(),
        },
        "sections": result.sections,
        "blocked": result.blocked,
        "skipped": result.skipped,
        "events": result.events,
        "calls": [vars(c) for c in result.calls],
        "audit": [{k: str(v) for k, v in r.items()} for r in audit],
        "referencia_planta": {
            "causa_preliminar": row["causa_preliminar"],
            "ocho_d": row["ocho_d"],
            "estado": row["estado"],
        },
    }


def resolve_out(path: Path, base: Path = TRACES_DIR) -> Path:
    """Una ruta relativa va a `traces/` (visible en el host). Se valida antes de gastar tokens.

    En Git Bash de Windows una ruta absoluta como /tmp/x.json se convierte en C:/... antes
    de llegar al contenedor; la relativa no se toca.
    """
    resolved = path if path.is_absolute() else base / path
    if not resolved.parent.is_dir():
        raise SystemExit(
            f"--out: no existe la carpeta {resolved.parent} dentro del contenedor. "
            "Usa un nombre relativo (--out caso.json → traces/caso.json en tu repo)."
        )
    return resolved


def print_report(out: dict[str, Any]) -> None:
    print(
        f"\n=== {out['ncr']['code']} ({out['ncr']['ncr_id_csv']}) · corte {out['ncr']['as_of']} ==="
    )
    for disc, section in out["sections"].items():
        print(
            f"\n--- {disc} · modelo {section.get('model')} · versión {section.get('version_no')} ---"
        )
        print(json.dumps(section.get("content"), ensure_ascii=False, indent=2))
    for label in ("blocked", "skipped"):
        for disc, why in out[label].items():
            print(f"\n[{label.upper()} {disc}] {why}")
    if out["events"]:
        print("\n--- eventos del grafo ---")
        for e in out["events"]:
            print(" ", e)
    print("\n--- llamadas al modelo (auditoría) ---")
    total = 0.0
    for r in out["audit"]:
        total += float(r["cost_usd"] or 0)
        print(
            f"  {r['stage']:<4} → {r['destination']:<5} {r['provider']}/{r['model']} · nivel {r['detected_level']}"
            f" · redactado={r['redaction_applied']} seudonimizado={r['pseudonymized']}"
            f" · {r['tokens_in']}→{r['tokens_out']} tok · {r['latency_ms']} ms"
        )
    print(f"  costo estimado total: ${total:.4f}")
    ref = out["referencia_planta"]
    print(
        f"\n--- lo que dijo la planta (NO se le dio al agente) ---\n  causa preliminar: {ref['causa_preliminar']}\n  8D: {ref['ocho_d'] or '—'} · estado: {ref['estado']}"
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("ncr_id", help="p. ej. NCR-2026-0079 (de ncr.csv)")
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--user", default="u-ingcal-1", help="usuario ingeniero del seed")
    ap.add_argument("--line", help="línea, si el NCR trae varias")
    ap.add_argument("--as-of", help="corte AAAA-MM-DD (por defecto, la fecha del NCR)")
    ap.add_argument("--disciplines", help="D2, D4 o D2,D4")
    ap.add_argument(
        "--out", type=Path, help="JSON con el resultado; relativo = dentro de traces/"
    )
    args = ap.parse_args()
    if args.out:
        args.out = resolve_out(args.out)
    out = asyncio.run(run(args))
    print_report(out)
    if args.out:
        args.out.write_text(
            json.dumps(out, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
        )
        print(f"\nguardado en {args.out}", file=sys.stderr)
    return 1 if out["blocked"] and not out["sections"] else 0


if __name__ == "__main__":
    sys.exit(main())
