"""Modelos de la recuperación.

`SearchQuery` valida la entrada (también la que arma una tool a partir de lo que
propone el LLM). `SearchHit` es lo que vuelve: incluye el nivel de cada
fragmento porque el router lo necesita antes de llamar al modelo.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.confidentiality import ConfidentialityLevel


class DocumentKind(StrEnum):
    """Mismo orden y valores que el enum `document_kind` (0001 + 0004)."""

    EIGHT_D = "8d"
    AMEF = "amef"
    SOP = "sop"
    INSTRUCCION = "instruccion"
    NORMA = "norma"
    NCR = "ncr"
    PLAN_CONTROL = "plan_control"
    ESPECIFICACION = "especificacion"
    REQUISITO_CLIENTE = "requisito_cliente"


SearchMode = Literal["hybrid", "text", "vector"]


class SearchQuery(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=8, ge=1, le=20)
    mode: SearchMode = "hybrid"
    """`text` y `vector` existen para el eval de Recall@5 (híbrida frente a solo vectorial)."""

    as_of: date | None = None
    """Excluye documentos con fecha posterior. Sin esto, un eval ve el futuro
    (p. ej. el 8D que ya resolvió el caso que se está evaluando)."""

    kinds: tuple[DocumentKind, ...] | None = Field(default=None, min_length=1)

    exclude_sources: tuple[str, ...] = ()
    """`source_key` de documentos que no deben salir. En un replay, el NCR que se está
    reproduciendo ya está en el corpus con la misma fecha: `as_of` no lo filtra y el agente
    lo citaría como "caso previo" de sí mismo."""

    @field_validator("text")
    @classmethod
    def _strip(cls, v: str) -> str:
        v = " ".join(v.split())
        if len(v) < 3:
            raise ValueError("la consulta necesita al menos 3 caracteres")
        return v


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    fragment_id: UUID
    document_id: UUID
    source_key: str
    kind: DocumentKind
    title: str
    section: str
    ordinal: int
    content: str
    level: ConfidentialityLevel
    contains_pii: bool
    doc_date: date | None
    plant_id: str | None
    line_id: str | None
    score: float
    lex_rank: int | None
    """Posición en la rama de texto completo (None = no apareció). Va a la traza."""
    sem_rank: int | None
    """Posición en la rama vectorial (None = no apareció)."""


class FragmentDraft(BaseModel):
    """Un fragmento listo para guardarse (sin embedding todavía)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    ordinal: int = Field(ge=0)
    section: str = Field(min_length=1, max_length=120)
    content: str = Field(min_length=1)
    codes: str
