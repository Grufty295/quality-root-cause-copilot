"""Redactor y seudonimizador (RF-04).

Reemplaza, antes de que un texto salga hacia el destino api, lo que no debe salir:

* clientes y números de parte del catálogo (de nivel interno o confidencial);
* números de parte con forma de catálogo que no están en él;
* PII: nombres de personas, números de nómina, correos y teléfonos.

Cada valor se cambia por un marcador estable dentro de la NCR (`[CLIENTE_1]`),
guardado en `pseudonym_map`. Al volver la respuesta del modelo, `restore` deja
los valores reales para quien tiene la NCR a la vista.

Lo que NO hace, y por qué importa:

* No decide el destino: eso es del router. Este módulo solo se usa si el destino es api.
* No es la última barrera: el inspector del gateway verifica el payload ya
  redactado y bloquea la llamada si encuentra algo del catálogo confidencial.
* Falla cerrado: si el almacén de seudónimos no responde, se lanza la excepción
  y nada sale. No hay modo degradado silencioso.
* La PII es heurística (ver `pii.py`). Un nombre sin rol delante, la primera vez
  que aparece en una NCR, no se detecta.

Los hallazgos se reportan como conteos por tipo; el valor detectado nunca sale de
aquí salvo hacia `pseudonym_map`.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from app.confidentiality.classifier import PART_SHAPE, CatalogTerm
from app.confidentiality.levels import ConfidentialityLevel
from app.confidentiality.pii import find_pii
from app.confidentiality.pseudonyms import PseudonymStore
from app.confidentiality.text import squash, squash_with_map

MIN_TERM_LENGTH = 3
MAX_PASSES = 3
_LEARNED = frozenset({"persona", "nomina", "correo", "telefono"})
_PLACEHOLDER = re.compile(r"\[([A-Z]+)_(\d+)\]")


@dataclass(frozen=True)
class RedactionResult:
    texts: tuple[str, ...]
    counts: dict[str, int] = field(default_factory=dict)
    """Reemplazos por tipo de entidad (`{"cliente": 1, "persona": 2}`). Sin valores."""


PII_TYPES: frozenset[str] = frozenset({"persona", "nomina", "correo", "telefono"})
"""Tipos que se seudonimizan también hacia el modelo local (RouteDecision.must_pseudonymize)."""


class Redactor(Protocol):
    def redact(
        self, ncr_id: UUID, texts: Sequence[str], *, only: frozenset[str] | None = None
    ) -> RedactionResult:
        """`only`: limita los reemplazos a esos tipos de entidad (None = todos)."""
        ...

    def restore(
        self, ncr_id: UUID, texts: Sequence[str], *, json_escaped: bool = False
    ) -> list[str]:
        """`json_escaped`: el texto es JSON; los valores se insertan escapados para no romperlo."""
        ...


@dataclass(frozen=True)
class _Span:
    start: int
    end: int
    entity_type: str
    canonical: str
    """Valor canónico: el del catálogo, el ya guardado, o el texto detectado normalizado."""


class RuleRedactor:
    def __init__(
        self,
        terms: Iterable[CatalogTerm],
        store: PseudonymStore,
        *,
        min_term_length: int = MIN_TERM_LENGTH,
    ) -> None:
        self._store = store
        self._min = min_term_length
        # Lo público puede salir tal cual; lo demás se reemplaza.
        self._catalog: dict[tuple[str, str], str] = {}
        for t in terms:
            key = squash(t.term)
            if (
                t.level is not ConfidentialityLevel.PUBLICO
                and len(key) >= min_term_length
            ):
                self._catalog[(t.kind, key)] = t.term
        self._known_parts = {k for (kind, k) in self._catalog if kind == "parte"}

    # ------------------------------------------------------------------ redact

    def redact(
        self, ncr_id: UUID, texts: Sequence[str], *, only: frozenset[str] | None = None
    ) -> RedactionResult:
        rows = self._store.mapping(ncr_id)
        # (tipo, clave squash) -> (valor canónico, marcador ya asignado | None)
        lookup: dict[tuple[str, str], tuple[str, str | None]] = {
            k: (v, None) for k, v in self._catalog.items()
        }
        for r in rows:
            key = squash(r.real_value)
            if len(key) >= self._min:
                lookup[(r.entity_type, key)] = (r.real_value, r.placeholder)
        # Un nombre que aparece con rol en un texto debe redactarse también donde
        # aparece solo, aunque sea en otro texto del mismo lote: se repite la
        # búsqueda mientras aparezcan valores nuevos (en la práctica, 2 pasadas).
        per_text: list[list[_Span]] = []
        for _ in range(MAX_PASSES):
            matcher = _matcher(lookup)
            per_text = [self._spans(t, lookup, matcher, only) for t in texts]
            fresh = {
                (s.entity_type, squash(s.canonical)): (s.canonical, None)
                for spans in per_text
                for s in spans
                if s.entity_type in _LEARNED
                and (s.entity_type, squash(s.canonical)) not in lookup
                and len(squash(s.canonical)) >= self._min
            }
            if not fresh:
                break
            lookup.update(fresh)

        existing = {(r.entity_type, r.real_value): r.placeholder for r in rows}
        needed = list(
            dict.fromkeys(
                (s.entity_type, s.canonical)
                for spans in per_text
                for s in spans
                if (s.entity_type, s.canonical) not in existing
            )
        )
        placeholders = {**existing, **self._store.assign(ncr_id, needed)}

        counts: dict[str, int] = {}
        out: list[str] = []
        for original, spans in zip(texts, per_text, strict=True):
            redacted = original
            for s in reversed(spans):
                redacted = (
                    redacted[: s.start]
                    + placeholders[(s.entity_type, s.canonical)]
                    + redacted[s.end :]
                )
                counts[s.entity_type] = counts.get(s.entity_type, 0) + 1
            out.append(redacted)
        return RedactionResult(tuple(out), counts)

    def _spans(
        self,
        text: str,
        lookup: dict[tuple[str, str], tuple[str, str | None]],
        matcher: re.Pattern[str] | None,
        only: frozenset[str] | None = None,
    ) -> list[_Span]:
        found: list[_Span] = []
        squashed, index = squash_with_map(text)

        if matcher is not None:
            reverse = {key: (kind, canon) for (kind, key), (canon, _) in lookup.items()}
            for m in matcher.finditer(squashed):
                kind, canon = reverse[m.group(0)]
                found.append(
                    _Span(index[m.start()], index[m.end() - 1] + 1, kind, canon)
                )

        for span in find_pii(text):
            value = " ".join(text[span.start : span.end].split())
            found.append(
                _Span(
                    span.start,
                    span.end,
                    span.kind,
                    _canonical(span.kind, value, lookup),
                )
            )

        for m in PART_SHAPE.finditer(text):
            if squash(m.group(0)) not in self._known_parts:
                value = m.group(0)
                found.append(
                    _Span(
                        m.start(), m.end(), "parte", _canonical("parte", value, lookup)
                    )
                )

        if only is not None:
            found = [s for s in found if s.entity_type in only]
        return _resolve_overlaps(found)

    # ------------------------------------------------------------------ restore

    def restore(
        self, ncr_id: UUID, texts: Sequence[str], *, json_escaped: bool = False
    ) -> list[str]:
        wanted = {m.group(0) for t in texts for m in _PLACEHOLDER.finditer(t)}
        if not wanted:
            return list(texts)
        real = self._store.resolve(ncr_id, wanted)
        if json_escaped:
            real = {k: json.dumps(v, ensure_ascii=False)[1:-1] for k, v in real.items()}

        def sub(m: re.Match[str]) -> str:
            return real.get(m.group(0), m.group(0))  # marcador desconocido: se deja

        return [_PLACEHOLDER.sub(sub, t) for t in texts]


def _canonical(
    kind: str, value: str, lookup: dict[tuple[str, str], tuple[str, str | None]]
) -> str:
    """Reusa el valor ya conocido si es el mismo sin importar mayúsculas, acentos o separadores."""
    known = lookup.get((kind, squash(value)))
    return known[0] if known else value


def _matcher(
    lookup: dict[tuple[str, str], tuple[str, str | None]],
) -> re.Pattern[str] | None:
    keys = sorted({key for (_, key) in lookup}, key=len, reverse=True)
    if not keys:
        return None
    return re.compile("|".join(re.escape(k) for k in keys))


def _resolve_overlaps(spans: list[_Span]) -> list[_Span]:
    """Gana el más largo; a igual longitud, el primero. Devuelve ordenado por posición."""
    chosen: list[_Span] = []
    for s in sorted(spans, key=lambda s: (-(s.end - s.start), s.start)):
        if all(s.end <= c.start or s.start >= c.end for c in chosen):
            chosen.append(s)
    return sorted(chosen, key=lambda s: s.start)


__all__ = ["PII_TYPES", "RedactionResult", "Redactor", "RuleRedactor"]
