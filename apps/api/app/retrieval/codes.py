"""Códigos exactos: números de parte, causas del AMEF, equipos, lotes, documentos.

La ingesta y la búsqueda usan esta misma función. Si divergen, un código que
existe en el corpus deja de encontrarse sin ningún error visible.

Por qué normalizar: el parser de texto de Postgres parte `RC-01` en `rc` y
`-01`, y `A7-DRH-2210-M` en cinco piezas. Con eso, buscar RC-01 también
encuentra RC-02. Guardando los códigos sin guiones (`rc01`, `a7drh2210m`),
cada uno es un solo lexema y la coincidencia es exacta.
"""

from __future__ import annotations

import re

# Al menos un guion, una letra y un dígito: RC-01, A7-DRH-2210-M, APL-L1-02,
# 8D-2026-011, LT-A-2604-03. Excluye fechas (2026-04-30, sin letras) y palabras
# con guion (re-medir, sin dígitos).
_CODE = re.compile(r"(?<![\w-])[A-Za-z0-9]+(?:-[A-Za-z0-9]+){1,5}(?![\w-])")
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")


def find_codes(text: str) -> list[str]:
    """Códigos tal como aparecen en el texto, en orden y sin repetir."""
    seen: dict[str, None] = {}
    for match in _CODE.finditer(text):
        raw = match.group(0)
        if _is_code(raw):
            seen.setdefault(raw, None)
    return list(seen)


def normalize_code(code: str) -> str:
    return code.replace("-", "").lower()


def codes_field(text: str) -> str:
    """Valor de la columna `fragment.codes`: códigos normalizados separados por espacio."""
    return " ".join(dict.fromkeys(normalize_code(c) for c in find_codes(text)))


def strip_codes(text: str) -> str:
    """Texto sin códigos, para la parte en español de la consulta.

    Si el código queda en el texto, el diccionario español lo parte en piezas
    (`l1`, `02`) que coinciden con cualquier fragmento de la línea 1.
    """
    return _CODE.sub(lambda m: " " if _is_code(m.group(0)) else m.group(0), text)


def _is_code(raw: str) -> bool:
    return bool(_HAS_LETTER.search(raw) and _HAS_DIGIT.search(raw))


def codes_tsquery(text: str) -> str | None:
    """Consulta de prefijo en sintaxis de `to_tsquery('simple', ...)`.

    Prefijo para que `A7-DRH` encuentre `A7-DRH-2210-M`. Los códigos normalizados
    son solo alfanuméricos, así que no hay nada que escapar.
    """
    codes = dict.fromkeys(normalize_code(c) for c in find_codes(text))
    return " | ".join(f"{c}:*" for c in codes) or None
