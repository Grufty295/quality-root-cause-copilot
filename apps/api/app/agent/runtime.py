"""Construcción del runtime del agente a partir de la configuración y la base.

El redactor y el inspector se arman con el catálogo vigente al construirse: si el
catálogo de clientes o partes cambia, hay que reconstruir el runtime (reiniciar la
API). Es la misma limitación del inspector; se declara en docs/redactor.md.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Engine

from app.agent.graph import AgentDeps
from app.agent.llm import (
    CatalogInspector,
    ConfidentialityLevel,
    ModelGateway,
    SqlAuditSink,
    get_llm_settings,
)
from app.agent.llm.factory import build_clients, close_clients
from app.agent.observe import observer_from_env
from app.confidentiality.pseudonyms import SqlPseudonymStore
from app.confidentiality.redactor import RuleRedactor
from app.modules.ncr import repository as ncr_repo
from app.retrieval.embedder import get_embedder


def build_deps(engine: Engine) -> AgentDeps:
    settings = get_llm_settings()
    clients = build_clients(settings)
    with engine.connect() as conn:
        terms = ncr_repo.catalog_terms(conn)
    forbidden: dict[str, Iterable[str]] = {
        kind: [
            t.term
            for t in terms
            if t.kind == kind and t.level is ConfidentialityLevel.CONFIDENCIAL
        ]
        for kind in ("cliente", "parte")
    }
    gateway = ModelGateway(
        settings,
        clients,
        SqlAuditSink(engine.begin),
        CatalogInspector(forbidden),
        RuleRedactor(terms, SqlPseudonymStore(engine.begin)),
    )
    deps = AgentDeps(
        engine=engine,
        gateway=gateway,
        embedder=get_embedder(),
        # TRACE_EXPORTER=langfuse: una traza sin contenido por análisis (app/agent/observe.py).
        observer=observer_from_env(),
        # Variante `enlace` del eval. Serie dev-ds (mismo modelo, 3 repeticiones): pass@1 0.72 contra
        # 0.67 de `base`; recurrentes (E7) 0.00 → 0.42, pero causa nueva (E8) 1.00 → 0.75: a veces
        # ancla en un 8D que no aplica. Ver docs/evaluacion.md. Se revierte con False.
        expand_case_links=True,
    )
    deps.extra["clients"] = clients
    return deps


async def close_deps(deps: AgentDeps) -> None:
    if deps.observer is not None:
        deps.observer.close()
    await close_clients(deps.extra.get("clients", {}))
