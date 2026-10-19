"""Diagnósticos de consistencia (no bloqueantes) sobre borradores reales.

Los casos salen del re-análisis de NCR-2026-0012 (v5, 18 oct 2026). Los fixtures se reconstruyeron
del texto que mostró la interfaz, no del JSON persistido: los identificadores de fuente (F6, F10…)
son los que el propio borrador cita, y el documento de cada uno se verificó contra el corpus.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.agent.guardrails.diagnostics import (
    as_events,
    diagnose,
    numbers_in,
    sin_dato_contradictions,
    unanchored_causes,
    ungrounded_numbers,
)
from app.agent.service import _diagnostic_events
from app.evalkit.agent import consistency_diagnostics


def h(texto: str, *fuentes: str) -> dict:
    return {"texto": texto, "fuentes": list(fuentes)}


INDEX = {
    "NCR": {"tipo": "reporte"},
    "F1": {"tipo": "fragmento", "documento": "NCR-2026-0002"},
    "F6": {"tipo": "fragmento", "documento": "AMEF-ARN-PD-001"},
    "F8": {"tipo": "fragmento", "documento": "WI-INS-004"},
    "F10": {"tipo": "fragmento", "documento": "WI-INS-004"},
    "F11": {"tipo": "fragmento", "documento": "WI-INS-004"},
    "F12": {"tipo": "fragmento", "documento": "8D-2026-019"},
    "F16": {"tipo": "fragmento", "documento": "AMEF-ARN-PD-001"},
    "F23": {"tipo": "fragmento", "documento": "AMEF-ARN-PD-001"},
    "F36": {"tipo": "fragmento", "documento": "SOP-QA-011"},
    "T1": {"tipo": "herramienta", "herramienta": "defects_by_station"},
    "T6": {"tipo": "herramienta", "herramienta": "defects_by_lot"},
}


def cause(codigo: str, *evidencia: dict, texto: str = "") -> dict:
    return {
        "codigo": codigo,
        "explicacion": texto,
        "pregunta_confirmacion": "",
        "evidencia": list(evidencia),
        "evidencia_contradictoria": [],
    }


D4_V5 = {
    "indice_fuentes": INDEX,
    "causas_ocurrencia": [
        cause(
            "RC-03",
            h(
                "AMEF RC-03: método de inserción sin verificación de empuje-jalón.",
                "F6",
            ),
            h("El reporte consigna que no se recibió la instrucción de jalón.", "NCR"),
            h("WI-INS-004 solo indica verificar visualmente la TPA.", "F10"),
            texto="La inducción en estación de 4 horas (F11) no asegura la instrucción.",
        ),
        cause(
            "RC-02",
            h("AMEF RC-02: lanza de retención deformada.", "F16"),
            h("8D-2026-019: lanza deformada en el lote LT-A-2605-06.", "F12"),
            h("Defectos de L1 por lote: LT-B-2609-15 29 (46.0%).", "T6"),
        ),
        # RC-10 cita la fila del AMEF y un WI genérico: ningún dato de este caso.
        cause(
            "RC-10",
            h("AMEF RC-10: ayuda visual con mapa de cavidades incorrecto.", "F23"),
            h(
                "WI-INS-004 pide verificar que la ayuda visual corresponda a la variante.",
                "F8",
            ),
        ),
    ],
    "causa_no_deteccion": cause(
        "ND-03", h("SOP-QA-011 ND-03: verificación en estación solo visual.", "F36")
    ),
}

D2_V5 = {
    "indice_fuentes": {"NCR": {"tipo": "reporte"}},
    "que": h("Terminal no asentada en el conector C08 de la pieza B3-FDH-0451.", "NCR"),
    "donde": h(
        "Línea L1, turno 3. Estación específica de inserción del C08: sin dato en las fuentes.",
        "NCR",
    ),
    "cuando": h(
        "Reporte NCR-2026-0012 con fecha 2026-10-17. Fecha de inicio de la condición: sin dato en las fuentes.",
        "NCR",
    ),
    "quien": h(
        "Área de detección: auditoría de producto. No se identifican personas.", "NCR"
    ),
    "por_que": h(
        "Sin dato en las fuentes sobre el requisito específico del cliente KES para asentamiento.",
        "NCR",
    ),
    # Copia el brief como lista de huecos, aunque D4 cita esos mismos documentos.
    "como": h(
        "El reporte consigna que no se recibió la instrucción de verificar con jalón. Sin dato en las "
        "fuentes sobre si el WI-INS-004 contempla la prueba de jalón, sobre la verificación física "
        "en la estación de inserción, y sobre AMEF, capacitación/inducción o certificación para "
        "operar la estación. No se registra en las fuentes lote de terminal ni aplicador.",
        "NCR",
    ),
    "cuanto": h(
        "Piezas afectadas por este hallazgo: sin dato en las fuentes. Los datos T1 corresponden a "
        "defectos de toda la línea L1 y no se usan como cantidad del hallazgo.",
        "NCR",
    ),
}


# --------------------------------------------------------------------------- anclas


def test_card_without_case_data_is_flagged():
    assert unanchored_causes(D4_V5) == ["RC-10"]


def test_cards_with_report_data_or_precedent_are_anchored():
    # RC-03 cita la NCR; RC-02 cita un resultado de datos y un 8D previo. El detector no mide si
    # ese dato es pertinente (T6 es de toda la línea): solo que la tarjeta no está vacía de caso.
    assert "RC-03" not in unanchored_causes(D4_V5)
    assert "RC-02" not in unanchored_causes(D4_V5)


def test_no_detection_cause_is_not_judged_on_case_data():
    d4 = {**D4_V5, "causas_ocurrencia": []}
    assert unanchored_causes(d4) == []


def test_unanchored_handles_missing_content():
    assert unanchored_causes(None) == []
    assert unanchored_causes({}) == []


# --------------------------------------------------------------------------- "sin dato"


def test_sin_dato_naming_a_cited_document_is_flagged():
    found = sin_dato_contradictions(D2_V5, D4_V5)
    assert [(c["campo"], c["documentos"]) for c in found] == [
        ("como", ["AMEF", "WI-INS-004"])
    ]


def test_sin_dato_about_missing_facts_is_not_flagged():
    d2 = {k: v for k, v in D2_V5.items() if k != "como"}
    # donde/cuando/por_que/cuanto dicen "sin dato" sobre hechos que de verdad faltan; el cuando
    # nombra la NCR en otra frase y la NCR no cuenta como documento.
    assert sin_dato_contradictions(d2, D4_V5) == []


def test_family_prefix_of_another_identifier_does_not_count():
    d2 = {**D2_V5, "como": h("Sin dato en las fuentes sobre el WI-INS-099.", "NCR")}
    assert sin_dato_contradictions(d2, D4_V5) == []


def test_corrected_como_passes():
    d2 = {
        **D2_V5,
        "como": h(
            "El WI-INS-004 solo pide verificación visual de la TPA. Sin dato en las fuentes sobre "
            "matriz de habilidades o certificación para operar la estación.",
            "NCR",
        ),
    }
    assert sin_dato_contradictions(d2, D4_V5) == []


def test_sin_dato_without_d2_or_d4():
    assert sin_dato_contradictions(None, D4_V5) == []
    # Sin D4 solo cuentan los documentos que cita el propio D2; aquí cita únicamente la NCR.
    assert sin_dato_contradictions(D2_V5, None) == []


# --------------------------------------------------------------------------- cifras

SOURCES = [
    "codigo: NCR-2026-0012 linea: L1 turno: 3 parte: B3-FDH-0451 fecha_reporte: 2026-10-17",
    "INS-L1-02 22 (20.0%) INS-L1-01 18 (16.4%) B3-FDH-0451 49 (44.5%)",
    "LT-B-2609-15 29 (46.0%) LT-A-2609-15 23 (36.5%)",
    "Inducción en estación de 4 horas con el líder de línea.",
    "prueba de jalón: 2 conectores por arnés, 5 arneses por turno",
    "APL-L1-02 165,602 ciclos = 66% del umbral de 250,000",
]


def test_numbers_ignore_identifiers_dates_and_markers():
    assert (
        numbers_in("8D-2026-019 LT-A-2609-15 C08 F12 T6 2026-10-17 8D (1) (2)") == set()
    )


def test_numbers_normalise_thousands_and_decimals():
    assert numbers_in("165,602 y 14,258 con 7.71 y 0.21 mm") == {
        "165602",
        "14258",
        "7.71",
        "0.21",
    }
    assert numbers_in("165602") == numbers_in("165,602")


def test_counts_in_parentheses_are_figures_but_list_markers_are_not():
    assert numbers_in("INS-L1-01 (23) e INS-L1-02 (22) (1) (2)") == {"23", "22"}
    assert numbers_in("lotes LT-B-2608-12, -13, -14 y LT-B-2608-12/13/14") == set()


def test_totals_and_percentages_computed_from_the_same_text_are_not_flagged():
    # Casos reales del eval dev: el modelo suma las filas de una tabla y calcula el porcentaje.
    texts = [
        "LT-A-2609-14 (66) y LT-A-2609-15 (37) concentran 103 de 171 defectos (60.2%).",
        "INS-L1-01 (23) e INS-L1-02 (22) concentran 45 de 201 defectos del rango.",
    ]
    sources = ["66 37 171 23 22 201"]
    assert ungrounded_numbers(texts, sources) == []


def test_a_total_with_no_terms_in_the_text_is_still_listed():
    # 120 sale de una tabla que el texto no reproduce: no se puede comprobar, se lista.
    assert ungrounded_numbers(["concentran 120 de 188 piezas"], ["188"]) == ["120"]


def test_figures_present_in_sources_are_grounded():
    texts = [
        "Defectos en INS-L1-02 (22) y INS-L1-01 (18); B3-FDH-0451 (49; 44.5%).",
        "Inducción de 4 horas; 5 arneses por turno y 2 conectores por arnés (F9, F7).",
        "APL-L1-02 acumula 165,602 ciclos = 66% del umbral de PM de 250,000.",
    ]
    assert ungrounded_numbers(texts, SOURCES) == []


def test_invented_or_derived_figures_are_listed():
    texts = [
        "Entre las dos estaciones suman 40 piezas, el 36.4% de los defectos.",
        "La tasa de la línea fue de 7.71 por mil.",
    ]
    assert ungrounded_numbers(texts, SOURCES) == ["7.71", "36.4", "40"]


# --------------------------------------------------------------------------- resumen


def test_diagnose_and_events_on_the_real_draft():
    found = diagnose(d2=D2_V5, d4=D4_V5, sources=SOURCES)
    assert found["unanchored_causes"] == ["RC-10"]
    assert [c["campo"] for c in found["sin_dato_contradictions"]] == ["como"]
    events = as_events(found)
    assert {e["stage"] for e in events} == {"consistencia"}
    assert [e["event"] for e in events][:2] == [
        "causa_sin_ancla",
        "sin_dato_contradictorio",
    ]
    assert events[0]["detail"] == "RC-10"
    assert events[1]["detail"] == "como: AMEF, WI-INS-004"


def test_clean_draft_produces_no_events():
    d4 = {**D4_V5, "causas_ocurrencia": D4_V5["causas_ocurrencia"][:2]}
    d2 = {k: v for k, v in D2_V5.items() if k != "como"} | {
        "como": h(
            "El reporte consigna que no se recibió la instrucción de jalón.", "NCR"
        )
    }
    found = diagnose(d2=d2, d4=d4, sources=SOURCES)
    assert as_events(found) == []


# --------------------------------------------------------------------------- integración


class _Book:
    def __init__(self, *bodies: str) -> None:
        self._items = [SimpleNamespace(body=b) for b in bodies]

    def all(self):
        return self._items


NCR = SimpleNamespace(
    code="NCR-2026-0012",
    line_id="L1",
    shift=3,
    part_number="B3-FDH-0451",
    customer_id="KES",
    created_at=datetime(2026, 10, 17, 17, 14, tzinfo=UTC),
    description="Terminal no asentada en conector C08 en L1 T3.",
)


def test_service_events_report_without_touching_the_draft():
    final = {
        "d2": None,
        "d4": D4_V5,
        "prior": {"D2": SimpleNamespace(kind="borrador", content=D2_V5)},
        "book": _Book(*SOURCES),
    }
    events = _diagnostic_events(NCR, final)
    assert [e["event"] for e in events] == [
        "causa_sin_ancla",
        "sin_dato_contradictorio",
    ]
    assert events[0]["detail"] == "RC-10"
    # El D2 rechazado no se hereda: sin D2 vigente no hay contradicción que medir.
    final["prior"] = {"D2": SimpleNamespace(kind="rechazo", content=D2_V5)}
    assert [e["event"] for e in _diagnostic_events(NCR, final)] == ["causa_sin_ancla"]


def test_service_events_never_break_a_run():
    assert _diagnostic_events(NCR, {"d2": None, "d4": None}) == []
    assert _diagnostic_events(None, {"d2": None, "d4": D4_V5, "book": _Book()}) == []


def test_eval_diagnostics_need_stored_evidence():
    record = SimpleNamespace(evidence={"F1": {"texto": SOURCES[1]}})
    found = consistency_diagnostics(D4_V5, record, NCR)
    assert found["unanchored_causes"] == ["RC-10"]
    assert consistency_diagnostics(D4_V5, SimpleNamespace(evidence={}), NCR) == {}
    assert consistency_diagnostics(None, record, NCR) == {}
