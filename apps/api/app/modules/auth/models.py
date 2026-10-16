"""Modelos de dominio de autenticacion. Sin dependencias de SQLAlchemy ni FastAPI."""

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Scope:
    plant_id: str
    line_id: str | None  # None = toda la planta


@dataclass(frozen=True)
class CurrentUser:
    id: UUID
    username: str
    display_name: str
    role: str
    scopes: tuple[Scope, ...]
