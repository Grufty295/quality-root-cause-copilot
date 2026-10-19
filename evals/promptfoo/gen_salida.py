"""Casos de Promptfoo para los guardrails de SALIDA (`check_blame`, `check_closing`).

* regresion: inseguros de v1 y v2 (ya vistos; los patrones se escribieron mirándolos) y de culpa/cierre solamente.
* validacion: inseguros de v3 (fresco al medirse; umbral de no regresión).
* los textos seguros de v1, v2 y v3 van en core.yaml como tolerancia cero (gen_core.py).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import salida_v1  # noqa: E402
import salida_v2  # noqa: E402
import salida_v3  # noqa: E402

SCORED = ("culpa", "cierre")


def _t(desc, text, cat, caso):
    return {"description": desc, "vars": {"texto": text, "modo": "salida"},
            "assert": [{"type": "javascript", "value": f"JSON.parse(output).{cat}"}],
            "metadata": {"caso": caso, "categoria": cat}}


def generate_regresion(config=None):  # noqa: ARG001
    out = []
    for tag, mod in (("S1", salida_v1), ("S2", salida_v2)):
        out += [_t(f"{tag}-{i:02d} ({c}): se marca", t, c, f"{tag}-{i:02d}")
                for i, (c, t) in enumerate(mod.INSEGUROS, 1) if c in SCORED]
    return out


def generate_validacion(config=None):  # noqa: ARG001
    return [_t(f"S3-{i:02d} ({c}): se marca", t, c, f"S3-{i:02d}")
            for i, (c, t) in enumerate(salida_v3.INSEGUROS, 1) if c in SCORED]


def seguros():
    return [t for mod in (salida_v1, salida_v2, salida_v3) for t in mod.SEGUROS]
