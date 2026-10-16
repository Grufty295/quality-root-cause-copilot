"""Modelos de dominio de la no conformidad. Sin SQLAlchemy ni FastAPI."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID


@dataclass(frozen=True)
class NcrDraft:
    """Lo que el usuario captura al abrir una no conformidad."""

    plant_id: str
    line_id: str
    shift: int
    description: str
    part_number: str | None = None
    customer_id: str | None = None


@dataclass(frozen=True)
class Ncr:
    id: UUID
    code: str
    plant_id: str
    line_id: str
    shift: int
    part_number: str | None
    customer_id: str | None
    description: str
    detected_level: str | None
    """None solo en NCR anteriores al clasificador; el router lo trata como confidencial."""
    contains_pii: bool | None
    classification_reasons: tuple[str, ...] | None
    """Tipos de hallazgo del clasificador, nunca valores."""
    status: str
    opened_by: UUID
    created_at: datetime


@dataclass(frozen=True)
class SectionView:
    """Ultima version de una disciplina. No incluye modelo, prompt ni traza: eso es de las trazas."""

    discipline: str
    version_no: int
    kind: str
    content: dict | None
    feedback: str | None
    author: str | None
    created_at: datetime


@dataclass(frozen=True)
class LatestVersion:
    version_no: int
    kind: str
    content: dict | None
