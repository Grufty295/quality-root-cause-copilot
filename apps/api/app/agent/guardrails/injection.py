"""Detección básica de prompt injection en texto no confiable.

Heurística por patrones, en español e inglés. Es la capa débil de la defensa y se
declara así: un atacante con paciencia la rodea. Lo que sostiene la seguridad es la
arquitectura (tools de solo lectura, alcance impuesto por el servidor, el agente
nunca cierra un 8D y todo lo citado se verifica), no este detector.

Devuelve ids de patrón, nunca el texto encontrado.
"""

from __future__ import annotations

import re

from app.confidentiality.text import fold

_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "ignorar_instrucciones",
        re.compile(
            r"\b(?:ignora|ignore|olvida|forget|disregard|omite|salta)\w*\s+(?:\w+\s+){0,3}"
            r"(?:instrucciones|instructions|reglas|rules|prompt|indicaciones)"
        ),
    ),
    (
        "nuevas_instrucciones",
        re.compile(
            r"\b(?:nuevas?\s+instrucciones|new\s+instructions|a\s+partir\s+de\s+ahora)\b"
        ),
    ),
    (
        "cambio_de_rol",
        re.compile(
            r"\b(?:eres\s+ahora|ahora\s+eres|you\s+are\s+now|act\s+as|actua\s+como|finge\s+ser|pretend\s+to\s+be)\b"
        ),
    ),
    (
        "prompt_del_sistema",
        re.compile(
            r"\b(?:prompt\s+del?\s+sistema|system\s+prompt|instrucciones\s+del\s+sistema"
            r"|(?:revela|muestra|imprime|reveal|print)\w*\s+(?:\w+\s+){0,3}(?:instrucciones|prompt|configuracion))\b"
        ),
    ),
    (
        "etiquetas_de_control",
        re.compile(
            r"</?\s*(?:system|assistant|instructions?|fuente|caso)\b|\[\s*(?:system|inst)\s*\]|<\|"
        ),
    ),
    (
        "ordenar_cierre_o_aprobacion",
        re.compile(
            r"\b(?:marca|marcar|mark|declara|declare|cierra|close|aprueba|approve)\w*\s+(?:\w+\s+){0,4}"
            r"(?:cerrad|closed|aprobad|approved|8d|ncr)\w*"
        ),
    ),
    (
        "ordenar_sin_citas",
        re.compile(
            r"\b(?:no\s+cites|sin\s+citar|do\s+not\s+cite|omite\s+las\s+citas|no\s+incluyas\s+fuentes)\b"
        ),
    ),
    (
        "ordenar_formato",
        re.compile(
            r"\b(?:responde|answer|respond|contesta)\s+(?:unicamente|solamente|solo|only)\b|\bignora\s+el\s+formato\b"
        ),
    ),
    (
        "exfiltracion",
        re.compile(
            r"\b(?:envia|envía|manda|send|post|exfiltrate)\w*\s+(?:\w+\s+){0,5}(?:a|to)\s+(?:https?://|\S+@\S+)|https?://\S+\?\S*="
        ),
    ),
    (
        "jailbreak",
        re.compile(
            r"\b(?:jailbreak|dan\s+mode|modo\s+desarrollador|developer\s+mode)\b"
        ),
    ),
)


def detect_injection(text: str) -> list[str]:
    folded = fold(text)
    return [name for name, pattern in _PATTERNS if pattern.search(folded)]
