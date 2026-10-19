"""Detectores de PII compartidos por el clasificador y el redactor.

Un solo lugar para los patrones: si el clasificador dice que un texto trae PII,
el redactor debe encontrar lo mismo. Devuelven posiciones, no valores, para que
nadie guarde por accidente lo que se detectó.

Heurísticos, no un modelo: reconocen "rol + nombre propio", "etiqueta de contacto +
nombre propio" ("Contacto del reportante: ..."), número de nómina, correo y teléfono.
Un nombre sin rol ni etiqueta delante no se detecta (el redactor lo cubre cuando ya
fue visto antes en la misma NCR).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from app.confidentiality.text import fold_with_map

PiiKind = Literal["persona", "nomina", "correo", "telefono"]
KINDS: tuple[PiiKind, ...] = ("persona", "nomina", "correo", "telefono")

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
# Etiqueta de contacto + nombre ("Contacto del reportante: Paola Ríos"). Los dos puntos o el guion son
# obligatorios salvo en "reportado por"/"reportó", que ya anuncian a una persona.
_LABELED = re.compile(
    r"\b(?i:reportante|contacto(?:[ \t]+del[ \t]+reportante)?|responsable)[ \t]*[:\-][ \t]*"
    r"(?P<name>[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:[ \t]+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){0,2})"
    r"|\b(?i:reportado[ \t]+por|report[óo])[ \t]+"
    r"(?P<name2>[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}(?:[ \t]+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{2,}){0,2})"
)
# Teléfono mexicano de 10 dígitos. Con palabra de contexto ("cel", "tel", "whatsapp") basta; sin ella exige
# separadores (656 123 4567), para no tomar por teléfono un lote o un número de serie de 10 dígitos.
_PHONE_CONTEXT = re.compile(
    r"\b(?:cel|celular|tel|telefono|movil|whatsapp)\s*[:.#]?\s*(?P<n>\+?(?:52[\s.-]?)?[\d\s.()-]{9,16}\d)\b"
)
_PHONE_SEPARATED = re.compile(
    r"(?<![\w-])(?P<n>\d{3}[ .-]\d{3}[ .-]\d{4}|\d{2}[ .-]\d{4}[ .-]\d{4})(?![\w-])"
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
        "cliente",
        "proveedor",
        "gerencia",
        "almacen",
        "almacén",
        "logistica",
        "logística",
        "ingenieria",
        "ingeniería",
        "sistemas",
        "metrologia",
        "metrología",
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
    for pattern in (_PERSON, _TITLE, _LABELED):
        for m in pattern.finditer(text):
            group = "name" if m.groupdict().get("name") else "name2"
            if m.groupdict().get(group) is None:
                continue
            if m.group(group).split()[0].lower() in _PROCESS_WORDS:
                continue
            spans.append(PiiSpan("persona", m.start(group), m.end(group)))
    for m in _EMAIL.finditer(text):
        spans.append(PiiSpan("correo", m.start(), m.end()))
    folded, index = fold_with_map(text)
    for m in _PAYROLL.finditer(folded):
        spans.append(PiiSpan("nomina", index[m.start("n")], index[m.end("n") - 1] + 1))
    for pattern in (_PHONE_CONTEXT, _PHONE_SEPARATED):
        for m in pattern.finditer(folded):
            if 10 <= sum(c.isdigit() for c in m.group("n")) <= 12:
                spans.append(PiiSpan("telefono", index[m.start("n")], index[m.end("n") - 1] + 1))
    return sorted(set(spans), key=lambda s: (s.start, s.end))
