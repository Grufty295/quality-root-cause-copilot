"""Manifiesto de una corrida: todo lo que hace falta para reproducirla o compararla.

Una versión del agente no es solo un prompt y un modelo. Si cambia el catálogo, el índice, el
proveedor que sirve el modelo, la cuantización o el tope de tokens, el resultado puede cambiar
aunque el prompt sea el mismo. El manifiesto junta todo eso y su `config_id` (hash del
contenido) dice si dos corridas son comparables.

Nunca lleva la API key ni texto de los casos. `extra_body` sí va completo: ahí están el
proveedor fijado (`provider.only/order`), las cuantizaciones permitidas y el esfuerzo de
razonamiento, que son justo lo que mueve la varianza.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from app.agent.catalog import CauseCatalog
from app.agent.prompts import PROMPT_VERSION

# Los defaults de `QualityTools.search_*` y de `ModelGateway.complete_structured`. Si cambian
# allá, el test de manifiesto falla para que cambien aquí.
RETRIEVAL_TOP_K = {"search_cases": 5, "search_controls": 6}
DECODING = {"temperature": 0.0, "max_tokens": 8192, "max_attempts": 3}


def _sha(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def catalog_sha(catalog: CauseCatalog | None) -> str | None:
    if catalog is None:
        return None
    return _sha(sorted((e.code, e.description) for e in catalog.entries()))


def code_revision() -> str | None:
    """`GIT_SHA` lo pone el build (`--build-arg GIT_SHA=$(git rev-parse --short HEAD)`)."""
    return os.environ.get("GIT_SHA") or None


def _destination(d: Any) -> dict[str, Any] | None:
    if d is None:
        return None
    provider = (d.extra_body or {}).get("provider") or {}
    return {
        "provider_label": d.provider_label,
        "base_url_host": d.base_url.host,
        "model_small": d.model_small,
        "model_large": d.model_large,
        "simulated": d.simulated,
        "json_mode": d.json_mode,
        "provider_routing": provider,
        "quantizations": provider.get("quantizations"),
        "reasoning": (d.extra_body or {}).get("reasoning"),
        "extra_body": d.extra_body,
        "price_in_per_mtok": str(d.price_in_per_mtok),
        "price_out_per_mtok": str(d.price_out_per_mtok),
    }


def build_manifest(
    deps: Any,
    *,
    index_version: str | None,
    catalog: CauseCatalog | None,
) -> dict[str, Any]:
    settings = deps.gateway.settings
    body: dict[str, Any] = {
        "prompt_version": PROMPT_VERSION,
        "index_version": index_version,
        "catalog_sha": catalog_sha(catalog),
        "agent": {
            "tool_budget": deps.tool_budget,
            "d4_max_rounds": deps.d4_max_rounds,
            "expand_case_links": deps.expand_case_links,
            "max_linked_8d": deps.max_linked_8d,
        },
        "retrieval": {**RETRIEVAL_TOP_K, "query": "graph.build_query"},
        "decoding": DECODING,
        "llm": {
            "local": _destination(settings.local),
            "api": _destination(settings.api),
        },
    }
    if getattr(deps, "controls_mode", "hybrid") != "hybrid":
        # Solo si no es el de producción: así el config_id de la configuración medida no cambia.
        body["agent"]["controls_mode"] = deps.controls_mode
    return {
        **body,
        # `config_id` no incluye la revisión de código: dos builds con la misma configuración
        # son comparables, y la revisión queda aparte para saber de qué build salió.
        "config_id": _sha(body),
        "code_revision": code_revision(),
    }
