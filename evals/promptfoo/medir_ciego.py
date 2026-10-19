"""Mide el detector con `heldout_usuario.py` e imprime la tasa (y los falsos positivos), sin listar los casos fallidos
salvo con --detalle, para no contaminar la validación."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1] / "apps" / "api"))

from app.agent.guardrails.injection import detect_injection  # noqa: E402
from heldout_usuario import ATAQUES, NEGATIVOS  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--detalle", action="store_true")
    a = ap.parse_args()
    if not ATAQUES:
        raise SystemExit("heldout_usuario.py está vacío: escribe los ataques primero.")
    miss = [(c, t) for c, t in ATAQUES if not detect_injection(t)]
    fp = [t for t in NEGATIVOS if detect_injection(t)]
    n = len(ATAQUES)
    print(f"Detectados: {n - len(miss)}/{n} ({(n - len(miss)) / n:.0%})  |  falsos positivos: {len(fp)}/{len(NEGATIVOS)}")
    if a.detalle:
        for c, t in miss:
            print("  NO DETECTADO", c, t[:100])
        for t in fp:
            print("  FALSO POSITIVO", t[:100])


if __name__ == "__main__":
    main()
