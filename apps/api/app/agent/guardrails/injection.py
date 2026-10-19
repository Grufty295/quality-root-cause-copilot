"""Detección básica de prompt injection en texto no confiable.

Heurística por patrones, en español e inglés. Es la capa débil de la defensa y se
declara así: un atacante con paciencia la rodea. Lo que sostiene la seguridad es la
arquitectura (tools de solo lectura, alcance impuesto por el servidor, el agente
nunca cierra un 8D y todo lo citado se verifica), no este detector.

Devuelve ids de patrón, nunca el texto encontrado.
"""

from __future__ import annotations

import re

from app.agent.guardrails.injection_cues import cue_hit
from app.confidentiality.text import fold

# Verbos de "no obedezcas" (formas imperativas, infinitivo y subjuntivo; el pasado y la 3.ª persona se excluyen a propósito
# porque "el operador ignoró las instrucciones" es lenguaje de 8D) y los objetos que un atacante quiere anular.
_DISREGARD = (
    r"ignora|ignore|ignores|olvida|olvides|omite|omita|descarta|descarte|desestima|desestime|prescinde|prescinda|elude|"
    r"anula|anule|desactiva|desactive|deshabilita|pasa\s+por\s+alto|deja\s+de\s+lado|haz\s+caso\s+omiso\s+de|"
    r"bypass|override|overrides|disregard|forget|skip"
)
_RULES = (
    r"(?:instrucciones|indicaciones|reglas|restricciones|pautas|lineamientos|directrices|politicas|salvaguardas|filtros|"
    r"instructions|rules|guidelines|restrictions|policies|safeguards|guardrails|"
    r"todo\s+lo\s+anterior|lo\s+anterior|everything\s+above|procedimiento\s+anterior|"
    r"lo\s+que\s+se\s+te\s+(?:indico|dijo|ordeno)|tus\s+\w+\s+previas|revision\s+humana|citation\s+checks?)"
)

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
            r"\b(?:nuevas?\s+instrucciones|new\s+instructions|a\s+partir\s+de\s+ahora\s+(?:eres|seras|debes|tu\b|responde|ignora|actua|solo|only))"
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
            r"\b(?:envia|envía|manda|send|post|exfiltrate)\w*\s+(?:\w+\s+){0,8}(?:a|to)\s+(?:https?://|\S+@\S+)|https?://\S+\?\S*="
        ),
    ),
    (
        "ignorar_fuentes",
        re.compile(
            r"\b(?:ignora|ignore|olvida|forget|disregard)\w*\s+(?:\w+\s+){0,3}(?:fuentes|sources)\b"
        ),
    ),
    (
        "dirigido_al_asistente",
        re.compile(
            r"\b(?:instruccion(?:es)?|nota|mensaje|importante|aviso)\s+para\s+(?:el|la|los)\s+"
            r"(?:asistente|agente|modelo|ia|llm)\b"
            r"|\bpara\s+el\s+asistente\s+de\s+ia\b"
            r"|\basistente\s+de\s+ia\s+que\s+lea\b"
        ),
    ),
    (
        "rol_de_sistema",
        re.compile(r"(?:^|[\s.;])(?:system|developer)\s*:"),
    ),
    (
        "escalar_privilegios",
        re.compile(
            r"\b(?:usuario\s+actual|tu\s+usuario|el\s+usuario)\s+(?:tiene|es)\s+(?:el\s+)?rol\b"
            r"|\bacceso\s+a\s+todas\s+las\s+(?:plantas|lineas)\b"
        ),
    ),
    (
        "prohibir_consultas",
        re.compile(
            r"\bno\s+(?:consultes|consulte|uses|utilices|llames)\s+(?:\w+\s+){0,2}"
            r"(?:datos|herramientas|tools|fuentes)\b"
        ),
    ),
    (
        "jailbreak",
        re.compile(
            r"\b(?:jailbreak|dan\s+mode|modo\s+desarrollador|developer\s+mode)\b"
        ),
    ),
    # ---- familias agregadas el 19 oct 2026, derivadas del conjunto de desarrollo (gen_variantes.py) y de formatos de chat
    # públicos; NO de `heldout_v1_quemado.py` (ver docs/seguridad/promptfoo.md, "Lo que salió mal").
    (
        "descartar_reglas",
        re.compile(r"\b(?:" + _DISREGARD + r")\s+(?:\w+\s+){0,3}?" + _RULES),
    ),
    (
        "dejar_de_obedecer",
        re.compile(
            r"\b(?:ya\s+no\s+sigas|deja\s+de\s+(?:seguir|obedecer|cumplir)|stop\s+(?:following|obeying)|"
            r"no\s+(?:sigas|respetes|obedezcas))\s+(?:\w+\s+){0,3}?" + _RULES + r"|\blo\s+anterior\s+ya\s+no\s+aplica\b"
        ),
    ),
    (
        "no_considerar_fuentes",
        re.compile(
            r"\b(?:no\s+(?:tomes\s+en\s+cuenta|consideres|revises|consultes|cites)|prescinde\s+de|no\s+hace\s+falta\s+(?:revisar|consultar))\s+"
            r"(?:\w+\s+){0,3}?(?:documentos|fuentes|evidencia|datos|mantenimiento|amef)\b"
        ),
    ),
    (
        "autoridad_o_modo_especial",
        re.compile(
            r"\bautorizo\s+(?:a\s+)?(?:cerrar|aprobar|omitir)\b"
            r"|\bmodo\s+(?:auditoria|mantenimiento|administrador|admin)\b"
            r"|\b(?:necesito|requiero|quiero)\s+que\s+(?:muestres|reveles|imprimas|listes|entregues)\b"
            r"|\b(?:lista|muestra|entrega)\s+(?:\w+\s+){0,4}de\s+otros\s+clientes\b"
        ),
    ),
    (
        "conclusion_impuesta",
        re.compile(
            r"\bya\s+(?:decidio|determino|concluyo)\b.{0,80}\b(?:solo|debe|confirm)"
            r"|\bson\s+(?:por|culpa\s+d[eo]l?)\s+(?:el\s+)?(?:operador|turno)\b"
            r"|\bdeclara\s+(?:\w+\s+){0,2}(?:resuelto|concluido|terminado)\b"
        ),
    ),
    (
        "formato_de_chat",
        re.compile(
            r"\[\s*/?inst\s*\]|<\s*/?\s*(?:system|sys)\s*>|<<\s*/?sys\s*>>|(?:```|~~~)\s*(?:system|sistema)\b|"
            r"\brole\s*:\s*(?:system|assistant)\b"
        ),
    ),
    (
        "exfiltrar_a_destino_externo",
        re.compile(
            r"\b(?:enlace|link|url)\s+a\s+https?://"
            r"|\b(?:reenvia|copia|comparte|publica|forward)\w*\s+(?:\w+\s+){0,8}?(?:a|to)\s+(?:https?://|\S+@\S+)"
        ),
    ),
)


