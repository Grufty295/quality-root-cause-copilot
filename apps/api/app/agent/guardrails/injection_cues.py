"""Segunda capa del detector: combinación de señales por cláusula, en vez de frases fijas.

Una frase fija solo atrapa lo que alguien ya escribió. Aquí una cláusula se marca cuando mezcla dos de tres señales:

* DIRIGIDA: le habla al modelo ("tu", "te", "eres", "asistente", "you") ;
* ORDEN: verbo en imperativo que pide una acción ("responde", "imprime", "aprueba", "ignora", "list");
* META: habla de lo que gobierna al modelo ("instrucciones", "reglas", "configuración", "formato", "fuentes").

Un texto operativo de planta ("Registra la altura de crimpado") trae ORDEN sin DIRIGIDA ni META; una NCR describe hechos
en tercera persona. Los dos pares que sí se marcan (DIRIGIDA+ORDEN, ORDEN+META, DIRIGIDA+META) son raros en ese lenguaje.

Límite declarado: es una heurística léxica. Medida el 19 oct 2026 contra los falsos positivos del corpus (1,288 párrafos)
y contra variantes que no se usaron para escribir el léxico solo en parte (ver `docs/seguridad/promptfoo.md`).
"""

from __future__ import annotations

import re

_CLAUSE = re.compile(r"[.;:!?\n]+|\s[—–-]\s|\(|\)")

_ADDRESS = re.compile(
    r"\b(?:tu|tus|te|ti|eres|debes|puedes|tienes|asistente|agente|modelo|llm|ia|you|your|you're|assistant|bot)\b"
)
_ORDER = re.compile(
    r"\b(?:responde|contesta|imprime|muestra|lista|entrega|escribe|redacta|deja|pon|ponle|evita|olvida|ignora|pasa|"
    r"considera|imagina|finge|actua|aprueba|cierra|confirma|registra|manda|envia|reenvia|guarda|publica|haz|dame|dime|"
    r"cambia|limitate|atiende|obedece|trata|invente|inventa|omite|salta|descarta|ponga|"
    r"pretend|ignore|forget|set\s+aside|switch|dump|list|print|reveal|stop|answer|reply|respond|disclose|bypass|override|"
    r"approve|close|write|tell|show|give)\b"
)
_META = re.compile(
    r"\b(?:instrucciones|indicaciones|reglas|politicas?|restricciones|directrices|directions|pautas|prompt|configuracion|"
    r"configuraron|mensaje\s+inicial|formato|citas|fuentes|catalogo|revision\s+humana|aprobacion|"
    r"lo\s+que\s+te\s+(?:dijeron|indicaron|pidieron)|previas?|anteriores|instructions|rules|polic(?:y|ies)|guidelines|"
    r"context\s+window|system|sources|citations?|safety|earlier|previous)\b"
)


def cue_hit(folded: str) -> bool:
    """`folded`: texto ya normalizado con `fold` (minúsculas, sin acentos)."""
    for clause in _CLAUSE.split(folded):
        if len(clause) < 12:
            continue
        a, o, m = bool(_ADDRESS.search(clause)), bool(_ORDER.search(clause)), bool(_META.search(clause))
        if (a and o) or (o and m) or (a and m):
            return True
    return False
