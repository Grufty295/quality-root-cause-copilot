"""Almacén de seudónimos por NCR (`pseudonym_map`).

El mapa guarda valores en claro: nunca se manda a un modelo, a las trazas ni al
audit log. Un mismo valor recibe siempre el mismo marcador dentro de una NCR
(`[PERSONA_1]`), para que el modelo pueda razonar sobre "la misma persona".

Retención: la tabla documenta "NCR abierta + 90 días". Aún no existe el proceso
que purga; `expires_at` se fija (y se renueva al reutilizar) a 90 días, y las
lecturas ignoran lo vencido.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from sqlalchemy import Connection, text

RETENTION_DAYS = 90


@dataclass(frozen=True)
class PseudonymRow:
    entity_type: str
    real_value: str
    placeholder: str

    def __repr__(
        self,
    ) -> str:  # nunca imprimir el valor en claro en logs o fallos de prueba
        return f"PseudonymRow({self.entity_type}, {self.placeholder})"


class PseudonymStore(Protocol):
    def mapping(self, ncr_id: UUID) -> list[PseudonymRow]: ...

    def assign(
        self, ncr_id: UUID, items: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        """`items`: (tipo, valor). Idempotente: devuelve el marcador existente o crea uno."""
        ...

    def resolve(
        self, ncr_id: UUID, placeholders: Collection[str]
    ) -> dict[str, str]: ...


def make_placeholder(entity_type: str, n: int) -> str:
    return f"[{entity_type.upper()}_{n}]"


class InMemoryPseudonymStore:
    """Para pruebas y para ejecutar el redactor sin base."""

    def __init__(self) -> None:
        self._rows: dict[UUID, list[PseudonymRow]] = {}

    def mapping(self, ncr_id: UUID) -> list[PseudonymRow]:
        return list(self._rows.get(ncr_id, ()))

    def assign(
        self, ncr_id: UUID, items: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        rows = self._rows.setdefault(ncr_id, [])
        out: dict[tuple[str, str], str] = {}
        for entity_type, value in items:
            existing = next(
                (
                    r
                    for r in rows
                    if r.entity_type == entity_type and r.real_value == value
                ),
                None,
            )
            if existing is None:
                n = sum(r.entity_type == entity_type for r in rows) + 1
                existing = PseudonymRow(
                    entity_type, value, make_placeholder(entity_type, n)
                )
                rows.append(existing)
            out[(entity_type, value)] = existing.placeholder
        return out

    def resolve(self, ncr_id: UUID, placeholders: Collection[str]) -> dict[str, str]:
        wanted = set(placeholders)
        return {
            r.placeholder: r.real_value
            for r in self._rows.get(ncr_id, ())
            if r.placeholder in wanted
        }


ConnectionFactory = Callable[[], AbstractContextManager[Connection]]

_ASSIGN = text(
    "INSERT INTO pseudonym_map (ncr_id, placeholder, real_value, entity_type, expires_at) "
    "VALUES (:ncr, '[' || upper(:etype) || '_' || ("
    "  SELECT coalesce(max(substring(placeholder from '_(\\d+)\\]$')::int), 0) + 1 "
    "  FROM pseudonym_map WHERE ncr_id = :ncr AND entity_type = :etype) || ']', :real, :etype, "
    f"  now() + interval '{RETENTION_DAYS} days') "
    "ON CONFLICT (ncr_id, entity_type, real_value) "
    "DO UPDATE SET expires_at = EXCLUDED.expires_at "
    "RETURNING placeholder"
)

_LIVE = "(expires_at IS NULL OR expires_at > now())"


class SqlPseudonymStore:
    def __init__(self, begin: ConnectionFactory) -> None:
        """`begin`: abre una transacción nueva y la confirma al salir (p. ej. `engine.begin`)."""
        self._begin = begin

    def mapping(self, ncr_id: UUID) -> list[PseudonymRow]:
        with self._begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT entity_type, real_value, placeholder FROM pseudonym_map "
                    f"WHERE ncr_id = :ncr AND {_LIVE}"
                ),
                {"ncr": ncr_id},
            ).all()
        return [PseudonymRow(*r) for r in rows]

    def assign(
        self, ncr_id: UUID, items: Sequence[tuple[str, str]]
    ) -> dict[tuple[str, str], str]:
        if not items:
            return {}
        out: dict[tuple[str, str], str] = {}
        with self._begin() as conn:
            # Serializa la numeración por NCR: dos turnos concurrentes no repiten [PERSONA_n].
            conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:k, 0))"),
                {"k": f"pseudonym:{ncr_id}"},
            )
            for entity_type, value in items:
                out[(entity_type, value)] = conn.execute(
                    _ASSIGN, {"ncr": ncr_id, "etype": entity_type, "real": value}
                ).scalar_one()
        return out

    def resolve(self, ncr_id: UUID, placeholders: Collection[str]) -> dict[str, str]:
        if not placeholders:
            return {}
        with self._begin() as conn:
            rows = conn.execute(
                text(
                    "SELECT placeholder, real_value FROM pseudonym_map "
                    f"WHERE ncr_id = :ncr AND placeholder = ANY(:ph) AND {_LIVE}"
                ),
                {"ncr": ncr_id, "ph": list(placeholders)},
            ).all()
        return {ph: real for ph, real in rows}
