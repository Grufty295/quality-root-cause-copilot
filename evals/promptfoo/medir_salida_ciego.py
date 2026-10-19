"""Mide los guardrails de salida con `salida_usuario.py` e imprime solo las tasas (--detalle lista los fallos)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "apps" / "api"))

from app.agent.guardrails.output import check_blame, check_closing  # noqa: E402
from salida_usuario import INSEGUROS, SEGUROS  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detalle", action="store_true")
    a = ap.parse_args()
    if not INSEGUROS:
        raise SystemExit("salida_usuario.py está vacío: escribe los casos primero.")
    flag = lambda t: bool(check_blame([t]) or check_closing([t]))  # noqa: E731
    miss = [(c, t) for c, t in INSEGUROS if not flag(t)]
    fp = [t for t in SEGUROS if flag(t)]
    n = len(INSEGUROS)
    print(f"Marcados: {n - len(miss)}/{n} ({(n - len(miss)) / n:.0%})  |  falsos positivos: {len(fp)}/{len(SEGUROS)}")
    if a.detalle:
        for c, t in miss:
            print("  NO MARCADO", c, t[:100])
        for t in fp:
            print("  FALSO POSITIVO", t[:100])


if __name__ == "__main__":
    main()
