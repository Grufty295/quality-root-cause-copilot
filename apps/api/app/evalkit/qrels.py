"""Qrels de recuperación: qué debería traer cada búsqueda del agente, por caso.

Se derivan de `esperado` y `episodios_verdad.json`; no se escriben a mano, así que no se
desincronizan del dataset. Cada ancla es (documento, sección); `section=None` = cualquier
sección del documento (las NCR son de una sola idea y su partición no importa).

El agente hace dos búsquedas (graph._run_retrieval) y cada una tiene su propio qrel:

- `cases`  (8D + NCR): el 8D del que el caso es recurrencia y las NCR previas del mismo
  episodio ya visibles al corte (útiles). Del 8D, la sección D4 (la causa) es esencial y
  cualquier otra sección del mismo 8D es útil: la consulta describe el síntoma, así que lo
  normal es que aparezca D2 y no D4. Esa diferencia es lo que mide `precedent@k` frente a
  `hit@k`. Un caso sin recurrencia no tiene ancla esencial: ahí lo que se mide es que NO salga
  un 8D de otra causa (distractor).
  Las NCR históricas que dieron origen a ese 8D también son útiles, y además cada una cita su
  8D ("8D relacionado"): son un camino de un salto al precedente (`precedent_links`).
- `controls` (AMEF, plan de control, instrucciones, SOP): los documentos de control que la fila
  RC del AMEF referencia (p. ej. RC-01 → SOP-MNT-008, WI-CRP-002) son lo esencial. Las filas RC
  y ND son útiles pero no esenciales: el agente ya las recibe completas por el catálogo
  (catalog.load_catalog), así que recuperarlas otra vez no le aporta nada nuevo.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Literal

AMEF_KEY = "AMEF-ARN-PD-001"
ND_CATALOG_KEY = "SOP-QA-011"
EIGHT_D_SECTION = "D4"

Search = Literal["cases", "controls"]

# Partición fija: se ajusta sobre `dev`; `test` se mira solo para confirmar una decisión ya tomada.
# dev = 2 episodios con recurrencia (E6, E7) y 1 de causa nueva (E8); test = 1 con recurrencia (E9)
# y 1 de causa nueva (E10). Con 5 episodios la partición es gruesa: ver docs/evaluacion.md.
DEV_EPISODES = frozenset({"E6", "E7", "E8"})
TEST_EPISODES = frozenset({"E9", "E10"})


@dataclass(frozen=True, order=True)
class Anchor:
    source_key: str
    section: str | None = None

    def label(self) -> str:
        return f"{self.source_key}#{self.section}" if self.section else self.source_key


@dataclass(frozen=True)
class Qrel:
    caso_id: str
    episodio: str
    search: Search
    grades: Mapping[Anchor, int]
    precedent: str | None = None
    """`source_key` del 8D del que el caso es recurrencia, si lo hay."""
    precedent_links: frozenset[str] = frozenset()
    """NCR que citan ese 8D: si sale una, el precedente está a un salto."""
    distractor_kinds: tuple[str, ...] = field(default=())
    """Tipos de documento que NO deberían aparecer (p. ej. 8d en un caso sin recurrencia)."""
    cites: Mapping[str, str] = field(default_factory=dict)
    """NCR histórica → 8D que cita. Sirve para medir qué 8D quedan a un salto del top-k, los
    correctos y los de otra causa."""

    @property
    def split(self) -> str:
        return split_of(self.episodio)


def split_of(episodio: str) -> str:
    if episodio in DEV_EPISODES:
        return "dev"
    if episodio in TEST_EPISODES:
        return "test"
    raise ValueError(f"episodio {episodio!r} sin partición definida")


def build_qrels(
    cases: Iterable[Mapping[str, Any]],
    episodios: Mapping[str, Mapping[str, Any]],
    doc_dates: Mapping[str, date | None],
    control_links: Mapping[str, Iterable[str]] | None = None,
) -> list[Qrel]:
    """Dos qrels por caso.

    `doc_dates`: fecha de cada `source_key` indexado (para el corte as_of).
    `control_links`: RC-xx → documentos de control que su fila del AMEF referencia.
    """
    control_links = control_links or {}
    cites = {
        ncr: v["ocho_d"]
        for v in episodios.values()
        if v.get("ocho_d")
        for ncr in v.get("ncrs_historicas", [])
    }
    out: list[Qrel] = []
    for case in cases:
        exp = case["esperado"]
        epi = case["episodio"]
        as_of = date.fromisoformat(case["as_of"])
        verdad = episodios[epi]

        cases_grades: dict[Anchor, int] = {}
        distractors: tuple[str, ...] = ()
        precedent: str | None = None
        links: set[str] = set()

        def visible(ncr: str, as_of: date = as_of) -> bool:
            # Lo que aún no existía al corte no se le puede exigir.
            fecha = doc_dates.get(ncr)
            return fecha is not None and fecha <= as_of

        if exp.get("recurrente") and exp.get("ocho_d_relacionado"):
            precedent = exp["ocho_d_relacionado"]
            cases_grades[Anchor(precedent)] = 1  # encontró el precedente (otra sección)
            cases_grades[Anchor(precedent, EIGHT_D_SECTION)] = 2  # trajo la causa
            # NCR del episodio histórico que originó ese 8D: mismo modo de falla y lo citan.
            for other in episodios.values():
                if other.get("ocho_d") == precedent:
                    links |= {n for n in other.get("ncrs_historicas", []) if visible(n)}
            for ncr in links:
                cases_grades[Anchor(ncr)] = 1
        else:
            distractors = ("8d",)
        for ncr in verdad.get("ncrs_historicas", []):
            if visible(ncr):
                cases_grades[Anchor(ncr)] = 1

        rc = exp["causa_ocurrencia"]
        # Fila RC y filas ND: útiles, no esenciales (ya vienen por el catálogo).
        controls_grades: dict[Anchor, int] = {Anchor(AMEF_KEY, rc): 1}
        for nd in {*exp.get("no_deteccion_aceptables", []), exp["causa_no_deteccion"]}:
            controls_grades[Anchor(ND_CATALOG_KEY, nd)] = 1
        for doc in control_links.get(rc, ()):
            controls_grades[Anchor(doc)] = 2

        out.append(
            Qrel(
                case["caso_id"],
                epi,
                "cases",
                cases_grades,
                precedent=precedent,
                precedent_links=frozenset(links),
                distractor_kinds=distractors,
                cites=cites,
            )
        )
        out.append(Qrel(case["caso_id"], epi, "controls", controls_grades))
    return out


def anchor_of(source_key: str, section: str, grades: Mapping[Anchor, int]) -> Anchor:
    """Ancla a la que pertenece un fragmento recuperado.

    Si coincide con alguna del qrel, esa; si no, (documento, sección) sin grado, que sirve
    para contar duplicados irrelevantes una sola vez.
    """
    exact = Anchor(source_key, section)
    if exact in grades:
        return exact
    whole = Anchor(source_key, None)
    if whole in grades:
        return whole
    return exact
