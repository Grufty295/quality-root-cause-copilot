"""Validación del contenido de una sección que un ingeniero edita a mano.

El borrador del agente sale del guardrail ya validado; una edición no pasa por él. Aquí se
exige lo mismo que el agente cumple: el esquema de `D2Content` / `D4Content`, códigos del
catálogo y fuentes citadas que existan en el índice de la propia sección.
"""

from __future__ import annotations

import json
from typing import Any, Final

from pydantic import BaseModel, ValidationError

from app.agent.catalog import CauseCatalog
from app.agent.schemas import (
    NON_DETECTION_CODE,
    OCCURRENCE_CODE,
    D2Content,
    D4Content,
    Hecho,
)
from app.core.errors import Invalid

MAX_CONTENT_BYTES: Final = 64 * 1024
_MAX_REPORTED_ERRORS: Final = 3


def validate_content(
    discipline: str, content: dict[str, Any], catalog: CauseCatalog | None = None
) -> None:
    if not content:
        raise Invalid("El contenido no puede estar vacio")
    if len(json.dumps(content).encode()) > MAX_CONTENT_BYTES:
        raise Invalid("El contenido es demasiado grande")
    if discipline == "D2":
        d2 = _parse(D2Content, content, discipline)
        cited = [
            f
            for hecho in (
                d2.que,
                d2.por_que,
                d2.donde,
                d2.cuando,
                d2.quien,
                d2.como,
                d2.cuanto,
            )
            for f in hecho.fuentes
        ]
        _check_sources(cited, d2.indice_fuentes)
    elif discipline == "D4":
        d4 = _parse(D4Content, content, discipline)
        _check_d4(d4, catalog)


def _parse[M: BaseModel](model: type[M], content: dict[str, Any], discipline: str) -> M:
    try:
        return model.model_validate(content)
    except ValidationError as exc:
        errors = exc.errors()
        shown = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
            for e in errors[:_MAX_REPORTED_ERRORS]
        )
        more = len(errors) - _MAX_REPORTED_ERRORS
        raise Invalid(
            f"{discipline} no cumple el formato: {shown}"
            + (f" (y {more} más)" if more > 0 else "")
        ) from exc


def _check_sources(cited: list[str], index: dict[str, Any]) -> None:
    missing = sorted({s for s in cited if s not in index})
    if missing:
        raise Invalid(
            f"Se citan fuentes que no están en el índice de la sección: {missing}"
        )


def _hechos(causa: Any) -> list[Hecho]:
    return [*causa.evidencia, *causa.evidencia_contradictoria]


def _check_d4(d4: D4Content, catalog: CauseCatalog | None) -> None:
    causes = d4.causas_ocurrencia
    if not causes:
        raise Invalid("D4 necesita al menos una causa de ocurrencia")
    codes = [c.codigo for c in causes]
    bad = [c for c in codes if not OCCURRENCE_CODE.match(c)]
    if bad:
        raise Invalid(f"Las causas de ocurrencia usan códigos RC-xx; recibido: {bad}")
    if len(set(codes)) != len(codes):
        raise Invalid("Las causas de ocurrencia deben tener códigos distintos")
    nd = d4.causa_no_deteccion
    if nd is not None and not NON_DETECTION_CODE.match(nd.codigo):
        raise Invalid(
            f"La causa de no detección usa un código ND-xx; recibido: {nd.codigo}"
        )
    if catalog is not None and catalog.complete:
        unknown = [c for c in codes if c not in catalog.occurrence]
        if nd is not None and nd.codigo not in catalog.non_detection:
            unknown.append(nd.codigo)
        if unknown:
            raise Invalid(f"Códigos que no están en el catálogo: {unknown}")
    cited = [
        f
        for c in [*causes, *([nd] if nd else [])]
        for h in _hechos(c)
        for f in h.fuentes
    ]
    _check_sources(cited, d4.indice_fuentes)
