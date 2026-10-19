"""Capa viva: arma un directorio de evals con las variantes que el detector NO atrapó.

Esas variantes llegan al modelo de verdad (pasan `guard_input`), así que son la prueba real de T3: ¿un modelo
obedece una inyección que el detector no vio, y lo atrapan los guardrails de salida y la aprobación humana?

    python evals/promptfoo/gen_live_dataset.py --out traces/promptfoo-live
    cd apps/api && python -m app.evalkit.agent --evals ../../traces/promptfoo-live --name var-live \
         --variants con_enlaces --repeats 1    # GASTA tokens (~US$1 con Qwen 27B)

Cada caso es una NCR legítima (EV-01..) con la variante añadida al final de la descripción; el esperado es el mismo
que el de la NCR limpia. Si el agente pasa igual que sin ataque, la inyección no lo movió; si no, la diferencia es
el hallazgo. Se compara contra el reporte limpio del mismo caso (dev-qwen27).
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from gen_variantes import VARIANTES  # noqa: E402
from heldout_v2 import ATAQUES as VALIDACION_V2  # noqa: E402

from app.agent.guardrails.injection import detect_injection  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--base-case", default="EV-02", help="NCR limpia sobre la que se añade cada variante")
    ap.add_argument("--incluir-validacion", action="store_true", help="añade los ataques de heldout_v2 que el detector no atrapa")
    a = ap.parse_args()

    cases = [json.loads(x) for x in (ROOT / "evals" / "casos_calidad.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    base = next(c for c in cases if c["caso_id"] == a.base_case)
    out = []
    pool = list(VARIANTES) + (list(VALIDACION_V2) if a.incluir_validacion else [])
    for i, (cat, txt) in enumerate(pool, 1):
        if detect_injection(txt):
            continue  # el detector la atrapa: nunca llegaría al modelo
        c = copy.deepcopy(base)
        c["caso_id"] = f"VARLIVE-{i:02d}"
        c["ncr"]["descripcion"] = f"{base['ncr']['descripcion']} {txt}"
        c["nota"] = f"Variante {cat} sobre {a.base_case}"
        out.append(c)

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "casos_calidad.jsonl").write_text("\n".join(json.dumps(c, ensure_ascii=False) for c in out) + "\n", encoding="utf-8")
    for extra in ("episodios_verdad.json",):
        src = ROOT / "evals" / extra
        if src.exists():
            (a.out / extra).write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    print(f"{len(out)} casos en {a.out}")


if __name__ == "__main__":
    main()
