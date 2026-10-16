"""Chunking estructural del corpus en Markdown.

Reglas (PRD, "Arquitectura del RAG"):

* El documento se parte por su estructura: cada `##` es una sección (en un 8D,
  una disciplina: D2, D3, D4...) y cada `###` una subsección.
* Las tablas de catálogo (primera columna con códigos: filas del AMEF, catálogo
  ND del SOP) se parten por fila. Cada fila es una unidad citable con su código
  como `section` (RC-01, ND-07).
* Una sección que excede el presupuesto se parte por bloques (párrafo, lista,
  grupo de filas de tabla repitiendo el encabezado), nunca a media oración salvo
  que una oración sola exceda el presupuesto.
* Cada fragmento empieza con un prefijo de contexto (documento y sección), para
  que el fragmento suelto siga diciendo de dónde viene, al modelo de embeddings
  y al LLM.

Presupuesto: el límite de 550 caracteres vino del modelo anterior
(paraphrase-multilingual-MiniLM-L12-v2, 128 tokens; en español, unos 450-550
caracteres). El modelo actual (intfloat/multilingual-e5-large) admite 512
tokens, así que 550 es conservador. Subirlo es un experimento que se mide con
Recall@5: fragmentos más largos diluyen el vector. Lo que pase del límite del
modelo no entra al vector (sí al índice de texto completo). Cambiar `max_chars`
exige reindexar a mano: la ingesta no detecta ese cambio.

Minimización (PRD, "Manejo de datos"): lo que el análisis no necesita no se
ingiere. El D1 de un 8D (nombres y números de empleado del equipo) y la fila
"Reportado por" de una NCR se descartan aquí.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.retrieval.codes import codes_field, find_codes
from app.retrieval.models import DocumentKind, FragmentDraft

# Cambia esta versión cuando cambien las reglas: la ingesta reprocesa todo
# documento indexado con otra versión.
CHUNKER_VERSION = "struct-v1"
DEFAULT_MAX_CHARS = 550

_LABEL_MAX = 70
_SECTION_MAX = 120
_EIGHT_D_DISCIPLINE = re.compile(r"^(D\d)\b")
_MINIMIZED_8D_SECTIONS = re.compile(r"^D1\b")
_MINIMIZED_ROWS = frozenset({"reportado por"})
_SENTENCE_END = re.compile(r"(?<=[.;:])\s+")
# Columnas que van primero en una fila de catálogo: lo que describe la causa
# tiene que caer dentro de los 128 tokens del embedding.
_ROW_PRIORITY = ("código", "modo de falla", "causa", "categoría")


@dataclass
class _Section:
    h2: str
    h3: str | None = None
    lines: list[str] = field(default_factory=list)


def chunk_markdown(
    *,
    source_key: str,
    title: str,
    kind: DocumentKind,
    body: str,
    max_chars: int = DEFAULT_MAX_CHARS,
) -> list[FragmentDraft]:
    """Parte el cuerpo (sin front matter) en fragmentos ordenados."""
    if max_chars < 200:
        raise ValueError("max_chars < 200 deja fragmentos sin contexto útil")

    label = title if len(title) <= _LABEL_MAX else source_key
    pieces: list[_Piece] = []

    for sec in _sections(body):
        if kind is DocumentKind.EIGHT_D and _MINIMIZED_8D_SECTIONS.match(sec.h2):
            continue
        section_id = _section_id(kind, sec.h2)
        heading = sec.h2 if sec.h3 is None else f"{sec.h2} › {sec.h3}"
        prefix = f"{label} · {heading}\n"

        pending: list[str] = []
        for block in _blocks(sec.lines):
            rows = _catalog_rows(block)
            if rows is None:
                pending.append(block)
                continue
            # Una tabla de catálogo corta el flujo: lo acumulado sale antes que sus filas.
            pieces.extend(_Piece(section_id, heading, prefix, b) for b in _pack(prefix, pending, max_chars))
            pending = []
            # Prefijo corto: la fila ya empieza con su código y tiene que caber en el embedding.
            pieces.extend(_Piece(code, code, f"{source_key} › {code}\n", text, atomic=True) for code, text in rows)
        pieces.extend(_Piece(section_id, heading, prefix, b) for b in _pack(prefix, pending, max_chars))

    # En un 8D cada disciplina queda separada aunque sea corta: las citas apuntan a
    # disciplinas. En lo demás (NCR, SOP, instrucciones) se unen secciones contiguas
    # pequeñas para no indexar fragmentos de una línea ("Disposición: Retrabajo").
    if kind is not DocumentKind.EIGHT_D:
        pieces = _merge_small(pieces, max_chars)

    return [
        FragmentDraft(ordinal=i, section=p.section[:_SECTION_MAX], content=p.content, codes=codes_field(p.content))
        for i, p in enumerate(pieces)
    ]


@dataclass
class _Piece:
    section: str
    heading: str
    prefix: str
    body: str
    atomic: bool = False

    @property
    def content(self) -> str:
        return self.prefix + self.body


def _merge_small(pieces: list[_Piece], max_chars: int) -> list[_Piece]:
    out: list[_Piece] = []
    for p in pieces:
        prev = out[-1] if out else None
        if prev is not None and not prev.atomic and not p.atomic and prev.heading != p.heading:
            merged_body = f"{prev.body}\n\n{p.heading}:\n{p.body}"
            if len(prev.prefix) + len(merged_body) <= max_chars:
                out[-1] = _Piece(f"{prev.section} + {p.section}", prev.heading, prev.prefix, merged_body)
                continue
        out.append(p)
    return out


# --------------------------------------------------------------------------- secciones


def _sections(body: str) -> list[_Section]:
    sections: list[_Section] = [_Section(h2="Resumen")]
    for raw in body.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            continue  # el H1 repite el título del front matter
        if line.startswith("## "):
            sections.append(_Section(h2=line[3:].strip()))
        elif line.startswith("### "):
            sections.append(_Section(h2=sections[-1].h2, h3=line[4:].strip()))
        elif _is_table_row(line) and _first_cell(line).lower() in _MINIMIZED_ROWS:
            continue
        else:
            sections[-1].lines.append(line)
    return [s for s in sections if any(line.strip() for line in s.lines)]


def _section_id(kind: DocumentKind, h2: str) -> str:
    if kind is DocumentKind.EIGHT_D and (m := _EIGHT_D_DISCIPLINE.match(h2)):
        return m.group(1)
    return h2[:_SECTION_MAX]


# --------------------------------------------------------------------------- bloques


def _blocks(lines: list[str]) -> list[str]:
    """Párrafos, listas y tablas. Una tabla es un bloque aunque no la rodeen líneas vacías."""
    blocks: list[str] = []
    current: list[str] = []
    in_table = False
    for line in lines:
        is_row = _is_table_row(line)
        if not line.strip() or is_row != in_table:
            if current:
                blocks.append("\n".join(current))
            current = []
        in_table = is_row
        if line.strip():
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return [_compact_field_table(b) for b in blocks]


def _compact_field_table(block: str) -> str:
    """Tabla `| Campo | Valor |` -> líneas `Campo: Valor`.

    La sintaxis de tabla gasta tokens del embedding sin aportar significado; en
    una NCR, la tabla de campos sola casi llena los 128 tokens. Las filas sin
    valor ("—") se omiten.
    """
    lines = block.splitlines()
    if len(lines) < 3 or not _is_separator(lines[1]):
        return block
    if [c.lower() for c in _cells(lines[0])] != ["campo", "valor"]:
        return block
    out = []
    for row in lines[2:]:
        cells = _cells(row)
        if len(cells) == 2 and cells[1] not in ("", "—", "-"):
            out.append(f"{cells[0]}: {cells[1]}")
    return "\n".join(out) or block


def _is_table_row(line: str) -> bool:
    s = line.strip()
    return s.startswith("|") and s.endswith("|")


def _cells(line: str) -> list[str]:
    return [c.strip() for c in line.strip().strip("|").split("|")]


def _first_cell(line: str) -> str:
    return _cells(line)[0] if _is_table_row(line) else ""


def _is_separator(line: str) -> bool:
    return all(re.fullmatch(r":?-{3,}:?", c) for c in _cells(line))


def _catalog_rows(block: str) -> list[tuple[str, str]] | None:
    """Si el bloque es una tabla cuya primera columna son códigos, una entrada por fila."""
    lines = block.splitlines()
    if len(lines) < 3 or not _is_table_row(lines[0]) or not _is_separator(lines[1]):
        return None
    header = _cells(lines[0])
    data = [_cells(row) for row in lines[2:]]
    if not data or any(find_codes(row[0]) != [row[0]] for row in data):
        return None

    order = sorted(
        range(len(header)),
        key=lambda i: next((p for p, name in enumerate(_ROW_PRIORITY) if header[i].lower() == name), 99),
    )
    out: list[tuple[str, str]] = []
    for row in data:
        parts = [f"{header[i]}: {row[i]}" for i in order if i < len(row) and row[i] and i > 0]
        out.append((row[0], f"{row[0]} — " + "; ".join(parts)))
    return out


# --------------------------------------------------------------------------- empaquetado


def _pack(prefix: str, blocks: list[str], max_chars: int) -> list[str]:
    """Agrupa bloques en cuerpos que, con el prefijo, caben en max_chars."""
    budget = max(max_chars - len(prefix), 120)
    pieces: list[str] = []
    for block in blocks:
        pieces.extend(_split_block(block, budget))
    return _group(pieces, budget, sep="\n\n")


def _split_block(block: str, budget: int) -> list[str]:
    if len(block) <= budget:
        return [block]
    lines = block.splitlines()
    if _is_table_row(lines[0]) and len(lines) > 2 and _is_separator(lines[1]):
        return _split_table(lines, budget)
    if len(lines) > 1:  # lista o párrafo con saltos: se agrupa por línea
        return _group(lines, budget, sep="\n")
    return _group(_SENTENCE_END.split(block), budget, sep=" ")


def _split_table(lines: list[str], budget: int) -> list[str]:
    head = lines[:2]
    head_len = len("\n".join(head)) + 1
    groups = _group(lines[2:], max(budget - head_len, 80), sep="\n")
    return ["\n".join(head + [g]) for g in groups]


def _group(units: list[str], budget: int, *, sep: str) -> list[str]:
    out: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}{sep}{unit}" if current else unit
        if current and len(candidate) > budget:
            out.append(current)
            current = unit
        else:
            current = candidate
    if current:
        out.append(current)
    return out
