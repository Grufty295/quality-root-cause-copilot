"""Guardrails de salida de D2 y D4.

Deterministas, sin modelo. Cada verificación devuelve violaciones con un `code`
estable (va a la traza) y un `detail` en español para el usuario y para el
mensaje de corrección que se le da al modelo. Los detalles nunca citan el texto
ofensivo completo, solo el tipo.

Reglas (PRD, "Guardrails"):

* cada afirmación cita fuentes que existen en el libro de evidencia del turno;
* cada causa cita al menos un fragmento; sin cita válida, se descarta;
* el código de la causa existe en el catálogo (RC-xx / ND-xx) y alguna fuente citada lo respalda;
* prohibido culpar a personas u operadores (el SOP-QA-011 prohíbe "error del operador");
* el agente nunca cierra un 8D;
* abstención: el modelo declara `estado`; si dice `candidato_respaldado` pero la primera
  causa solo cita su propia fila del catálogo y ningún dato del caso, el guardrail lo baja a
  `evidencia_insuficiente` y deja el motivo. Nunca sube un estado: abstenerse siempre se respeta.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from app.agent.catalog import CauseCatalog
from app.agent.evidence import EvidenceBook
from app.agent.schemas import (
    Causa,
    CausaVerificada,
    D2Content,
    D2Draft,
    D4Content,
    D4Draft,
    Descarte,
    Hecho,
)
from app.confidentiality.pii import find_pii
from app.confidentiality.text import fold, squash


@dataclass(frozen=True)
class Violation:
    code: str
    detail: str
    where: str = ""


# Se evalúa sobre texto normalizado con `fold`.
_BLAME_WORDS = re.compile(
    r"\b(?:culpa\w*|negligen\w+|descuid\w+|irresponsab\w+|incompeten\w+|desidia|flojera|sabotaj\w+)\b"
)
_BLAME_HUMAN_ERROR = re.compile(
    r"\berror(?:es)?\s+(?:humano|del?\s+(?:operador|operadora|operario|tecnico|tecnica|personal|inspector|inspectora|mecanico))\b"
    r"|\b(?:operador|operadora|operario|tecnico|inspector)\s+(?:no\s+(?:siguio|cumplio|respeto)|se\s+equivoco|omitio)\b"
)
# Ampliado el 19 oct 2026 (ver docs/seguridad/promptfoo.md): sujeto humano + verbo de falta, y frases de responsabilidad.
# Se excluye a propósito lo que describe al sistema ("no hay evidencia", "no cubre") y las menciones neutras de un rol.
_ROLE = (
    r"(?:operador(?:es|a|as)?|operario(?:s|a|as)?|tecnic[oa]s?|inspector(?:es|a|as)?|supervisor(?:es|a|as)?|"
    r"ingenier[oa]s?|personal|trabajador(?:es|a|as)?|emplead[oa]s?|persona|gente|turno\s+\w+)"
)
_FAULT_VERB = (
    r"(?:se\s+(?:confundio|equivoco|descuido|distrajo|durmio)|cometio|omitio|olvido|erro|fallo\s+al|desobedecio|incumplio|"
    r"no\s+(?!hay\b|existe\b|define\b|cubre\b|menciona\b|incluye\b|indica\b|esta\b|estan\b|tiene\s+(?:registro|evidencia)|"
    r"se\s+(?:registra|encontro|identifico|dispone)|ha\s+sido|fue\s+(?:programad|capacitad|informad)|especifica\b|contempla\b|"
    r"aparece\b|consta\b|requiere\b|detecta\b|puede\b|cuenta\b|cuentan\b|dispone\b|disponen\b|tiene\b|tienen\b)\w+|"
    r"permitio\s+(?:el|la|que)\s+\w+)"
)
_BLAME_PEOPLE = re.compile(
    r"\b" + _ROLE + r"\s+(?:\w+\s+){0,5}?" + _FAULT_VERB + r"\b"
    r"|\b(?:fue|es|era|son|fueron)\s+(?:el|la|los|las)\s+responsables?\b|\bresponsables?\s+de\s+no\b"
    r"|\bresponsable\s+fue\s+(?:el|la)\b"
    r"|\b(?:responsabilidad|culpa)\s+recae\b"
    r"|\bmala\s+decision\s+d(?:el|e)\b"
    r"|\bactitud\s+(?:poco|negativ|irrespons|descuidad)\w*"
    r"|\b(?:falta\s+de|poca|poco)\s+(?:atencion|cuidado|compromiso|disciplina)\b"
    r"|\bllamar(?:le)?\s+(?:la\s+)?atencion\s+(?:al|a\s+la)\b|\bimputable\s+al\b"
    r"|\bquien(?:es)?\s+(?:\w+\s+){0,4}?(?:se\s+equivoco|cometio|fallo)\b"
    r"|\bpoco\s+(?:cuidados|profesional|atent|comprometid)\w*"
    r"|\bsancion(?:ar|es|ado)\b.{0,40}\b" + _ROLE + r"\b"
    r"|\berror\s+d[el]\s+(?:la\s+)?persona\b"
)
_CLOSING = re.compile(
    r"\b(?:se\s+)?(?:cierra|cierro|cerramos|cerro)\s+(?:el\s+|este\s+|la\s+)?(?:8d|ncr|caso|reporte)\b"
    r"|\b(?:8d|ncr|caso|reporte)\s+(?:\w+\s+){0,2}?(?:esta|queda|quedo)\s+(?:como\s+)?(?:cerrad|aprobad|resuelt|concluid|finalizad)\w*"
    r"|\b(?:dar|doy|damos|da|dare|daria)\s+por\s+(?:cerrad|concluid|resuelt|finalizad|terminad)\w*"
    r"|\bcaso\s+cerrado\b|\bestado\s+final\s*:?\s*(?:cerrad|aprobad)"
    r"|\b(?:se\s+aprueba|apruebo|autorizo|autorizamos|se\s+autoriza)\s+(?:el\s+)?(?:cierre|8d|ncr)\b"
    r"|\b(?:8d|ncr)(?!-)\s+(?:\w+\s+){0,2}?cerrad[oa]\b"
    r"|\b(?:8d|ncr|reporte|caso)\s+se\s+(?:considera|da)\s+(?:por\s+)?(?:cerrad|terminad|finalizad|concluid)\w*"
    r"|\bcierre\s+(?:del\s+)?(?:8d|ncr|caso)\s*:?\s*aprobad"
    r"|\b(?:marco|marcar|marcado|marcamos)\s+(?:el\s+|este\s+)?(?:8d|ncr|caso)\s+como\s+(?:resuelt|cerrad|concluid|aprobad)"
    r"|\b(?:puede\s+)?considerarse\s+(?:finalizad|cerrad|concluid|resuelt)\w*"
)
# "cerrar el 8D" solo es una orden de cierre si no es procedimiento ("antes de cerrar", "para cerrar", "sin cerrar").
_CLOSE_INFINITIVE = re.compile(r"(?<![\w])(?:cerrar|cerrarlo)\s+(?:el\s+|este\s+|la\s+)?(?:8d|ncr|caso|reporte)\b")
_PROCEDURAL = re.compile(
    r"(?:antes\s+de|para|hasta|sin|al|de|no|puede|debe|deberia|podra|requiere|necesita|permite|y\s+luego|despues\s+de)\s+$"
)


def _closes(folded: str) -> bool:
    if _CLOSING.search(folded):
        return True
    return any(
        not _PROCEDURAL.search(folded[max(0, m.start() - 22) : m.start()])
        for m in _CLOSE_INFINITIVE.finditer(folded)
    )


# Una negación de evidencia antes del sujeto ("no se encontraron datos que indiquen que el personal incumplió") describe una
# ausencia de dato, no una atribución.
_NEGATED_EVIDENCE = re.compile(
    r"(?:ningun[ao]s?\s+(?:\w+\s+){0,2}indica|no\s+se\s+encontr\w+|no\s+hay\s+(?:evidencia|datos)|sin\s+evidencia|no\s+existe\s+evidencia)"
)


def _blames_people(folded: str) -> bool:
    return any(
        not _NEGATED_EVIDENCE.search(folded[max(0, m.start() - 90) : m.start()])
        for m in _BLAME_PEOPLE.finditer(folded)
    )


def check_blame(texts: Iterable[str]) -> list[Violation]:
    out: list[Violation] = []
    for t in texts:
        folded = fold(t)
        if find_pii(t):
            out.append(
                Violation(
                    "persona_identificable",
                    "El texto nombra a una persona; describe el sistema, no a individuos.",
                )
            )
        if _BLAME_WORDS.search(folded) or _BLAME_HUMAN_ERROR.search(folded) or _blames_people(folded):
            out.append(
                Violation(
                    "culpa_a_personas",
                    "Atribuye la causa a personas ('error del operador', negligencia, culpa). "
                    "Explica qué permitió el error en el sistema: método, instrucción, capacitación, diseño.",
                )
            )
    return _dedupe(out)


def check_closing(texts: Iterable[str]) -> list[Violation]:
    if any(_closes(fold(t)) for t in texts):
        return [
            Violation(
                "cierra_8d",
                "El agente no cierra ni declara cerrado un 8D; solo propone borradores.",
            )
        ]
    return []


def verify_d2(
    draft: D2Draft, book: EvidenceBook
) -> tuple[D2Content | None, list[Violation]]:
    hechos = _hechos(draft)
    violations = [
        *_check_sources(hechos, book),
        *check_blame(h.texto for _, h in hechos),
        *check_closing(h.texto for _, h in hechos),
    ]
    if violations:
        return None, violations
    used = {s for _, h in hechos for s in h.fuentes}
    return D2Content(**draft.model_dump(), indice_fuentes=book.index(used)), []


def verify_d4(
    draft: D4Draft, book: EvidenceBook, catalog: CauseCatalog
) -> tuple[D4Content | None, list[Violation], bool]:
    """Devuelve (contenido, violaciones, ok).

    `ok` es False si alguna causa se descartó: dispara la cascada al modelo grande.
    Con al menos una causa de ocurrencia válida el contenido existe; sin ninguna, es None.
    """
    violations: list[Violation] = []
    descartes: list[Descarte] = []

    valid_occ: list[CausaVerificada] = []
    for i, causa in enumerate(draft.causas_ocurrencia):
        verified, why = _verify_cause(
            causa, f"causas_ocurrencia[{i}]", book, catalog.occurrence
        )
        if verified:
            valid_occ.append(verified)
        else:
            violations.extend(why)
            descartes.append(
                Descarte(
                    codigo=causa.codigo, motivo="; ".join(v.detail for v in why)[:300]
                )
            )

    nd, why = _verify_cause(
        draft.causa_no_deteccion, "causa_no_deteccion", book, catalog.non_detection
    )
    if nd is None:
        violations.extend(why)
        descartes.append(
            Descarte(
                codigo=draft.causa_no_deteccion.codigo,
                motivo="; ".join(v.detail for v in why)[:300],
            )
        )

    ok = not descartes
    if not valid_occ:
        return None, violations, False

    estado, motivo = draft.estado, None
    if estado == "candidato_respaldado" and not has_case_support(valid_occ[0], book):
        estado = "evidencia_insuficiente"
        motivo = (
            f"{valid_occ[0].codigo} solo cita su fila del catálogo: sin un caso parecido ni datos "
            "del caso que la respalden, es una hipótesis por verificar, no un candidato respaldado."
        )

    used = {
        s
        for c in [*valid_occ, *([nd] if nd else [])]
        for h in [*c.evidencia, *c.evidencia_contradictoria]
        for s in h.fuentes
    }
    content = D4Content(
        estado=estado,
        estado_motivo=motivo,
        causas_ocurrencia=valid_occ,
        causa_no_deteccion=nd,
        descartes=descartes,
        indice_fuentes=book.index(used),
    )
    return content, violations, ok


def has_case_support(causa: CausaVerificada, book: EvidenceBook) -> bool:
    """Respaldo en el caso: cita algo más que su fila del catálogo (`respaldo == "caso"`) o
    algún resultado de datos (T#). Solo cuenta la evidencia a favor, no la contradictoria."""
    if causa.respaldo == "caso":
        return True
    return any(
        (e := book.get(s)) is not None and e.kind == "herramienta"
        for h in causa.evidencia
        for s in h.fuentes
    )


# --------------------------------------------------------------------------- internos


def _hechos(draft: D2Draft) -> list[tuple[str, Hecho]]:
    return [
        (name, getattr(draft, name))
        for name in ("que", "por_que", "donde", "cuando", "quien", "como", "cuanto")
    ]


def _check_sources(
    hechos: Iterable[tuple[str, Hecho]], book: EvidenceBook
) -> list[Violation]:
    out = []
    for where, h in hechos:
        for sid in h.fuentes:
            if sid != "NCR" and book.get(sid) is None:
                out.append(
                    Violation(
                        "fuente_inexistente",
                        f"Cita {sid}, que no existe entre las fuentes entregadas.",
                        where,
                    )
                )
    return out


def _verify_cause(
    causa: Causa, where: str, book: EvidenceBook, catalog: dict
) -> tuple[CausaVerificada | None, list[Violation]]:
    v: list[Violation] = []
    entry = catalog.get(causa.codigo)
    if entry is None:
        v.append(
            Violation(
                "codigo_fuera_de_catalogo",
                f"{causa.codigo} no está en el catálogo de causas.",
                where,
            )
        )

    cited = {s for h in causa.evidencia for s in h.fuentes}
    v.extend(
        _check_sources(
            [(where, h) for h in [*causa.evidencia, *causa.evidencia_contradictoria]],
            book,
        )
    )
    fragments = [
        e for sid in cited if (e := book.get(sid)) is not None and e.kind == "fragmento"
    ]
    if not fragments:
        v.append(
            Violation(
                "sin_cita",
                "Ninguna fuente citada es un fragmento recuperado; sin cita se descarta.",
                where,
            )
        )

    code_key = squash(causa.codigo)
    if fragments and not any(code_key in e.searchable for e in fragments):
        v.append(
            Violation(
                "cita_no_respalda_codigo",
                f"Ninguna fuente citada menciona {causa.codigo}; cita la fila del catálogo o el caso que la sustenta.",
                where,
            )
        )

    texts = [
        causa.explicacion,
        causa.pregunta_confirmacion,
        *(h.texto for h in [*causa.evidencia, *causa.evidencia_contradictoria]),
        *(t for t in (causa.refutaria, causa.dato_faltante) if t),
    ]
    v.extend(check_blame(texts))
    v.extend(check_closing(texts))
    if v:
        return None, _dedupe([Violation(x.code, x.detail, where) for x in v])

    only_catalog = all(e.catalog_code == causa.codigo for e in fragments)
    return CausaVerificada(
        **causa.model_dump(), respaldo="solo_catalogo" if only_catalog else "caso"
    ), []


def _dedupe(items: list[Violation]) -> list[Violation]:
    seen: set[tuple[str, str]] = set()
    out = []
    for v in items:
        key = (v.code, v.where)
        if key not in seen:
            seen.add(key)
            out.append(v)
    return out
