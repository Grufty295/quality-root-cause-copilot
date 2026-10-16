"""Catálogos cerrados de causas, leídos del corpus.

* RC-xx: filas del AMEF (causa de ocurrencia).
* ND-xx: categorías de no detección del SOP-QA-011.

La fuente es el corpus visible para el usuario, no una tabla aparte: el AMEF es
el único dueño de esos códigos (el SOP-QA-011 exige que el D4 referencie su fila).
Una tabla `cause_code` duplicaría el catálogo y divergiría en la primera revisión
del AMEF.

El chunker emite un fragmento por fila, con `section` igual al código.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from sqlalchemy import Connection, text

from app.confidentiality import ConfidentialityLevel

_CODE_SECTION = re.compile(r"^(RC|ND)-\d{2}$")


@dataclass(frozen=True)
class CatalogEntry:
    code: str
    description: str
    fragment_id: UUID
    level: ConfidentialityLevel
    contains_pii: bool


@dataclass(frozen=True)
class CauseCatalog:
    occurrence: dict[str, CatalogEntry]
    non_detection: dict[str, CatalogEntry]

    def get(self, code: str) -> CatalogEntry | None:
        return self.occurrence.get(code) or self.non_detection.get(code)

    def entries(self) -> list[CatalogEntry]:
        return [*self.occurrence.values(), *self.non_detection.values()]

    @property
    def complete(self) -> bool:
        return bool(self.occurrence) and bool(self.non_detection)


_SQL = text(
    """
SELECT f.id, f.section, f.content, f.level::text, f.contains_pii
FROM visible_fragments(CAST(:user_id AS uuid)) f
JOIN document d ON d.id = f.document_id
WHERE f.section ~ '^(RC|ND)-[0-9]{2}$'
  AND d.kind IN ('amef', 'sop')
  AND (CAST(:as_of AS date) IS NULL OR f.doc_date IS NULL OR f.doc_date <= CAST(:as_of AS date))
ORDER BY f.section, f.id
"""
)


def load_catalog(
    conn: Connection, user_id: UUID, as_of: date | None = None
) -> CauseCatalog:
    occurrence: dict[str, CatalogEntry] = {}
    non_detection: dict[str, CatalogEntry] = {}
    for fid, section, content, level, pii in conn.execute(
        _SQL, {"user_id": user_id, "as_of": as_of}
    ):
        if not _CODE_SECTION.match(section):
            continue
        entry = CatalogEntry(
            section, content, fid, ConfidentialityLevel(level), bool(pii)
        )
        target = occurrence if section.startswith("RC") else non_detection
        target.setdefault(
            section, entry
        )  # la primera revisión que aparezca; ver nota en el servicio
    return CauseCatalog(occurrence, non_detection)