_ZERO_WIDTH = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff\u00ad"))
_LEET = str.maketrans({"0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t", "@": "a", "$": "s"})
_SPELLED = re.compile(r"(?<![\w])(?:\w[ \-._*]){3,}\w(?![\w])")


def _deobfuscate(text: str) -> str:
    """Segunda vista del texto sin los trucos baratos: caracteres invisibles, letras separadas ("i g n o r a"), guiones
    entre palabras, leetspeak, letras repetidas y espacios múltiples. Se busca sobre las dos vistas.

    Solo reescribe lo que haría falta para que un patrón coincida; no pretende ser reversible. Un número legítimo ("0.805 mm", "T1", "L2")
    no se toca: el leetspeak solo cambia símbolos que quedan entre letras.
    """
    t = fold(text).translate(_ZERO_WIDTH)
    t = _SPELLED.sub(lambda m: re.sub(r"[ \-._*]", "", m.group(0)), t)
    t = re.sub(r"(?<=[a-z])-(?=[a-z])", " ", t)
    t = re.sub(r"(?<=[a-z])[013457@$]+(?=[a-z])", lambda m: m.group(0).translate(_LEET), t)
    t = re.sub(r"([a-z])\1{2,}", r"\1", t)
    return re.sub(r"\s+", " ", t)


def detect_injection(text: str) -> list[str]:
    views = {fold(text), _deobfuscate(text)}
    found: list[str] = []
    for view in views:
        for name, pattern in _PATTERNS:
            if name not in found and pattern.search(view):
                found.append(name)
        if "cues_dirigidas_al_modelo" not in found and cue_hit(view):
            found.append("cues_dirigidas_al_modelo")
    return found
