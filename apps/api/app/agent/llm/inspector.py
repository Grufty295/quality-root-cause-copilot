"""Inspector de payloads salientes (detector de fugas).

Es la última barrera antes de una llamada al destino api: busca en el payload ya
redactado cualquier identificador confidencial del catálogo (nombres de clientes
confidenciales, números de parte, alias). Si encuentra uno, la llamada se bloquea.

No reemplaza al redactor: lo verifica. Si el redactor falla, esto lo detecta;
el eval de fugas usa esta misma función sobre cada payload enviado.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Protocol

from app.confidentiality.text import squash as _squash

from .schemas import Message


class PayloadInspector(Protocol):
    def findings(self, messages: Iterable[Message]) -> list[str]:
        """Devuelve los *tipos* de hallazgo (nunca el valor encontrado)."""
        ...


class CatalogInspector:
    """Busca términos prohibidos sin importar mayúsculas, acentos ni separadores.

    `AX-4471-B`, `ax 4471 b` y `AX4471B` coinciden. Los términos se agrupan por
    tipo de entidad para que el hallazgo diga qué tipo se filtró sin repetir el valor.
    """

    def __init__(
        self, forbidden: dict[str, Iterable[str]], *, min_length: int = 3
    ) -> None:
        self._patterns: list[tuple[str, re.Pattern[str]]] = []
        for entity_type, terms in forbidden.items():
            keys = sorted(
                {k for t in terms if len(k := _squash(t)) >= min_length},
                key=len,
                reverse=True,
            )
            if keys:
                alternation = "|".join(re.escape(k) for k in keys)
                self._patterns.append((entity_type, re.compile(alternation)))

    def findings(self, messages: Iterable[Message]) -> list[str]:
        haystack = _squash(" ".join(_texts(messages)))
        return [
            entity_type
            for entity_type, pattern in self._patterns
            if pattern.search(haystack)
        ]


def _texts(messages: Iterable[Message]) -> Iterable[str]:
    for m in messages:
        if m.content:
            yield m.content
        for tc in m.tool_calls:
            yield repr(tc.arguments)
