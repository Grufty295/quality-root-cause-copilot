"""Diagnósticos de consistencia de D2/D4. Deterministas, sin modelo y que NO bloquean.

A diferencia de `output.py`, aquí nada descarta un borrador: cada función devuelve hallazgos que
se registran como eventos de la corrida y como contadores del eval. Se mantienen aparte a propósito:
son heurísticas sobre texto libre (identificadores y cifras), con falsos positivos posibles, y un
bloqueo con falsos positivos tumba borradores buenos. Se vuelven bloqueantes, si alguna vez, con
datos de varias series y sin mover el umbral para que una versión pase.

Qué atrapan (los tres salieron de un re-análisis real, NCR-2026-0012, v5):

* `unanchored_causes`: una causa de ocurrencia que no cita ningún dato del caso. `respaldo="caso"`
  se cumple con cualquier fragmento que no sea su propia fila del catálogo, así que un WI genérico
  basta; esto exige además la NCR, un resultado de datos (T#) o un precedente (NCR/8D previo).
* `sin_dato_contradictions`: D2 dice "sin dato en las fuentes" sobre un documento que D4 (o el mismo
  D2) cita como evidencia. Es una señal para revisar, no un veredicto: "sin dato sobre X en el WI"
  puede ser cierto aunque el WI se cite para otra cosa.
* `ungrounded_numbers`: cifras de la salida que no aparecen en la NCR ni en ninguna fuente de la
  corrida y que tampoco salen de operar con otras cifras del mismo texto (sumas, restas,
  porcentajes). En las 108 corridas dev de `dev-fix`, sin esa tolerancia el 26% de las corridas salía
  marcado, casi todo por totales y porcentajes calculados por el modelo.

Ninguno dice si la causa es correcta: solo detectan inconsistencias entre lo que el borrador afirma
y lo que él mismo cita o recibió.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from itertools import combinations
from typing import Any

from app.confidentiality.text import fold

# --------------------------------------------------------------------------- anclas de caso

_PRECEDENT_DOCS = ("NCR-", "8D-")


def _is_case_anchor(sid: str, index: Mapping[str, Any]) -> bool:
    if sid == "NCR":
        return True
    ref = index.get(sid) or {}
    tipo = ref.get("tipo")
    if tipo in ("reporte", "herramienta"):
        return True
    return tipo == "fragmento" and str(ref.get("documento") or "").startswith(
        _PRECEDENT_DOCS
    )


def unanchored_causes(d4: Mapping[str, Any] | None) -> list[str]:
    """Códigos de causas de ocurrencia sin ninguna fuente del caso (NCR, datos o precedente).

    La causa de no detección no se evalúa: describe el sistema de control y su evidencia es
    documental por naturaleza (SOP, plan de control), no datos del caso."""
    if not d4:
        return []
    index = d4.get("indice_fuentes") or {}
    out: list[str] = []
    for c in d4.get("causas_ocurrencia") or []:
        cited = {s for h in c.get("evidencia") or [] for s in h.get("fuentes") or []}
        if not any(_is_case_anchor(s, index) for s in cited):
            out.append(str(c.get("codigo")))
    return out


# --------------------------------------------------------------------------- "sin dato"

_D2_FIELDS = ("que", "por_que", "donde", "cuando", "quien", "como", "cuanto")
_DOC_ID = re.compile(r"\b[A-Z0-9]{2,6}(?:-[A-Z0-9]{1,6}){1,4}\b")
_FAMILY = re.compile(r"\b[A-Z]{2,6}\b")
_SENTENCE = re.compile(r"(?<=[.;])\s+")
# Familias demasiado genéricas para decir "el documento X": la propia NCR y los 8D.
_GENERIC_FAMILIES = frozenset({"NCR", "8D"})


def _documents(content: Mapping[str, Any] | None) -> set[str]:
    index = (content or {}).get("indice_fuentes") or {}
    return {
        str(r["documento"])
        for r in index.values()
        if r.get("tipo") == "fragmento" and r.get("documento")
    }


def sin_dato_contradictions(
    d2: Mapping[str, Any] | None, d4: Mapping[str, Any] | None
) -> list[dict[str, Any]]:
    """Frases de D2 con "sin dato" que nombran un documento citado en D2 o D4.

    Coincide el identificador completo (WI-INS-004) o la familia sola (AMEF) cuando algún
    documento citado empieza por ella. Cada hallazgo: campo, documentos y la frase."""
    if not d2:
        return []
    docs = _documents(d2) | _documents(d4)
    families = {d.split("-")[0] for d in docs} - _GENERIC_FAMILIES
    out: list[dict[str, Any]] = []
    for campo in _D2_FIELDS:
        texto = ((d2.get(campo) or {}).get("texto")) or ""
        for sentence in _SENTENCE.split(texto):
            if "sin dato" not in fold(sentence):
                continue
            hits = {t for t in _DOC_ID.findall(sentence) if t in docs}
            # La familia sola (AMEF) cuenta; el prefijo de otro identificador (WI-INS-099) no.
            bare = _FAMILY.findall(_DOC_ID.sub(" ", sentence))
            hits |= {t for t in bare if t in families}
            if hits:
                out.append(
                    {
                        "campo": campo,
                        "documentos": sorted(hits),
                        "frase": sentence.strip()[:200],
                    }
                )
    return out


# --------------------------------------------------------------------------- cifras

# Identificadores con letras y dígitos (8D-2026-019, B3-FDH-0451, C08, F12, T6, 2026-10-17) y
# sus continuaciones abreviadas ("LT-B-2608-12, -13, -14" o "LT-B-2608-12/13/14"): no son cifras.
_IDENT = re.compile(
    r"\b[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+\b|\b[A-Za-z]+\d+[A-Za-z0-9]*\b|\b\d+[A-Za-z]+\d*\b"
    r"|(?<![\w.])-\d+\b|(?<=\w)/\d+\b"
)
_MARKER = re.compile(r"\(\d\)")
_NUMBER = re.compile(r"\d[\d.,]*\d|\d")
_POOL_MAX = 12


def _canonical(raw: str) -> str | None:
    s = raw.strip(".,")
    if not s:
        return None
    if re.fullmatch(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?", s):  # 165,602  14,258.5
        s = s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+(?:,\d+)?", s):  # 165.602,5
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", ".")
    try:
        out = repr(float(s))
    except ValueError:
        return None
    return out.removesuffix(".0")


def numbers_in(text: str) -> set[str]:
    cleaned = _MARKER.sub(" ", _IDENT.sub(" ", text))
    return {c for m in _NUMBER.findall(cleaned) if (c := _canonical(m))}


def _tolerance(canonical: str) -> float:
    decimals = len(canonical.split(".")[1]) if "." in canonical else 0
    return 0.5 * 10**-decimals + 1e-9


def _derivable(canonical: str, pool: Sequence[str]) -> bool:
    """¿Sale de operar con las cifras del mismo texto? Suma de 2 o 3, resta, o porcentaje de
    una cifra (o suma de dos) sobre otra. Deja pasar cifras derivadas legítimas ("66 + 37 = 103",
    "120 de 188 = 63.8%"); a cambio, una inventada que coincida por azar también pasa."""
    x = float(canonical)
    tol = _tolerance(canonical)
    values = sorted({float(c) for c in pool})[:_POOL_MAX]
    pairs = {a + b for a, b in combinations(values, 2)}
    sums = set(values) | pairs | {a + b + c for a, b, c in combinations(values, 3)}
    if any(abs(x - v) <= tol for v in sums):
        return True
    if any(abs(x - abs(a - b)) <= tol for a, b in combinations(values, 2)):
        return True
    numerators = set(values) | pairs
    return any(
        abs(x - 100 * a / b) <= tol for a in numerators for b in values if b and a <= b
    )


def ungrounded_numbers(texts: Iterable[str], sources: Iterable[str]) -> list[str]:
    """Cifras de `texts` que no están en `sources` (NCR y cuerpos de evidencia) ni se derivan de
    otras cifras del mismo texto, ordenadas."""
    known: set[str] = set()
    for s in sources:
        known |= numbers_in(s)
    found: set[str] = set()
    for t in texts:
        here = numbers_in(t)
        for c in here - known:
            if not _derivable(c, sorted(here - {c})):
                found.add(c)
    return sorted(found, key=float)


def d4_texts(d4: Mapping[str, Any] | None) -> list[str]:
    out: list[str] = []
    for c in [
        *((d4 or {}).get("causas_ocurrencia") or []),
        (d4 or {}).get("causa_no_deteccion"),
    ]:
        if not c:
            continue
        out += [c.get("explicacion") or "", c.get("pregunta_confirmacion") or ""]
        out += [c.get("refutaria") or "", c.get("dato_faltante") or ""]
        out += [
            h.get("texto") or ""
            for h in [
                *(c.get("evidencia") or []),
                *(c.get("evidencia_contradictoria") or []),
            ]
        ]
    return out


def d2_texts(d2: Mapping[str, Any] | None) -> list[str]:
    return [((d2 or {}).get(f) or {}).get("texto") or "" for f in _D2_FIELDS]


# --------------------------------------------------------------------------- resumen


def diagnose(
    *,
    d2: Mapping[str, Any] | None,
    d4: Mapping[str, Any] | None,
    sources: Iterable[str],
) -> dict[str, Any]:
    """Los tres diagnósticos de una corrida. `sources`: texto de la NCR y de cada evidencia."""
    sources = list(sources)
    return {
        "unanchored_causes": unanchored_causes(d4),
        "sin_dato_contradictions": sin_dato_contradictions(d2, d4),
        "ungrounded_numbers": ungrounded_numbers(
            [*d2_texts(d2), *d4_texts(d4)], sources
        ),
    }


def as_events(found: Mapping[str, Any]) -> list[dict[str, str]]:
    """Eventos para la traza de la corrida. Vacío si no hay hallazgos."""
    out: list[dict[str, str]] = []
    if found["unanchored_causes"]:
        out.append(
            {
                "stage": "consistencia",
                "event": "causa_sin_ancla",
                "detail": ", ".join(found["unanchored_causes"]),
            }
        )
    for c in found["sin_dato_contradictions"]:
        out.append(
            {
                "stage": "consistencia",
                "event": "sin_dato_contradictorio",
                "detail": f"{c['campo']}: {', '.join(c['documentos'])}",
            }
        )
    if found["ungrounded_numbers"]:
        out.append(
            {
                "stage": "consistencia",
                "event": "cifra_sin_respaldo",
                "detail": ", ".join(found["ungrounded_numbers"][:12]),
            }
        )
    return out
