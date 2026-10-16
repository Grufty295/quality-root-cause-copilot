"""Puntuación de un D4 contra `esperado`. Pura: no toca base ni modelo.

Qué se mide y por qué así:

- `rc_top1` / `rc_top3`: la causa de ocurrencia esperada es la primera / está entre las tres.
  El agente ordena de más a menos probable y la primera es la que un ingeniero investigaría.
- `nd_ok`: la causa de no detección está entre las aceptables (`no_deteccion_aceptables`).
- `pass`: `rc_top1` y `nd_ok`. Es la definición estricta que se usa para pass^k.
- Precedentes: qué 8D cita la causa principal como evidencia. En un caso recurrente se
  espera que cite el 8D anterior; en cualquier caso, citar un 8D de *otra* causa como
  respaldo de la causa principal es el error que una expansión por enlace podría provocar.
- Lo que el guardrail descartó cuenta aparte: un descarte no es un acierto ni un fallo de
  causa, pero sí dice cuánto trabajo inválido produjo el modelo.
- Abstención (`estado = evidencia_insuficiente`): `abstained` dice si el borrador se abstuvo.
  Si el caso declara `evidencia_suficiente` (falso = lo correcto es abstenerse), se mide
  `abstention_correct`; sin esa etiqueta, una abstención en un caso con causa esperada cuenta como
  `false_abstention` (el agente tenía con qué y no lo usó). `pass` no cambia: sigue exigiendo la
  causa esperada primero; una abstención con la causa correcta primero también pasa.
- `contradictions`: cuántas causas traen evidencia contradictoria. No hay etiqueta de cuántas
  debería haber; sirve para ver si el modelo usa el campo o lo deja siempre vacío.

No hay juez LLM aquí: todo sale de códigos y citas, que son verificables.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _cited_docs(cause: Mapping[str, Any], index: Mapping[str, Any]) -> set[str]:
    docs: set[str] = set()
    for hecho in cause.get("evidencia") or []:
        for sid in hecho.get("fuentes") or []:
            ref = index.get(sid) or {}
            if ref.get("tipo") == "fragmento" and ref.get("documento"):
                docs.add(str(ref["documento"]))
    return docs


def score_d4(
    content: Mapping[str, Any] | None, esperado: Mapping[str, Any]
) -> dict[str, Any]:
    """Métricas de una corrida. `content` es `section_version.content` de D4 (o None)."""
    expected_rc = esperado["causa_ocurrencia"]
    acceptable_nd = set(esperado.get("no_deteccion_aceptables") or []) | {
        esperado["causa_no_deteccion"]
    }
    recurrent = bool(esperado.get("recurrente"))
    precedent = esperado.get("ocho_d_relacionado") if recurrent else None

    if not content:
        return {
            "generated": False,
            "pass": False,
            "rc_top1": False,
            "rc_top3": False,
            "rc_rank": None,
            "nd_exact": False,
            "nd_ok": False,
            "recurrent": recurrent,
            "top1_cites_precedent": False if recurrent else None,
            "top1_cites_foreign_8d": False,
            "any_cites_foreign_8d": False,
            "top1_support": None,
            "discarded": [],
            "expected_rc_discarded": False,
            "codes": [],
            "nd": None,
            "abstained": None,
            "abstention_correct": None,
            "false_abstention": None,
            "estado_downgraded": None,
            "contradictions": 0,
        }

    causes = list(content.get("causas_ocurrencia") or [])
    index = content.get("indice_fuentes") or {}
    codes = [c.get("codigo") for c in causes]
    rank = codes.index(expected_rc) + 1 if expected_rc in codes else None
    nd_cause = content.get("causa_no_deteccion") or {}
    nd = nd_cause.get("codigo")

    top1_docs = _cited_docs(causes[0], index) if causes else set()
    all_docs = (
        set().union(*(_cited_docs(c, index) for c in causes)) if causes else set()
    )
    top1_8d = {d for d in top1_docs if d.startswith("8D-")}
    all_8d = {d for d in all_docs if d.startswith("8D-")}
    discarded = [d.get("codigo") for d in content.get("descartes") or []]
    abstained = content.get("estado") == "evidencia_insuficiente"
    sufficient = esperado.get("evidencia_suficiente")

    return {
        "generated": True,
        "pass": rank == 1 and nd in acceptable_nd,
        "rc_top1": rank == 1,
        "rc_top3": rank is not None,
        "rc_rank": rank,
        "nd_exact": nd == esperado["causa_no_deteccion"],
        "nd_ok": nd in acceptable_nd,
        "recurrent": recurrent,
        "top1_cites_precedent": (precedent in top1_8d) if recurrent else None,
        "top1_cites_foreign_8d": bool(top1_8d - {precedent}),
        "any_cites_foreign_8d": bool(all_8d - {precedent}),
        "top1_support": causes[0].get("respaldo") if causes else None,
        "discarded": discarded,
        "expected_rc_discarded": expected_rc in discarded,
        "codes": codes,
        "nd": nd,
        "abstained": abstained,
        "abstention_correct": None if sufficient is None else abstained == (not sufficient),
        "false_abstention": abstained and sufficient is not False,
        "estado_downgraded": bool(content.get("estado_motivo")),
        "contradictions": sum(1 for c in causes if c.get("evidencia_contradictoria")),
    }
