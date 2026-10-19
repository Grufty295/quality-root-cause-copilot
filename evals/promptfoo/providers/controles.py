"""Proveedor de Promptfoo: ejecuta los controles deterministas de la API sobre un texto.

No llama a ningún modelo ni a la red; no necesita base de datos. Devuelve JSON con lo que los controles
decidieron (nunca el valor encontrado: solo ids de patrón, nivel y tipos de PII), y las aserciones del config
comparan eso con lo esperado.

Qué NO mide: si un modelo real obedece una inyección que el detector no vio. Eso es la capa viva
(`docs/seguridad/promptfoo.md`, sección "Qué falta").
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

API = Path(__file__).resolve().parents[3] / "apps" / "api"
if str(API) not in sys.path:
    sys.path.insert(0, str(API))

from app.agent.guardrails.injection import detect_injection  # noqa: E402
from app.confidentiality import ConfidentialityLevel as L  # noqa: E402
from app.confidentiality.classifier import CatalogTerm, RuleClassifier  # noqa: E402
from app.confidentiality.pii import find_pii  # noqa: E402

# Catálogo mínimo (el de tests/test_confidentiality_classifier.py más la parte de ADV-09). En producción sale de la base.
CATALOG = (
    CatalogTerm("Norvane Motors", L.CONFIDENCIAL, "cliente"),
    CatalogTerm("Kestrel Modules", L.INTERNO, "cliente"),
    CatalogTerm("A7-DRH-2210-M", L.CONFIDENCIAL, "parte"),
    CatalogTerm("A7-DRH-2210-H", L.CONFIDENCIAL, "parte"),  # ADV-09 usa esta parte, escrita con espacios
    CatalogTerm("B3-FDH-0451", L.INTERNO, "parte"),
)
_CLASSIFIER = RuleClassifier(CATALOG)


def _corpus() -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from corpus_fp import parrafos

    ps = parrafos()
    alarmas = [f for f, t in ps if detect_injection(t)]
    return {"parrafos": len(ps), "alarmas": len(alarmas), "archivos_con_alarma": sorted(set(alarmas))[:10]}


def call_api(prompt: str, options: dict, context: dict) -> dict:  # noqa: ARG001
    modo = (context.get("vars") or {}).get("modo")
    if modo == "corpus":
        return {"output": json.dumps(_corpus(), ensure_ascii=False)}
    if modo == "salida":
        # Guardrails de SALIDA: lo que un borrador no debe decir (culpa a personas, cerrar el 8D).
        from app.agent.guardrails.output import check_blame, check_closing

        return {"output": json.dumps({"culpa": bool(check_blame([prompt])), "cierre": bool(check_closing([prompt]))})}
    cls = _CLASSIFIER.classify(prompt)
    out = {
        "injection": detect_injection(prompt),
        "nivel": cls.level.value,
        "pii": sorted({s.kind for s in find_pii(prompt)}),
    }
    return {"output": json.dumps(out, ensure_ascii=False)}
