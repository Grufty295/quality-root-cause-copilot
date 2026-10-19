"""Clasificador de confidencialidad y PII del texto de una no conformidad.

Reglas deterministas, sin modelo. El PRD agrega "un clasificador ligero para el
texto libre"; en el MVP no existe: lo que las reglas no reconocen se trata con el
mismo criterio de fallo seguro que usa el resto del sistema.

Decide dos ejes independientes (PRD, "Dos ejes independientes"):

* nivel: el más alto que dé cualquier regla;
* PII: si el texto trae nombres de personas, números de nómina, correos o teléfonos.

Reglas de nivel:

1. Campos estructurados: el cliente o la parte que el usuario eligió en el
   formulario dan su nivel (un cliente confidencial lo es también para sus partes).
2. Menciones en el texto de clientes o partes del catálogo, sin importar
   mayúsculas, acentos ni separadores (`A7-DRH-2210-M` = `a7 drh 2210 m`).
3. Una cadena con la forma de un número de parte de cliente que NO está en el
   catálogo es confidencial: no sabemos de quién es.
4. Marcadores de material del cliente ("reclamo del cliente", "CSR", ...).
5. Sin ningún hallazgo: interno. Nunca público. Una NCR es un dato operativo de
   la planta; "público" es para normas y guías genéricas, no para casos.

`reasons` lista *tipos* de hallazgo, nunca el valor encontrado, así que se puede
guardar y mostrar en la traza sin filtrar lo que se detectó.

Limitaciones que se declaran, no se esconden:

* PII es heurística (patrón de "rol + nombre propio", etiqueta de contacto, nómina, correo,
  teléfono). Puede dejar pasar un nombre sin rol ni etiqueta delante. Presidio queda como diseño (PRD, "MVP").
* Los marcadores y el patrón de número de parte son del dataset sintético; una
  planta real los configura.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.confidentiality.levels import ConfidentialityLevel
from app.confidentiality.pii import KINDS, find_pii
from app.confidentiality.text import fold, squash

Level = ConfidentialityLevel

# Número de parte de cliente del dataset: B3-FDH-0451, A7-DRH-2210-M.
PART_SHAPE = re.compile(
    r"(?<![\w-])[A-Za-z]\d-[A-Za-z]{3}-\d{4}(?:-[A-Za-z]{1,2})?(?![\w-])"
)

# Sobre texto ya normalizado con `fold` (minúsculas, sin acentos).
_MARKERS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "reclamo_cliente",
        re.compile(
            r"\b(?:reclamos?|quejas?|reclamaciones)\s+(?:del?\s+)?(?:el\s+)?cliente\b"
        ),
    ),
    (
        "especificacion_cliente",
        re.compile(r"\bespecificaci(?:on|ones)\s+(?:del?\s+)?(?:el\s+)?cliente\b"),
    ),
    (
        "requisito_cliente",
        re.compile(
            r"\brequisitos?\s+(?:especificos?\s+)?(?:del?\s+)?(?:el\s+)?cliente\b"
        ),
    ),
    ("plano_cliente", re.compile(r"\bplanos?\s+(?:del?\s+)?(?:el\s+)?cliente\b")),
    ("csr", re.compile(r"\bcsr\b")),
    # Un programa del cliente se nombra con una palabra clave que ningún catálogo trae ("programa Halcón del OEM").
    ("programa_cliente", re.compile(r"\bprograma\s+\w+\s+del\s+(?:oem|cliente)\b")),
    ("oem", re.compile(r"\boem\b")),
)

MIN_TERM_LENGTH = 3


@dataclass(frozen=True)
class CatalogTerm:
    """Un nombre de cliente o un número de parte del catálogo y su nivel."""

    term: str
    level: ConfidentialityLevel
    kind: Literal["cliente", "parte"]


class Classification(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    level: ConfidentialityLevel
    contains_pii: bool
    reasons: tuple[str, ...]
    """Tipos de hallazgo, p. ej. `cliente:confidencial`, `parte_desconocida`, `pii:persona`."""


class RuleClassifier:
    def __init__(
        self, terms: Iterable[CatalogTerm], *, min_term_length: int = MIN_TERM_LENGTH
    ) -> None:
        self._terms: list[tuple[str, CatalogTerm]] = []
        for t in terms:
            key = squash(t.term)
            if len(key) >= min_term_length:
                self._terms.append((key, t))
        # Más largo primero: una coincidencia larga no queda tapada por una corta.
        self._terms.sort(key=lambda kt: len(kt[0]), reverse=True)
        self._known_parts = {key for key, t in self._terms if t.kind == "parte"}

    def classify(
        self,
        text: str,
        *,
        structured_levels: Iterable[ConfidentialityLevel | None] = (),
    ) -> Classification:
        """`structured_levels`: niveles de lo que el usuario eligió en el formulario (cliente, parte).

        Un `None` ahí significa un dato estructurado sin nivel conocido: confidencial.
        """
        levels: list[ConfidentialityLevel] = []
        reasons: list[str] = []

        for lvl in structured_levels:
            effective = lvl if lvl is not None else Level.CONFIDENCIAL
            levels.append(effective)
            reasons.append(f"campo:{effective.value}")

        squashed = squash(text)
        seen: set[tuple[str, str]] = set()
        for key, term in self._terms:
            if key in squashed and (term.kind, term.level.value) not in seen:
                seen.add((term.kind, term.level.value))
                levels.append(term.level)
                reasons.append(f"{term.kind}:{term.level.value}")

        for match in PART_SHAPE.finditer(text):
            if squash(match.group(0)) not in self._known_parts:
                levels.append(Level.CONFIDENCIAL)
                reasons.append("parte_desconocida")
                break

        folded = fold(text)
        for name, pattern in _MARKERS:
            if pattern.search(folded):
                levels.append(Level.CONFIDENCIAL)
                reasons.append(f"marcador:{name}")

        pii = self._pii_reasons(text)
        reasons.extend(pii)

        if not levels:
            levels.append(Level.INTERNO)
            reasons.append("sin_hallazgos")

        return Classification(
            level=Level.highest(levels),
            contains_pii=bool(pii),
            reasons=tuple(dict.fromkeys(reasons)),
        )

    @staticmethod
    def _pii_reasons(text: str) -> list[str]:
        kinds = {span.kind for span in find_pii(text)}
        return [f"pii:{kind}" for kind in KINDS if kind in kinds]
