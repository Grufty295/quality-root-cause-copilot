"""Libro de evidencia de un turno: qué ve el modelo y con qué id lo puede citar.

* `F1..Fn`: fragmentos recuperados (tienen `fragment_id`, se pueden citar en `citation`).
* `T1..Tn`: resultados de tools sobre datos (no son fragmentos; la tabla `citation`
  solo admite fragmentos, así que viven en el contenido de la sección).
* `NCR`: el reporte mismo.

Todo texto no confiable (fragmentos, resultados, la NCR) se escapa y se entrega
entre etiquetas; el prompt de sistema declara que lo de dentro son datos.
"""

from __future__ import annotations

import html
from dataclasses import dataclass, field
from typing import Literal
from uuid import UUID

from app.agent.schemas import FuenteRef
from app.confidentiality import ConfidentialityLevel
from app.confidentiality.text import squash

MAX_FRAGMENT_CHARS = 1400


@dataclass(frozen=True)
class Evidence:
    id: str
    kind: Literal["fragmento", "herramienta"]
    header: str
    body: str
    level: ConfidentialityLevel
    contains_pii: bool
    fragment_id: UUID | None = None
    document: str | None = None
    section: str | None = None
    tool: str | None = None
    params: dict[str, str] | None = None
    catalog_code: str | None = None
    """Si es la fila del catálogo (RC-xx / ND-xx), su código."""

    @property
    def searchable(self) -> str:
        return squash(f"{self.header} {self.body}")

    def render(self) -> str:
        return (
            f'<fuente id="{self.id}" nivel="{self.level.value}">\n'
            f"{html.escape(self.header, quote=False)}\n{html.escape(self.body, quote=False)}\n</fuente>"
        )

    def ref(self) -> FuenteRef:
        if self.kind == "fragmento":
            return FuenteRef(
                tipo="fragmento",
                fragment_id=str(self.fragment_id),
                documento=self.document,
                seccion=self.section,
                nivel=self.level.value,
            )
        return FuenteRef(
            tipo="herramienta",
            herramienta=self.tool,
            parametros=self.params,
            nivel=self.level.value,
        )


@dataclass
class EvidenceBook:
    _items: dict[str, Evidence] = field(default_factory=dict)
    _by_fragment: dict[UUID, str] = field(default_factory=dict)

    def add_fragment(
        self,
        *,
        fragment_id: UUID,
        document: str,
        section: str,
        title: str,
        content: str,
        level: ConfidentialityLevel,
        contains_pii: bool,
        catalog_code: str | None = None,
    ) -> Evidence:
        existing = self._by_fragment.get(fragment_id)
        if existing:
            return self._items[existing]
        eid = f"F{sum(e.kind == 'fragmento' for e in self._items.values()) + 1}"
        item = Evidence(
            id=eid,
            kind="fragmento",
            header=f"{document} · {title} · {section}",
            body=content[:MAX_FRAGMENT_CHARS],
            level=level,
            contains_pii=contains_pii,
            fragment_id=fragment_id,
            document=document,
            section=section,
            catalog_code=catalog_code,
        )
        self._items[eid] = item
        self._by_fragment[fragment_id] = eid
        return item

    def add_tool(
        self,
        *,
        tool: str,
        params: dict[str, str],
        body: str,
        level: ConfidentialityLevel,
        contains_pii: bool,
    ) -> Evidence:
        eid = f"T{sum(e.kind == 'herramienta' for e in self._items.values()) + 1}"
        item = Evidence(
            id=eid,
            kind="herramienta",
            header=f"resultado de {tool}",
            body=body,
            level=level,
            contains_pii=contains_pii,
            tool=tool,
            params=params,
        )
        self._items[eid] = item
        return item

    def get(self, evidence_id: str) -> Evidence | None:
        return self._items.get(evidence_id)

    def fragments(self) -> list[Evidence]:
        return [e for e in self._items.values() if e.kind == "fragmento"]

    def tools(self) -> list[Evidence]:
        return [e for e in self._items.values() if e.kind == "herramienta"]

    def all(self) -> list[Evidence]:
        return list(self._items.values())

    def render(self, *, only: set[str] | None = None) -> str:
        items = [e for e in self._items.values() if only is None or e.id in only]
        return "\n".join(e.render() for e in items) if items else "(sin fuentes)"

    def index(self, used: set[str]) -> dict[str, FuenteRef]:
        """Índice de las fuentes realmente citadas, para guardarlo con la sección."""
        out: dict[str, FuenteRef] = {}
        for sid in sorted(used):
            if sid == "NCR":
                out[sid] = FuenteRef(tipo="reporte")
            elif (item := self._items.get(sid)) is not None:
                out[sid] = item.ref()
        return out
