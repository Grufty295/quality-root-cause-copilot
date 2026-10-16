"""Catálogos y parámetros de la planta ficticia.

Todo nombre de cliente, proveedor, persona y número de parte es inventado.
Los valores numéricos son supuestos de modelado, no datos de industria.
"""

from datetime import date

SEED = 42
START = date(2026, 4, 1)
END = date(2026, 9, 30)

PLANTA = "Cablenova México, planta Juárez"
LINEAS = ["L1", "L2"]
TURNOS = ["T1", "T2", "T3"]  # T1 06-14, T2 14-22, T3 22-06 (fecha = inicio de turno)

CLIENTES = {
    "NOR": {"nombre": "Norvane Motors", "tipo": "OEM", "confidencialidad": "confidencial"},
    "KES": {"nombre": "Kestrel Modules", "tipo": "Tier 1", "confidencialidad": "interno"},
}

# Arneses: mezcla de producción, terminales por familia y cables usados.
ARNESES = {
    "B3-FDH-0451": {"variante": "Base", "cliente": "KES", "mezcla": 0.40, "term_A": 26, "term_B": 6,
                    "cables": ["WIR-050", "WIR-075", "WIR-100"]},
    "A7-DRH-2210-M": {"variante": "Media", "cliente": "NOR", "mezcla": 0.35, "term_A": 32, "term_B": 8,
                      "cables": ["WIR-035", "WIR-075", "WIR-100"]},
    "A7-DRH-2210-H": {"variante": "Alta", "cliente": "NOR", "mezcla": 0.25, "term_A": 38, "term_B": 10,
                      "cables": ["WIR-035", "WIR-075", "WIR-100"]},
}

TERMINALES = {
    "TRM-A-1064": {"familia": "A", "descripcion": "Terminal hembra 0.64 mm, estañada"},
    "TRM-B-2150": {"familia": "B", "descripcion": "Terminal hembra 1.5 mm, estañada"},
}
TERMINAL_POR_FAMILIA = {"A": "TRM-A-1064", "B": "TRM-B-2150"}

CABLES = {
    "WIR-035": {"seccion": 0.35, "familia": "A"},
    "WIR-050": {"seccion": 0.50, "familia": "A"},
    "WIR-075": {"seccion": 0.75, "familia": "B"},
    "WIR-100": {"seccion": 1.00, "familia": "B"},
}

PROVEEDORES = {
    "PRV-01": {"nombre": "Vértice Conectores", "categoria": "A"},
    "PRV-02": {"nombre": "Conexa Terminales", "categoria": "A"},
}


def aplicadores(linea):
    """Aplicadores 01-02 familia A, 03-04 familia B. Prensa 01 aloja 01 y 03, prensa 02 aloja 02 y 04."""
    return {
        f"APL-{linea}-01": {"familia": "A", "prensa": f"PRS-{linea}-01"},
        f"APL-{linea}-02": {"familia": "A", "prensa": f"PRS-{linea}-02"},
        f"APL-{linea}-03": {"familia": "B", "prensa": f"PRS-{linea}-01"},
        f"APL-{linea}-04": {"familia": "B", "prensa": f"PRS-{linea}-02"},
    }


APLICADORES = {k: {**v, "linea": ln} for ln in LINEAS for k, v in aplicadores(ln).items()}

# Combinación de referencia del plan de control por familia de aplicador (SPEC-CRP-001 rev E).
SPEC_CRIMPADO = {
    "A": {"combinacion": "TRM-A-1064 / WIR-035", "nominal": 0.80, "lsl": 0.76, "usl": 0.84,
          "traccion_min": 50.0, "traccion_base": 62.0},
    "B": {"combinacion": "TRM-B-2150 / WIR-100", "nominal": 1.35, "lsl": 1.30, "usl": 1.40,
          "traccion_min": 140.0, "traccion_base": 165.0},
}

UMBRAL_PM_CICLOS = 250_000
CICLOS_INICIO_DESGASTE = 300_000   # supuesto: la deriva empieza después de este punto
DERIVA_MM_POR_100K = 0.010         # supuesto: ~0.03 mm a 600k ciclos

