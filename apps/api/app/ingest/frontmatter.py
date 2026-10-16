"""Lectura de los documentos del corpus: front matter y cuerpo.

El generador escribe un subconjunto mínimo de YAML (`clave: valor` y listas
`[a, b]`; ver data/generator/documentos.py::front_matter). Se parsea aquí sin
agregar PyYAML, y todo lo que no tenga esa forma es un error explícito.

Política de fallo seguro: si falta la confidencialidad o el valor no se reconoce,
el documento es `confidencial`; si falta `contiene_pii`, se asume que sí tiene.
El cuerpo nunca cambia el nivel: un documento que dice "CLASIFICACIÓN: PÚBLICO"
en su texto (caso adversarial ADV-06/07) conserva el nivel de su front matter.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.confidentiality import ConfidentialityLevel
from app.retrieval.models import DocumentKind

_KEY = re.compile(r"^([a-z_][a-z0-9_]*):\s?(.*)$")
_DOC_ID = r"^[A-Z0-9][A-Z0-9-]{2,40}$"

# Tipos del generador -> enum document_kind. Un tipo nuevo falla en voz alta.
KIND_BY_TIPO: dict[str, DocumentKind] = {
    "8D": DocumentKind.EIGHT_D,
    "NCR": DocumentKind.NCR,
    "AMEF": DocumentKind.AMEF,
    "SOP": DocumentKind.SOP,
    "INSTRUCCION_TRABAJO": DocumentKind.INSTRUCCION,
    "PLAN_CONTROL": DocumentKind.PLAN_CONTROL,
    "ESPECIFICACION": DocumentKind.ESPECIFICACION,
    "CSR": DocumentKind.REQUISITO_CLIENTE,
    "NORMA": DocumentKind.NORMA,
}


class FrontMatterError(ValueError):
    pass


class CorpusDocument(BaseModel):
    """Un documento del corpus ya validado. `body` es Markdown sin front matter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_key: str = Field(pattern=_DOC_ID)
    kind: DocumentKind
    tipo: str
    title: str = Field(min_length=3, max_length=300)
    doc_date: date
    lines: tuple[str, ...] = Field(min_length=1)
    customers: tuple[str, ...] = ()
    level: ConfidentialityLevel
    level_was_defaulted: bool
    contains_pii: bool
    extra: dict[str, str | list[str]] = Field(default_factory=dict)
    body: str = Field(min_length=1)

    @field_validator("lines")
    @classmethod
    def _line_ids(cls, v: tuple[str, ...]) -> tuple[str, ...]:
        if any(not re.fullmatch(r"[A-Z0-9]{1,10}", x) for x in v):
            raise ValueError(f"id de línea inválido en {v}")
        return tuple(dict.fromkeys(v))


def split_front_matter(text: str) -> tuple[dict[str, str | list[str]], str]:
    text = text.lstrip("﻿")
    if not text.startswith("---\n"):
        raise FrontMatterError("el documento no empieza con front matter (---)")
    end = text.find("\n---\n", 4)
    if end == -1:
        raise FrontMatterError("front matter sin cierre (---)")
    meta: dict[str, str | list[str]] = {}
    for n, line in enumerate(text[4:end].splitlines(), start=2):
        if not line.strip():
            continue
        m = _KEY.match(line)
        if not m:
            raise FrontMatterError(f"línea {n} del front matter no es 'clave: valor'")
        key, value = m.group(1), m.group(2).strip()
        if key in meta:
            raise FrontMatterError(f"clave repetida en el front matter: {key}")
        if value.startswith("[") and value.endswith("]"):
            meta[key] = [x.strip() for x in value[1:-1].split(",") if x.strip()]
        else:
            meta[key] = value
    return meta, text[end + 5 :]


def parse_document(text: str) -> CorpusDocument:
    meta, body = split_front_matter(text)
    data: dict[str, Any] = dict(meta)

    def take(key: str) -> Any:
        if key not in data:
            raise FrontMatterError(f"falta '{key}' en el front matter")
        return data.pop(key)

    tipo = str(take("tipo"))
    if tipo not in KIND_BY_TIPO:
        raise FrontMatterError(f"tipo de documento desconocido: {tipo!r}")

    raw_level = data.pop("confidencialidad", None)
    try:
        level = ConfidentialityLevel(str(raw_level)) if raw_level is not None else None
    except ValueError:
        level = None

    raw_pii = data.pop("contiene_pii", None)
    contains_pii = raw_pii != "false"  # solo un "false" explícito lo desactiva

    lines = take("lineas")
    customers = data.pop("clientes", [])
    if not isinstance(lines, list) or not isinstance(customers, list):
        raise FrontMatterError("'lineas' y 'clientes' deben ser listas [a, b]")

    try:
        return CorpusDocument(
            source_key=str(take("doc_id")),
            kind=KIND_BY_TIPO[tipo],
            tipo=tipo,
            title=str(take("titulo")),
            doc_date=date.fromisoformat(str(take("fecha"))),
            lines=tuple(lines),
            customers=tuple(customers),
            level=level or ConfidentialityLevel.CONFIDENCIAL,
            level_was_defaulted=level is None,
            contains_pii=contains_pii,
            extra=data,
            body=body,
        )
    except ValueError as exc:  # incluye ValidationError
        raise FrontMatterError(str(exc)) from exc
