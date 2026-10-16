"""Episodios causales: la verdad de fondo del dataset.

Este archivo NO se indexa ni se expone al agente. Los episodios H* tienen 8D cerrado en el
corpus (casos históricos). Los episodios E* existen solo en los datos estructurados y en
NCRs sin causa determinada; sus casos de evaluación prueban si el agente llega a la causa.
Los episodios N* son ruido con 8D propio (causas distintas a los 5 escenarios).
"""

from datetime import date

EPISODIOS = {
    # --- Históricos con 8D cerrado en el corpus ---
    "H1": {
        "escenario": "RC-01", "nd": "ND-01", "tipo": "historico", "ocho_d": "8D-2026-011",
        "linea": ["L1"], "aplicador": "APL-L1-02",
        "descripcion": "Desgaste de aplicador APL-L1-02 con PM reprogramado 3 veces",
        "pm_ultimo": date(2026, 3, 29), "pm_correctivo": date(2026, 5, 2),
    },
    "H2": {
        "escenario": "RC-02", "nd": "ND-02", "tipo": "historico", "ocho_d": "8D-2026-019",
        "linea": ["L1", "L2"], "familia": "A", "proveedor": "PRV-02",
        "recepcion": date(2026, 5, 28), "consumo": (date(2026, 6, 1), date(2026, 6, 19)),
        "descripcion": "Lote de TRM-A-1064 de Conexa con lanza de retención deformada",
    },
    "H3": {
        "escenario": "RC-04", "nd": "ND-04", "tipo": "historico", "ocho_d": "8D-2026-024",
        "linea": ["L1"], "maquina": "CUT-L1-01", "cable": "WIR-050",
        "ventana": (date(2026, 7, 6), date(2026, 7, 14)), "correccion": date(2026, 7, 15),
        "descripcion": "Receta R-050 migrada con longitud de desforre de la hoja impresa obsoleta",
    },
    # --- Episodios de evaluación (sin 8D en el corpus) ---
    "E6": {
        "escenario": "RC-01", "nd": "ND-01", "nd_alternas": ["ND-07"], "tipo": "evaluacion",
        "recurrente_de": "8D-2026-011",
        "linea": ["L2"], "aplicador": "APL-L2-01",
        "pm_ultimo": date(2026, 8, 16),
        "descripcion": "Desgaste de APL-L2-01; PM reprogramado; el bloqueo por ciclos del 8D-2026-011 no se extendió a L2",
    },
    "E7": {
        "escenario": "RC-02", "nd": "ND-02", "tipo": "evaluacion", "recurrente_de": "8D-2026-019",
        "linea": ["L1", "L2"], "familia": "B", "proveedor": "PRV-02",
        "recepcion": date(2026, 9, 9), "consumo": (date(2026, 9, 11), date(2026, 9, 26)),
        "descripcion": "Lote de TRM-B-2150 de Conexa; el muestreo reforzado del 8D-2026-019 solo cubrió TRM-A-1064",
    },
    "E8": {
        "escenario": "RC-03", "nd": "ND-03", "nd_alternas": ["ND-07"], "tipo": "evaluacion",
        "recurrente_de": None,
        "linea": ["L1"], "estacion": "INS-L1-02", "turno": "T3",
        "ventana": (date(2026, 8, 4), date(2026, 8, 29)),
        "descripcion": "Operadores de nuevo ingreso en INS-L1-02 T3; la WI no exige prueba de empuje-jalón",
    },
    "E9": {
        "escenario": "RC-04", "nd": "ND-04", "tipo": "evaluacion", "recurrente_de": "8D-2026-024",
        "linea": ["L2"], "maquina": "CUT-L2-01", "cable": "WIR-050",
        "ventana": (date(2026, 8, 10), date(2026, 8, 18)), "correccion": date(2026, 8, 19),
        "descripcion": "Misma migración de receta en CUT-L2-01; la acción D7 del 8D-2026-024 vencía el 28 de agosto",
    },
    "E10": {
        "escenario": "RC-05", "nd": "ND-05", "tipo": "evaluacion", "recurrente_de": None,
        "linea": ["L1", "L2"], "variante": "Alta", "ecn": "ECN-2026-031",
        "ventana": (date(2026, 8, 24), date(2026, 9, 10)), "correccion": date(2026, 9, 11),
        "descripcion": "ECN-2026-031 efectivo sin plantillas de tablero ni programa de prueba actualizados",
    },
    # --- Ruido con 8D propio ---
    "N1": {
        "escenario": "RC-14", "nd": "ND-06", "tipo": "ruido", "ocho_d": "8D-2026-013",
        "linea": ["L2"], "defecto": "DEF-10", "numero_parte": "B3-FDH-0451",
        "ventana": (date(2026, 5, 4), date(2026, 5, 11)),
        "descripcion": "Plantilla de etiqueta obsoleta en impresora de EMP-L2",
    },
    "N2": {
        "escenario": "RC-12", "nd": "ND-02", "tipo": "ruido", "ocho_d": "8D-2026-021",
        "linea": ["L1"], "defecto": "DEF-09",
        "ventana": (date(2026, 6, 22), date(2026, 7, 3)),
        "descripcion": "Lote de cinta con adhesión baja",
    },
    "N3": {
        "escenario": "RC-15", "nd": "ND-08", "tipo": "ruido", "ocho_d": "8D-2026-027",
        "linea": ["L2"], "defecto": "DEF-08",
        "ventana": (date(2026, 8, 17), date(2026, 8, 24)),
        "descripcion": "Guía de tablero BRD-L2 con borde filoso por desgaste",
    },
}