# Catálogo de defectos: tasa base por línea-turno (eventos), estación de origen y punto de detección.
DEFECTOS = {
    "DEF-01": {"descripcion": "Falso contacto intermitente", "tasa": 0.10, "origen": "CRP",
               "deteccion": {"AUD": 0.45, "CLIENTE": 0.35, "INF": 0.20}},
    "DEF-02": {"descripcion": "Alta resistencia de contacto", "tasa": 0.12, "origen": "CRP",
               "deteccion": {"TST": 0.6, "AUD": 0.4}},
    "DEF-03": {"descripcion": "Circuito abierto", "tasa": 0.22, "origen": "INS",
               "deteccion": {"TST": 0.9, "CLIENTE": 0.1}},
    "DEF-04": {"descripcion": "Terminal no asentada o retraída (back-out)", "tasa": 0.12, "origen": "INS",
               "deteccion": {"INF": 0.7, "CLIENTE": 0.3}},
    "DEF-05": {"descripcion": "Altura de crimpado fuera de especificación", "tasa": 0.10, "origen": "CRP",
               "deteccion": {"CRP": 1.0}},
    "DEF-06": {"descripcion": "Aislamiento atrapado en barril conductor", "tasa": 0.04, "origen": "CUT",
               "deteccion": {"LAB": 0.6, "AUD": 0.4}},
    "DEF-07": {"descripcion": "Ruteo incorrecto o conector fuera de posición", "tasa": 0.05, "origen": "BRD",
               "deteccion": {"INF": 0.7, "CLIENTE": 0.3}},
    "DEF-08": {"descripcion": "Daño de aislamiento", "tasa": 0.25, "origen": "BRD",
               "deteccion": {"INF": 0.8, "TST": 0.2}},
    "DEF-09": {"descripcion": "Encintado deficiente", "tasa": 0.30, "origen": "BRD",
               "deteccion": {"INF": 1.0}},
    "DEF-10": {"descripcion": "Etiqueta incorrecta", "tasa": 0.06, "origen": "EMP",
               "deteccion": {"INF": 0.7, "CLIENTE": 0.3}},
    "DEF-11": {"descripcion": "Longitud de ramal fuera de especificación", "tasa": 0.18, "origen": "BRD",
               "deteccion": {"INF": 1.0}},
    "DEF-12": {"descripcion": "Clip o abrazadera faltante", "tasa": 0.18, "origen": "BRD",
               "deteccion": {"INF": 0.85, "CLIENTE": 0.15}},
}

PUNTOS_DETECCION = {
    "CRP": "Verificación en crimpado",
    "LAB": "Laboratorio (corte transversal)",
    "TST": "Prueba eléctrica",
    "INF": "Inspección final",
    "AUD": "Auditoría de producto",
    "CLIENTE": "Cliente",
}

# Usuarios simulados de la demo (sin nombres reales; el alcance es por línea).
USUARIOS = [
    {"usuario_id": "u-insp-l1", "rol": "inspector", "lineas": ["L1"]},
    {"usuario_id": "u-insp-l2", "rol": "inspector", "lineas": ["L2"]},
    {"usuario_id": "u-ingcal-1", "rol": "ingeniero_calidad", "lineas": ["L1", "L2"]},
    {"usuario_id": "u-ingcal-2", "rol": "ingeniero_calidad", "lineas": ["L1", "L2"]},
    {"usuario_id": "u-gercal", "rol": "gerente_calidad", "lineas": ["L1", "L2"]},
    {"usuario_id": "u-auditor", "rol": "auditor", "lineas": ["L1", "L2"]},
]

# Nombres ficticios para campos "reportado por" y equipos 8D (prueban la seudonimización).
NOMBRES_PILA = ["Rosa María", "Juan Carlos", "Héctor", "Lucía", "Ramón", "Ana Karen", "Óscar", "Daniela",
                "Miguel Ángel", "Patricia", "Jorge", "Verónica", "Luis Fernando", "Claudia", "Ernesto", "Sandra",
                "Ricardo", "Mónica", "Arturo", "Leticia", "Gabriela", "Fernando", "Alejandra", "Raúl"]
APELLIDOS = ["Delgado", "Ibarra", "Salas", "Contreras", "Villalobos", "Mendoza", "Treviño", "Fuentes", "Rivas",
             "Lozano", "Arellano", "Esparza", "Gallegos", "Peña", "Quiñones", "Olivas", "Bustillos", "Zubiría",
             "Cázares", "Holguín", "Carrasco", "Chávez", "Loya", "Terrazas"]
