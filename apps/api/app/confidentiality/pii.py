"""Detectores de PII compartidos por el clasificador y el redactor.

Un solo lugar para los patrones: si el clasificador dice que un texto trae PII,
el redactor debe encontrar lo mismo. Devuelven posiciones, no valores, para que
nadie guarde por accidente lo que se detectó.

Heurísticos, no un modelo: reconocen "rol + nombre propio", número de nómina y
correo. Un nombre sin rol delante no se detecta (el redactor lo cubre cuando ya
fue visto antes en la misma NCR).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.confidentiality.text import fold_with_map

PiiKind = Literal["persona", "nomina", "correo"]
KINDS: tuple[PiiKind, ...] = ("persona", "nomina", "correo")

# Sobre texto normalizado con `fold` (minúsculas, sin acentos).
_PAYROLL = re.compile(
    r"\b(?:nomina|empleado|emp|gafete)\s*(?:no\.?|num\.?|numero|#|:)?\s*(?P<n>\d{4,8})\b"
)
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Rol + nombre propio ("operador Juan Pérez"). El rol sin distinguir mayúsculas; el
# nombre exige Mayúscula+minúsculas, así "Operador A" (ya pseudonimizado) no cuenta.
_PERSON = re.compile(
    r"\b(?i:operador|operadora|tecnico|técnico|tecnica|técnica|supervisor|supervisora|inspector|inspectora"
    r"|ingeniero|ingeniera|lider|líder|mecanico|mecánico|mecanica|mecánica|capturista|auditor|auditora)"
    r"[ \t]+(?:(?i:ing|lic|dr|dra|sr|sra|tec|téc|mtro|mtra)\.?[ \t]+)?"
    r"(?P<name>[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:[ \t]+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){0,2})"
)
# Título abreviado + nombre sin rol delante ("Ing. Luis Hernández"). El punto es obligatorio: sin él
# "Ing Luis" podría ser otra cosa, y "Ing." solo no distingue un nombre de una palabra capitalizada.
_TITLE = re.compile(
    r"\b(?:Ing|Lic|Dr|Dra|Mtro|Mtra|Sr|Sra)\.[ \t]+"
    r"(?P<name>[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:[ \t]+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){0,2})"
)
# Palabras de proceso que siguen a un rol en encabezados ("operador Crimpado") y no son nombres.
# Sin esto el redactor las aprende como persona y las tacha en todo el texto.
_PROCESS_WORDS = frozenset(
    [
        "crimpado",
        "corte",
        "desforre",
        "insercion",
        "inserción",
        "ensamble",
        "encintado",
        "retrabajo",
        "prueba",
        "pruebas",
        "inspeccion",
        "inspección",
        "calidad",
        "produccion",
        "producción",
        "mantenimiento",
        "empaque",
        "embarque",
        "ruteo",
        "tablero",
        "estampado",
        "soldadura",
        "setup",
        "verificacion",
        "verificación",
        "proceso",
        "linea",
        "línea",
        "turno",
        "planta",
        "area",
        "área",
    ]
)


@dataclass(frozen=True)
class PiiSpan:
    kind: PiiKind
    start: int
    end: int
    """Posiciones en el texto original. De una persona, solo el nombre (no el rol)."""


def find_pii(text: str) -> list[PiiSpan]:
    spans: list[PiiSpan] = []
    for pattern in (_PERSON, _TITLE):
        for m in pattern.finditer(text):
            if m.group("name").split()[0].lower() in _PROCESS_WORDS:
                continue
            spans.append(PiiSpan("persona", m.start("name"), m.end("name")))
    for m in _EMAIL.finditer(text):
        spans.append(PiiSpan("correo", m.start(), m.end()))
    folded, index = fold_with_map(text)
    for m in _PAYROLL.finditer(folded):
        spans.append(PiiSpan("nomina", index[m.start("n")], index[m.end("n") - 1] + 1))
    return sorted(set(spans), key=lambda s: (s.start, s.end))
