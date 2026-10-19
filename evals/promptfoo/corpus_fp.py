"""Párrafos legítimos del corpus sintético para medir falsos positivos del detector (se usa también en cuarentena de
fragmentos, así que un falso positivo aquí saca evidencia buena del prompt)."""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def parrafos() -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    for f in sorted((ROOT / "data" / "seed" / "corpus").rglob("*.md")):
        for para in re.split(r"\n\s*\n", f.read_text(encoding="utf-8")):
            if para.strip():
                out.append((f.name, para))
    with (ROOT / "data" / "seed" / "estructurados" / "ncr.csv").open(encoding="utf-8-sig", newline="") as fh:
        out += [("ncr.csv:" + r["ncr_id"], r["descripcion"]) for r in csv.DictReader(fh)]
    return out
