"""NCRs históricas y reportes 8D generados a partir de los datos estructurados.

Las cifras de cada NCR y de cada 8D se calculan de los eventos generados, para que el
corpus y los datos que consultan las tools no se contradigan.
"""

import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from statistics import mean

import config as C
from episodios import EPISODIOS as EP

PATRON_CONFIDENCIAL = re.compile(r"Norvane|A7[-\s]?DRH|Halc[oó]n", re.IGNORECASE)
PUNTO = C.PUNTOS_DETECCION


def clasificar(texto):
    return "confidencial" if PATRON_CONFIDENCIAL.search(texto) else "interno"


def front_matter(meta):
    lineas = []
    for k, v in meta.items():
        if isinstance(v, list):
            v = "[" + ", ".join(str(x) for x in v) + "]"
        elif isinstance(v, bool):
            v = "true" if v else "false"
        lineas.append(f"{k}: {v}")
    return "---\n" + "\n".join(lineas) + "\n---\n\n"


def fmt_fecha(iso):
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
             "octubre", "noviembre", "diciembre"]
    d = date.fromisoformat(iso) if isinstance(iso, str) else iso
    return f"{d.day} de {meses[d.month - 1]} de {d.year}"


class Documentos:
    def __init__(self, mundo):
        self.m = mundo
        self.rng = mundo.rng
        self.ncrs = []
        self.ochod = {}       # doc_id -> (meta, texto)
        self._personas = {}

    # ------------------------------------------------------------------ utilidades
    def persona(self, clave):
        """Nombre ficticio único y estable por clave (prueba la seudonimización de PII)."""
        if clave not in self._personas:
            usados = {v.split(" (#")[0] for v in self._personas.values()}
            while True:
                nombre = f"{self.rng.choice(C.NOMBRES_PILA)} {self.rng.choice(C.APELLIDOS)}"
                if nombre not in usados:
                    break
            self._personas[clave] = f"{nombre} (#{self.rng.randint(40000, 69999)})"
        return self._personas[clave]

    def eventos(self, ep=None, **filtros):
        out = []
        for e in self.m.eventos:
            if ep is not None and e["_episodio"] != ep:
                continue
            if all((e[k] in v) if isinstance(v, (list, tuple, set)) else e[k] == v for k, v in filtros.items()):
                out.append(e)
        return out

    def piezas(self, evs):
        return sum(e["cantidad"] for e in evs)

    def cantidad_ncr(self, ep, fecha, det, lineas, codigos=None, minimo=1):
        a = (date.fromisoformat(fecha) - timedelta(days=1)).isoformat()
        evs = [e for e in self.m.eventos if e["_episodio"] == ep and a <= e["fecha_deteccion"] <= fecha
               and e["detectado_en"] == det and e["linea"] in lineas
               and (codigos is None or e["defecto_codigo"] in codigos)]
        return max(minimo, self.piezas(evs))

    # ------------------------------------------------------------------ NCRs
    def _ncr(self, fecha, linea, turno, det, codigo, pn, cantidad, descripcion, contencion, disposicion,
             causa, estado, ocho_d="", episodio="", cliente_reporta=False):
        arn = C.ARNESES[pn] if pn in C.ARNESES else None
        cliente = C.CLIENTES[arn["cliente"]]["nombre"] if arn else ""
        texto_total = " ".join([descripcion, contencion, causa, cliente, pn])
        self.ncrs.append({
            "fecha": fecha, "linea": linea, "turno": turno, "detectado_en": PUNTO[det],
            "origen": "Cliente" if det == "CLIENTE" else "Interno", "cliente": cliente,
            "numero_parte": pn, "variante": arn["variante"] if arn else "", "defecto_codigo": codigo,
            "defecto": C.DEFECTOS[codigo]["descripcion"], "cantidad": cantidad, "descripcion": descripcion,
            "contencion": contencion, "disposicion": disposicion, "causa_preliminar": causa, "estado": estado,
            "ocho_d": ocho_d,
            "reportado_por": (self.persona(f"sqe-{cliente}") + ", SQE de cuenta") if cliente_reporta
            else self.persona(f"rep-{det}-{linea}-{len(self.ncrs) % 7}"),
            "confidencialidad": clasificar(texto_total), "_episodio": episodio,
        })

    def ncrs_escenarios(self):
        q = self.cantidad_ncr
        n = self._ncr
        # H1: RC-01 en APL-L1-02
        n("2026-04-23", "L1", "T2", "AUD", "DEF-01", "A7-DRH-2210-M", q("H1", "2026-04-23", "AUD", ["L1"]),
          f"Auditoría de producto con prueba dinámica: {q('H1', '2026-04-23', 'AUD', ['L1'])} arneses con intermitencia "
          "al mover el ramal del conector C08 (seguro eléctrico). Terminal TRM-A-1064. En prueba estática pasan.",
          "Producción del turno T2 de L1 retenida y re-auditada con prueba dinámica.", "Retrabajo: reemplazo de terminal",
          "En análisis", "Cerrada", "8D-2026-011", "H1")
        n("2026-04-28", "L1", "T1", "AUD", "DEF-01", "B3-FDH-0451", q("H1", "2026-04-28", "AUD", ["L1"]),
          f"Auditoría de producto: {q('H1', '2026-04-28', 'AUD', ['L1'])} arneses B3-FDH-0451 con intermitencia en "
          "circuitos de terminal TRM-A-1064 (conectores C05 y C11). Segunda NCR del mismo modo en la semana.",
          "Auditoría con prueba dinámica ampliada a 20 arneses por turno en L1.", "Retrabajo: reemplazo de terminal",
          "Posible crimpado marginal; se revisarán hojas de verificación de crimpado", "Cerrada", "8D-2026-011", "H1")
        n("2026-04-30", "L1", "T2", "TST", "DEF-02", "A7-DRH-2210-H", q("H1", "2026-04-30", "TST", ["L1"]),
          f"Prueba eléctrica rechaza {q('H1', '2026-04-30', 'TST', ['L1'])} arneses por resistencia sobre el umbral "
          "del programa en circuitos de TRM-A-1064. Lecturas de 14 a 22 mΩ contra máximo de 10 mΩ.",
          "Se separa el inventario de L1 fabricado desde el 23 de abril para prueba dinámica al 100%.",
          "Retrabajo: reemplazo de terminal", "Crimpado marginal; se abre 8D por repetición", "Cerrada",
          "8D-2026-011", "H1")
        n("2026-05-01", "L1", "T3", "INF", "DEF-01", "A7-DRH-2210-M", q("H1", "2026-05-01", "INF", ["L1"]),
          f"Inspección final: {q('H1', '2026-05-01', 'INF', ['L1'])} arneses con terminal TRM-A-1064 que muestra "
          "continuidad intermitente al manipular el conector C08.", "Contención según 8D-2026-011.",
          "Retrabajo: reemplazo de terminal", "Ver 8D-2026-011", "Cerrada", "8D-2026-011", "H1")
        n("2026-05-04", "L1", "", "CLIENTE", "DEF-01", "A7-DRH-2210-M", q("H1", "2026-05-06", "CLIENTE", ["L1"], minimo=3),
          "Reclamo de Norvane Motors: arneses A7-DRH-2210-M con falla intermitente del seguro eléctrico detectada en "
          "la prueba de fin de línea del cliente. Conector C08, terminal TRM-A-1064. Fabricación del 27 al 30 de abril, L1.",
          "Contención en tránsito y en almacén del cliente con prueba dinámica; ver 8D-2026-011.",
          "Reemplazo de arneses en cliente", "Ver 8D-2026-011", "Cerrada", "8D-2026-011", "H1",
          cliente_reporta=True)

        # H2: RC-02 lote de TRM-A-1064 de Conexa
        n("2026-06-01", "L2", "T1", "TST", "DEF-03", "A7-DRH-2210-H", q("H2", "2026-06-01", "TST", ["L2"]),
          f"Prueba eléctrica: {q('H2', '2026-06-01', 'TST', ['L2'])} arneses con circuito abierto; la terminal "
          "TRM-A-1064 se encontró retraída en el conector C14.", "Retrabajo en línea.",
          "Retrabajo: reinserción de terminal", "Inserción incompleta", "Cerrada", "8D-2026-019", "H2")
        n("2026-06-02", "L2", "T2", "INF", "DEF-04", "B3-FDH-0451", q("H2", "2026-06-02", "INF", ["L2"]),
          f"Inspección final, prueba de jalón: {q('H2', '2026-06-02', 'INF', ['L2'])} terminales TRM-A-1064 se "
          "retraen del conector al jalar con fuerza manual normal.",
          "Prueba de jalón ampliada a todos los conectores del turno.", "Retrabajo: reemplazo de terminal",
          "Inserción incompleta; retroalimentación a estaciones de inserción", "Cerrada", "8D-2026-019", "H2")
        n("2026-06-06", "L1, L2", "", "CLIENTE", "DEF-04", "A7-DRH-2210-M", q("H2", "2026-06-07", "CLIENTE", ["L1", "L2"], minimo=4),
          "Reclamo de Norvane Motors: terminales TRM-A-1064 que se salen del conector al conectar el arnés en la "
          "puerta; arneses de L1 y L2 fabricados la primera semana de junio.",
          "Inspección 100% con jalón en planta, en tránsito y en almacén del cliente.", "Reemplazo de arneses en cliente",
          "En análisis; se abre 8D-2026-019", "Cerrada", "8D-2026-019", "H2", cliente_reporta=True)
        n("2026-06-11", "L1, L2", "", "CLIENTE", "DEF-04", "B3-FDH-0451", q("H2", "2026-06-11", "CLIENTE", ["L1", "L2"], minimo=3),
          "Reclamo de Kestrel Modules: terminales retraídas en conectores del arnés B3-FDH-0451; terminal TRM-A-1064.",
          "Inspección 100% con jalón en almacén del cliente.", "Reemplazo de arneses en cliente", "Ver 8D-2026-019",
          "Cerrada", "8D-2026-019", "H2", cliente_reporta=True)
        n("2026-06-12", "L1", "T1", "INF", "DEF-04", "A7-DRH-2210-H", q("H2", "2026-06-12", "INF", ["L1"]),
          f"Inspección final: {q('H2', '2026-06-12', 'INF', ['L1'])} terminales TRM-A-1064 retraídas; la lanza de "
          "retención se observa aplanada en las piezas retiradas.", "Contención según 8D-2026-019.",
          "Retrabajo: reemplazo de terminal", "Posible problema de material; ver 8D-2026-019", "Cerrada",
          "8D-2026-019", "H2")

        # H3: RC-04 receta de corte en CUT-L1-01
        n("2026-07-06", "L1", "T2", "TST", "DEF-02", "B3-FDH-0451", q("H3", "2026-07-06", "TST", ["L1"]),
          f"Prueba eléctrica: {q('H3', '2026-07-06', 'TST', ['L1'])} arneses B3-FDH-0451 con resistencia alta en "
          "circuitos de cable WIR-050.", "Retrabajo en línea.", "Retrabajo: reemplazo de circuito",
          "En análisis", "Cerrada", "8D-2026-024", "H3")
        n("2026-07-07", "L1", "T1", "TST", "DEF-03", "B3-FDH-0451", q("H3", "2026-07-07", "TST", ["L1"]),
          f"Prueba eléctrica: {q('H3', '2026-07-07', 'TST', ['L1'])} arneses con circuito abierto en circuitos de "
          "WIR-050; el conductor se ve corto dentro del barril.", "Retrabajo en línea.",
          "Retrabajo: reemplazo de circuito", "Posible crimpado incompleto", "Cerrada", "8D-2026-024", "H3")
        n("2026-07-11", "L1", "", "LAB", "DEF-06", "B3-FDH-0451", q("H3", "2026-07-11", "LAB", ["L1"]),
          "Corte transversal semanal: muestra de TRM-A-1064 con WIR-050 presenta aislamiento atrapado en el barril "
          "conductor y longitud de hebras expuestas menor a la especificada.",
          "Se retiene producción de circuitos WIR-050 de L1 desde la última muestra conforme.",
          "Retrabajo de circuitos WIR-050 retenidos", "Ver 8D-2026-024", "Cerrada", "8D-2026-024", "H3")
        n("2026-07-13", "L1", "T3", "TST", "DEF-02", "B3-FDH-0451", q("H3", "2026-07-13", "TST", ["L1"]),
          f"Prueba eléctrica: {q('H3', '2026-07-13', 'TST', ['L1'])} arneses B3-FDH-0451 con resistencia alta en "
          "circuitos WIR-050; continúa la tendencia de la semana.", "Contención según 8D-2026-024.",
          "Retrabajo: reemplazo de circuito", "Ver 8D-2026-024", "Cerrada", "8D-2026-024", "H3")

        # N1, N2, N3: ruido con 8D propio
        n("2026-05-05", "L2", "T1", "INF", "DEF-10", "B3-FDH-0451", q("N1", "2026-05-05", "INF", ["L2"]),
          f"Inspección final: {q('N1', '2026-05-05', 'INF', ['L2'])} arneses B3-FDH-0451 con etiqueta que muestra "
          "la revisión C del dibujo en lugar de la revisión D.", "Re-etiquetado del inventario de L2.",
          "Re-etiquetado", "Plantilla de etiqueta incorrecta", "Cerrada", "8D-2026-013", "N1")
        n("2026-05-08", "L2", "", "CLIENTE", "DEF-10", "B3-FDH-0451", 1,
          "Reclamo de Kestrel Modules: caja con arneses B3-FDH-0451 etiquetados con revisión anterior; el sistema "
          "de recibo del cliente rechazó la caja.", "Re-etiquetado en almacén del cliente.", "Re-etiquetado",
          "Ver 8D-2026-013", "Cerrada", "8D-2026-013", "N1", cliente_reporta=True)
        n("2026-06-22", "L1", "T1", "INF", "DEF-09", "A7-DRH-2210-M", q("N2", "2026-06-22", "INF", ["L1"]),
          f"Inspección final: {q('N2', '2026-06-22', 'INF', ['L1'])} arneses con cinta desprendida en el ramal "
          "principal a pocas horas de encintados.", "Re-encintado.", "Retrabajo: re-encintado",
          "Técnica de encintado", "Cerrada", "8D-2026-021", "N2")
        n("2026-06-23", "L1", "T2", "INF", "DEF-09", "A7-DRH-2210-H", q("N2", "2026-06-23", "INF", ["L1"]),
          f"Inspección final: {q('N2', '2026-06-23', 'INF', ['L1'])} arneses con encintado desprendido en varios "
          "ramales, en los tres turnos.", "Re-encintado; se revisa el lote de cinta en uso.",
          "Retrabajo: re-encintado", "Posible lote de cinta; ver 8D-2026-021", "Cerrada", "8D-2026-021", "N2")
        n("2026-08-19", "L2", "T2", "INF", "DEF-08", "B3-FDH-0451", q("N3", "2026-08-19", "INF", ["L2"]),
          f"Inspección final: {q('N3', '2026-08-19', 'INF', ['L2'])} arneses con aislamiento raspado en el ramal "
          "principal, siempre en la misma zona del arnés.", "Inspección 100% del ramal principal en L2.",
          "Retrabajo: reemplazo de circuito", "Daño en ensamble", "Cerrada", "8D-2026-027", "N3")
        n("2026-08-20", "L2", "T1", "TST", "DEF-08", "A7-DRH-2210-M", q("N3", "2026-08-20", "TST", ["L2"]),
          "Prueba eléctrica detecta corto entre circuitos del ramal principal por aislamiento cortado.",
          "Contención según 8D-2026-027.", "Retrabajo: reemplazo de circuitos", "Ver 8D-2026-027", "Cerrada",
          "8D-2026-027", "N3")

        # Episodios de evaluación: NCRs sin causa determinada (no tienen 8D en el corpus)
        n("2026-09-14", "L2", "T1", "AUD", "DEF-01", "A7-DRH-2210-H", q("E6", "2026-09-14", "AUD", ["L2"]),
          "Auditoría de producto con prueba dinámica: arnés con intermitencia en circuito de terminal TRM-A-1064, "
          "conector C11 (ventana).", "Re-auditoría de 10 arneses del turno sin hallazgos adicionales.",
          "Retrabajo: reemplazo de terminal", "No determinada; evento aislado", "Cerrada", "", "E6")
        n("2026-09-17", "L2", "T2", "TST", "DEF-02", "B3-FDH-0451", q("E6", "2026-09-17", "TST", ["L2"]),
          f"Prueba eléctrica: {q('E6', '2026-09-17', 'TST', ['L2'])} arneses con resistencia sobre el umbral en "
          "circuitos de TRM-A-1064.", "Retrabajo en línea.", "Retrabajo: reemplazo de terminal",
          "No determinada", "En análisis", "", "E6")
        n("2026-09-21", "L2", "T3", "AUD", "DEF-01", "A7-DRH-2210-M", q("E6", "2026-09-21", "AUD", ["L2"]),
          f"Auditoría de producto: {q('E6', '2026-09-21', 'AUD', ['L2'])} arneses con intermitencia en prueba dinámica, "
          "circuitos de TRM-A-1064 en conectores C05 y C08.",
          "Auditoría ampliada a 15 arneses por turno en L2.", "Retrabajo: reemplazo de terminal",
          "En análisis", "En análisis", "", "E6")
        n("2026-09-14", "L1", "T2", "INF", "DEF-04", "B3-FDH-0451", q("E7", "2026-09-14", "INF", ["L1"]),
          f"Inspección final, prueba de jalón: {q('E7', '2026-09-14', 'INF', ['L1'])} terminales TRM-B-2150 se "
          "retraen del conector C21 (motor de ventana).", "Prueba de jalón ampliada en L1.",
          "Retrabajo: reemplazo de terminal", "Inserción incompleta", "Cerrada", "", "E7")
        n("2026-09-25", "L1, L2", "", "CLIENTE", "DEF-04", "A7-DRH-2210-M", q("E7", "2026-09-25", "CLIENTE", ["L1", "L2"], minimo=3),
          "Reclamo de Norvane Motors: terminal TRM-B-2150 del conector C21 se sale al conectar el motor de ventana. "
          "Arneses de L1 y L2.", "Inspección con jalón en almacén del cliente.", "Reemplazo de arneses en cliente",
          "En análisis", "Abierta", "", "E7", cliente_reporta=True)
        n("2026-08-05", "L1", "T3", "TST", "DEF-03", "B3-FDH-0451", q("E8", "2026-08-05", "TST", ["L1"]),
          f"Prueba eléctrica, turno T3: {q('E8', '2026-08-05', 'TST', ['L1'])} arneses con circuito abierto; las "
          "terminales salen al jalar ligeramente el cable.", "Retrabajo en línea.",
          "Retrabajo: reinserción de terminal", "Inserción incompleta; se retroalimentó a la estación", "Cerrada",
          "", "E8")
        n("2026-08-17", "L1", "T3", "INF", "DEF-04", "A7-DRH-2210-H", q("E8", "2026-08-17", "INF", ["L1"]),
          "Inspección final: TPA en posición de preensamble en conector C05; terminal parcialmente asentada.",
          "Revisión de TPA en el inventario del turno.", "Retrabajo: reinserción y cierre de TPA",
          "Cierre incompleto de TPA", "Cerrada", "", "E8")
        n("2026-08-11", "L2", "T1", "TST", "DEF-02", "B3-FDH-0451", q("E9", "2026-08-11", "TST", ["L2"]),
          f"Prueba eléctrica: {q('E9', '2026-08-11', 'TST', ['L2'])} arneses B3-FDH-0451 con resistencia alta en "
          "circuitos de cable WIR-050.", "Retrabajo en línea.", "Retrabajo: reemplazo de circuito",
          "No determinada", "Cerrada", "", "E9")
        n("2026-08-31", "L1, L2", "", "CLIENTE", "DEF-07", "A7-DRH-2210-H", q("E10", "2026-08-31", "CLIENTE", ["L1", "L2"], minimo=3),
          "Reclamo de Norvane Motors: en algunas puertas el conector C14 (bocina) no alcanza su punto de montaje; "
          "el ramal llega corto. Variante A7-DRH-2210-H.", "Inspección dimensional de ramal C14 en inventario.",
          "En revisión con el cliente", "En análisis", "Abierta", "", "E10", cliente_reporta=True)
        n("2026-09-04", "L2", "T1", "AUD", "DEF-07", "A7-DRH-2210-H", q("E10", "2026-09-04", "AUD", ["L2"]),
          "Auditoría de producto: ramal del conector C14 en posición distinta a la del dibujo de cliente vigente.",
          "Retención de variante Alta en L2 para revisión dimensional.", "Retrabajo de ruteo",
          "En análisis", "En análisis", "", "E10")

    def ncrs_ruido(self, objetivo=50):
        rng = self.rng
        ventanas = []
        for clave, ep in EP.items():
            if "ventana" in ep:
                a, b = ep["ventana"]
            elif "consumo" in ep:
                a, b = ep["consumo"]
            else:
                evs = self.eventos(clave)
                a = date.fromisoformat(min(e["fecha_fabricacion"] for e in evs))
                b = date.fromisoformat(max(e["fecha_fabricacion"] for e in evs))
            ventanas.append((a - timedelta(days=5), b + timedelta(days=12), set(ep["linea"])))
        grupos = defaultdict(list)
        for e in self.m.eventos:
            if e["_episodio"]:
                continue
            if e["detectado_en"] not in ("INF", "TST", "AUD", "CLIENTE", "CRP", "LAB"):
                continue
            d = date.fromisoformat(e["fecha_deteccion"])
            if d > C.END:
                continue
            if e["defecto_codigo"] in ("DEF-01", "DEF-02", "DEF-03", "DEF-04", "DEF-06", "DEF-07"):
                if any(a <= d <= b and e["linea"] in lns for a, b, lns in ventanas):
                    continue
            grupos[(e["fecha_deteccion"], e["linea"], e["defecto_codigo"], e["detectado_en"])].append(e)
        pesos = {"DEF-01": 1, "DEF-02": 2, "DEF-03": 5, "DEF-04": 3, "DEF-05": 5, "DEF-06": 1, "DEF-07": 1,
                 "DEF-08": 8, "DEF-09": 8, "DEF-10": 2, "DEF-11": 7, "DEF-12": 7}
        claves = sorted(grupos)
        rng.shuffle(claves)
        por_mes = Counter()
        elegidos = []
        cuota = Counter()
        orden = sorted(claves, key=lambda k: -pesos[k[2]] * rng.random())
        for holgura in (0, 2):
            for k in orden:
                if len(elegidos) >= objetivo:
                    break
                mes = k[0][:7]
                if k in elegidos or por_mes[mes] >= objetivo // 6 + 1 + holgura or cuota[k[2]] >= pesos[k[2]] + holgura:
                    continue
                elegidos.append(k)
                por_mes[mes] += 1
                cuota[k[2]] += 1
        conectores_a = ["C05 (espejo)", "C08 (seguro eléctrico)", "C11 (ventana)", "C14 (bocina)"]
        conectores_b = ["C21 (motor de ventana)", "C02 (alimentación)"]
        ramales = ["principal", "de espejo", "de bocina", "de cerradura", "de ventana"]
        for k in sorted(elegidos):
            evs = grupos[k]
            e = evs[0]
            qty = self.piezas(evs)
            cod, det, ln = e["defecto_codigo"], e["detectado_en"], e["linea"]
            con = rng.choice(conectores_a if e["numero_parte_terminal"] != "TRM-B-2150" else conectores_b)
            ram = rng.choice(ramales)
            t = {
                "DEF-01": (f"Intermitencia en prueba dinámica en el conector {con}.", "Retrabajo de la terminal.",
                           "Evento aislado"),
                "DEF-02": (f"Resistencia sobre el umbral en un circuito del conector {con}.", "Retrabajo en línea.",
                           "Terminal con residuo de lubricante; evento aislado"),
                "DEF-03": (f"Circuito abierto en el conector {con}; terminal no insertada.", "Retrabajo en línea.",
                           rng.choice(["Inserción incompleta", "Terminal omitida en la secuencia"])),
                "DEF-04": (f"Terminal retraída en el conector {con} durante la prueba de jalón.", "Retrabajo en línea.",
                           "Inserción incompleta"),
                "DEF-05": (f"Altura de crimpado fuera de especificación en verificación de inicio de turno, "
                           f"aplicador {e['aplicador_id']}.", "Ajuste de altura de cierre y re-verificación.",
                           "Ajuste de altura de cierre en setup"),
                "DEF-06": ("Corte transversal semanal: una muestra con aislamiento en el barril conductor.",
                           "Re-muestreo de 5 piezas conforme.", "Evento aislado; posición del cable en el aplicador"),
                "DEF-07": (f"Conector {con} fuera de posición en el tablero.", "Corrección en estación.",
                           "Conector colocado en la posición de otra variante"),
                "DEF-08": (f"Aislamiento raspado en el ramal {ram}.", "Retrabajo: reemplazo de circuito.",
                           rng.choice(["Manejo del arnés al retirarlo del tablero", "Roce con carro de transporte"])),
                "DEF-09": (f"Encintado flojo en el ramal {ram}; traslape menor al 50%.", "Re-encintado.",
                           "Técnica de encintado"),
                "DEF-10": ("Etiqueta con impresión ilegible; el escáner no la lee.", "Re-etiquetado.",
                           "Cabezal de impresora sucio"),
                "DEF-11": (f"Longitud del ramal {ram} fuera de tolerancia ({rng.choice([8, 12, 15, 18])} mm sobre el "
                           "nominal).", "Retrabajo de ramal.", "Arnés movido en el tablero durante el encintado"),
                "DEF-12": (f"Clip faltante en el ramal {ram}.", "Colocación de clip en inspección.",
                           "Omisión en la estación de tablero"),
            }[cod]
            prefijo = {"CLIENTE": "Reclamo de cliente: ", "AUD": "Auditoría de producto: ", "TST": "Prueba eléctrica: ",
                       "INF": "Inspección final: ", "CRP": "Verificación de crimpado: ", "LAB": ""}[det]
            desc = f"{prefijo}{qty} {'arnés' if qty == 1 else 'arneses'}. {t[0]}"
            if det == "CLIENTE":
                desc = (f"Reclamo de {e['cliente']}: {qty} {'arnés' if qty == 1 else 'arneses'} "
                        f"{e['numero_parte']}. {t[0]}")
            self._ncr(e["fecha_deteccion"], ln, "" if det == "CLIENTE" else e["turno"], det, cod, e["numero_parte"], qty,
                      desc, t[1], "Retrabajo" if det != "CLIENTE" else "Reemplazo en cliente", t[2],
                      "Cerrada", cliente_reporta=(det == "CLIENTE"))

    def numerar_ncrs(self):
        self.ncrs.sort(key=lambda r: (r["fecha"], r["linea"], r["defecto_codigo"]))
        for i, r in enumerate(self.ncrs, 1):
            r["ncr_id"] = f"NCR-2026-{i:04d}"
        # referencias cruzadas que se usan en los 8D
        self.ncr_por_ep = defaultdict(list)
        for r in self.ncrs:
            if r["_episodio"]:
                self.ncr_por_ep[r["_episodio"]].append(r["ncr_id"])

    def ncr_markdown(self, r):
        lineas = [x.strip() for x in r["linea"].split(",")]
        meta = {
            "doc_id": r["ncr_id"], "tipo": "NCR", "titulo": f"{r['ncr_id']} — {r['defecto']}",
            "fecha": r["fecha"], "lineas": lineas, "clientes": [r["cliente"]] if r["cliente"] else [],
            "confidencialidad": r["confidencialidad"], "contiene_pii": True,
        }
        cuerpo = (
            f"# {r['ncr_id']} — {r['defecto']}\n\n"
            f"| Campo | Valor |\n|---|---|\n"
            f"| Fecha | {r['fecha']} |\n| Línea | {r['linea']} |\n| Turno | {r['turno'] or '—'} |\n"
            f"| Detectado en | {r['detectado_en']} |\n| Origen | {r['origen']} |\n"
            f"| Cliente | {r['cliente']} |\n| Número de parte | {r['numero_parte']} |\n"
            f"| Variante | {r['variante']} |\n| Código de defecto | {r['defecto_codigo']} |\n"
            f"| Cantidad | {r['cantidad']} |\n| Estado | {r['estado']} |\n"
            f"| 8D relacionado | {r['ocho_d'] or '—'} |\n| Reportado por | {r['reportado_por']} |\n\n"
            f"## Descripción\n\n{r['descripcion']}\n\n"
            f"## Contención\n\n{r['contencion']}\n\n"
            f"## Disposición\n\n{r['disposicion']}\n\n"
            f"## Causa preliminar\n\n{r['causa_preliminar']}\n"
        )
        return front_matter(meta) + cuerpo

    # ------------------------------------------------------------------ 8D
    def medicion(self, apl, a, b):
        filas = [r for r in self.m.mediciones if r["aplicador_id"] == apl and a <= r["fecha"] <= b]
        return {
            "altura_media": round(mean(r["altura_mm"] for r in filas), 3),
            "altura_max": max(r["altura_mm"] for r in filas),
            "traccion_media": round(mean(r["traccion_n"] for r in filas), 1),
            "traccion_min": min(r["traccion_n"] for r in filas),
            "nok": sum(1 for r in filas if r["resultado_altura"] == "NOK" or r["resultado_traccion"] == "NOK"),
            "n": len(filas),
        }

    def resumen_eventos(self, ep):
        evs = self.eventos(ep)
        return {
            "piezas": self.piezas(evs),
            "fab_desde": min(e["fecha_fabricacion"] for e in evs),
            "fab_hasta": max(e["fecha_fabricacion"] for e in evs),
            "por_det": Counter({PUNTO[k]: v for k, v in self._suma(evs, "detectado_en").items()}),
            "por_linea": self._suma(evs, "linea"),
            "por_turno": self._suma(evs, "turno"),
            "por_pn": self._suma(evs, "numero_parte"),
            "cliente": sum(e["cantidad"] for e in evs if e["detectado_en"] == "CLIENTE"),
        }

    def _suma(self, evs, campo):
        c = Counter()
        for e in evs:
            c[e[campo]] += e["cantidad"]
        return c

    @staticmethod
    def tabla_conteo(counter, titulo_col):
        filas = "\n".join(f"| {k} | {v} |" for k, v in sorted(counter.items()))
        return f"| {titulo_col} | Piezas |\n|---|---|\n{filas}"

    def ochod_doc(self, doc_id, meta_extra, secciones):
        texto = "\n\n".join(secciones)
        meta = {
            "doc_id": doc_id, "tipo": "8D", **meta_extra,
            "confidencialidad": clasificar(texto), "contiene_pii": True,
        }
        self.ochod[doc_id] = (meta, texto)

    def generar_8d(self):
        P = self.persona
        # ---------------- 8D-2026-011 (H1, RC-01)
        r = self.resumen_eventos("H1")
        antes = self.medicion("APL-L1-02", "2026-04-20", "2026-05-01")
        par = self.medicion("APL-L1-01", "2026-04-20", "2026-05-01")
        despues = self.medicion("APL-L1-02", "2026-05-04", "2026-05-29")
        ot = next(o for o in self.m.mantenimiento if o["equipo_id"] == "APL-L1-02" and o["tipo"] == "Correctivo")
        ncrs = ", ".join(self.ncr_por_ep["H1"])
        lotes_h1 = ", ".join(sorted({e["lote_terminal"] for e in self.eventos("H1")}))
        self.ochod_doc("8D-2026-011", {
            "titulo": "8D-2026-011 — Falso contacto intermitente en terminales TRM-A-1064, línea L1",
            "fecha": "2026-06-05", "fecha_apertura": "2026-04-30", "estado": "Cerrado", "lineas": ["L1"],
            "clientes": ["Norvane Motors", "Kestrel Modules"],
        }, [
            "# 8D-2026-011 — Falso contacto intermitente en terminales TRM-A-1064, línea L1",
            f"| Campo | Valor |\n|---|---|\n| Apertura | 30 de abril de 2026 |\n| Cierre | 5 de junio de 2026 |\n"
            f"| Clientes afectados | Norvane Motors (A7-DRH-2210-M, A7-DRH-2210-H), Kestrel Modules (B3-FDH-0451) |\n"
            f"| NCRs relacionadas | {ncrs} |\n| Fila del AMEF | RC-01 |",
            "## D0 — Preparación\n\nSe abre 8D por repetición (3 NCRs de intermitencia y resistencia alta en L1 en una "
            "semana) y por severidad 8 en el AMEF. El 4 de mayo se suma el reclamo de Norvane Motors.",
            f"## D1 — Equipo\n\n| Rol | Nombre |\n|---|---|\n| Líder, ingeniería de calidad | {P('ing-cal-1')} |\n"
            f"| Ingeniería de proceso | {P('ing-proc-1')} |\n| Supervisión de mantenimiento | {P('sup-mant')} |\n"
            f"| Supervisión de producción L1 | {P('sup-prod-l1')} |\n| SQE de cuenta Norvane | {P('sqe-Norvane Motors')} |",
            f"## D2 — Descripción del problema\n\n**Qué:** falso contacto intermitente y resistencia de contacto alta en "
            f"circuitos con terminal TRM-A-1064. **Dónde:** línea L1. **Cuándo:** arneses fabricados del "
            f"{fmt_fecha(r['fab_desde'])} al {fmt_fecha(r['fab_hasta'])}, en los tres turnos. **Cuánto:** {r['piezas']} "
            f"piezas no conformes registradas, {r['cliente']} de ellas detectadas por clientes. **Cómo se detectó:** "
            f"auditoría de producto con prueba dinámica, prueba eléctrica y reclamo de Norvane. En prueba eléctrica "
            f"estática la mayoría de los arneses pasan.\n\n"
            + self.tabla_conteo(r["por_det"], "Punto de detección") + "\n\n"
            "| Pregunta | Es | No es |\n|---|---|---|\n"
            "| Objeto | Circuitos con TRM-A-1064 | Circuitos con TRM-B-2150 |\n"
            "| Línea | L1 | L2 |\n"
            f"| Turno | T1, T2 y T3 ({', '.join(f'{k}: {v}' for k, v in sorted(r['por_turno'].items()))}) | Un turno en particular |\n"
            "| Equipo | Circuitos crimpados con el aplicador APL-L1-02 | APL-L1-01, que crimpa la misma terminal |\n"
            f"| Material | Lote {lotes_h1} de TRM-A-1064 | El mismo lote crimpado con APL-L1-01 y en L2, sin el defecto |\n"
            "| Tiempo | Desde el 23 de abril, creciente | Antes del 20 de abril |",
            "## D3 — Contención\n\n1. Retención del inventario de L1 fabricado desde el 20 de abril y prueba dinámica al "
            "100%: 2,140 arneses probados, 7 rechazados.\n2. Inspección en tránsito y en almacén de Norvane: 980 arneses, 4 "
            "rechazados.\n3. Aplicador APL-L1-02 fuera de servicio desde el 1 de mayo hasta su correctivo.\n4. Prueba "
            "dinámica ampliada a 20 arneses por turno en L1 durante 4 semanas.",
            f"## D4 — Causa raíz\n\n### Causa de ocurrencia (AMEF RC-01)\n\nDesgaste del punzón y el yunque del aplicador "
            f"APL-L1-02 por operar sin mantenimiento preventivo. El último PM fue el 29 de marzo; los PM del 12, 19 y 26 "
            f"de abril se reprogramaron (auditoría de cliente, recuperación de volumen y falta de juego de repuesto). Al "
            f"momento del correctivo ({ot['ot_id']}, 2 de mayo) el aplicador acumulaba {int(ot['ciclos_al_evento']):,} "
            f"ciclos contra el umbral de 250,000 de SOP-MNT-008.\n\n**5 porqués:**\n\n1. ¿Por qué hay intermitencia? "
            "Porque el crimpado tiene baja compactación y la terminal tiene micro-movimiento.\n2. ¿Por qué baja "
            "compactación? Porque el punzón y el yunque desgastados comprimen menos el barril.\n3. ¿Por qué estaban "
            "desgastados? Porque el aplicador superó el doble de los ciclos entre PM.\n4. ¿Por qué no se hizo el PM? "
            "Porque SOP-MNT-008 permite reprogramar sin límite y no había juego de repuesto.\n5. ¿Por qué se permite? "
            "Porque el PM no está ligado a un bloqueo por contador de ciclos.\n\n**Verificación:** en las hojas de "
            f"verificación del 20 de abril al 1 de mayo, APL-L1-02 tuvo altura media de {antes['altura_media']} mm "
            f"(máxima {antes['altura_max']} mm) y tracción media de {antes['traccion_media']} N (mínima "
            f"{antes['traccion_min']} N), contra {par['altura_media']} mm y {par['traccion_media']} N de APL-L1-01 en el "
            "mismo periodo. Se crimparon 30 muestras con el herramental retirado: el corte transversal mostró "
            "compactación insuficiente. Con herramental nuevo las muestras quedaron conformes.\n\n### Causa de no "
            "detección (ND-01)\n\nLa altura se mide una vez al inicio de turno y la tracción una vez por turno "
            "(WI-CRP-002). Las lecturas individuales se mantuvieron dentro de especificación mientras la tendencia "
            "subía; la instrucción no define reglas de tendencia. La prueba eléctrica estática no detecta intermitencias "
            "(ND-07 como factor contribuyente).",
            "## D5 — Acciones correctivas permanentes\n\n| Acción | Responsable | Fecha |\n|---|---|---|\n"
            "| Reemplazo de punzón y yunque de APL-L1-02 | Mantenimiento | 2026-05-02 |\n"
            "| Contador de ciclos con bloqueo en PRS-L1-01 y PRS-L1-02: la prensa no opera si el aplicador supera "
            "260,000 ciclos sin PM registrado | Mantenimiento | 2026-05-22 |\n"
            "| Inventario mínimo de 2 juegos de punzón y yunque por familia de terminal | Compras / Mantenimiento | 2026-05-29 |",
            f"## D6 — Implementación y validación\n\nDel 4 al 29 de mayo, APL-L1-02 promedió {despues['altura_media']} mm "
            f"de altura y {despues['traccion_media']} N de tracción. No hubo NCRs de intermitencia en L1 durante las 4 "
            "semanas posteriores. El bloqueo por ciclos de L1 se probó forzando el contador: la prensa se detuvo.",
            "## D7 — Prevención de recurrencia\n\n| Acción | Estado al cierre |\n|---|---|\n"
            "| AMEF RC-01: ocurrencia de 3 a 4; control de prevención actualizado con bloqueo por ciclos en L1 | Hecho |\n"
            "| Despliegue horizontal del bloqueo por ciclos a PRS-L2-01 y PRS-L2-02 | En proceso; compra de contadores "
            "(OC-2026-0441), fecha compromiso 31 de julio de 2026 |\n"
            "| SOP-MNT-008 rev C: máximo una reprogramación de PM con aprobación de gerencia de calidad | En revisión |\n"
            "| Evaluar gráfica de tendencia de altura de crimpado en WI-CRP-002 | Pendiente; responsable ingeniería de calidad |",
            "## D8 — Cierre\n\nCriterio de salida: 4 semanas sin recurrencia en L1 y aceptación de Norvane. Cerrado el 5 de "
            "junio de 2026. Se reconoce al equipo de mantenimiento por el correctivo en fin de semana.",
        ])

        # ---------------- 8D-2026-019 (H2, RC-02)
        r = self.resumen_eventos("H2")
        lote = self.m.lote_de_episodio("H2")
        lotes_a = [l for l in self.m.lotes if l["familia"] == "A"]
        idx = next(i for i, l in enumerate(lotes_a) if l["lote_id"] == lote)
        previos = lotes_a[max(0, idx - 2):idx]
        def4 = lambda lid: sum(e["cantidad"] for e in self.m.eventos if e["lote_terminal"] == lid and e["defecto_codigo"] == "DEF-04")
        comp = "\n".join(f"| {l['lote_id']} | {l['proveedor']} | {l['consumo_desde']} a {l['consumo_hasta']} | {def4(l['lote_id'])} |"
                         for l in previos + [lotes_a[idx]])
        ncrs = ", ".join(self.ncr_por_ep["H2"])
        self.ochod_doc("8D-2026-019", {
            "titulo": "8D-2026-019 — Terminales TRM-A-1064 retraídas del conector (back-out), líneas L1 y L2",
            "fecha": "2026-07-17", "fecha_apertura": "2026-06-06", "estado": "Cerrado", "lineas": ["L1", "L2"],
            "clientes": ["Norvane Motors", "Kestrel Modules"],
        }, [
            "# 8D-2026-019 — Terminales TRM-A-1064 retraídas del conector, líneas L1 y L2",
            f"| Campo | Valor |\n|---|---|\n| Apertura | 6 de junio de 2026 |\n| Cierre | 17 de julio de 2026 |\n"
            f"| Clientes afectados | Norvane Motors, Kestrel Modules |\n| NCRs relacionadas | {ncrs} |\n"
            f"| Proveedor | PRV-02 Conexa Terminales |\n| SCAR | SCAR-2026-007 |\n| Fila del AMEF | RC-02 |",
            "## D0 — Preparación\n\nSe abre 8D por reclamo de Norvane Motors del 6 de junio. El 11 de junio se suma el "
            "reclamo de Kestrel Modules.",
            f"## D1 — Equipo\n\n| Rol | Nombre |\n|---|---|\n| Líder, ingeniería de calidad | {P('ing-cal-2')} |\n"
            f"| Calidad de proveedores | {P('cal-prov')} |\n| Inspección de recibo | {P('insp-recibo')} |\n"
            f"| Supervisión de producción L1 | {P('sup-prod-l1')} |\n| Supervisión de producción L2 | {P('sup-prod-l2')} |",
            f"## D2 — Descripción del problema\n\n**Qué:** terminales TRM-A-1064 que se retraen o salen del conector con "
            f"fuerza normal de manipulación; en algunos casos circuito abierto o intermitencia. **Dónde:** líneas L1 y L2, "
            f"todas las estaciones de inserción. **Cuándo:** fabricación del {fmt_fecha(r['fab_desde'])} al "
            f"{fmt_fecha(r['fab_hasta'])}. **Cuánto:** {r['piezas']} piezas no conformes, {r['cliente']} detectadas por "
            "clientes.\n\n" + self.tabla_conteo(r["por_linea"], "Línea") + "\n\n"
            "| Pregunta | Es | No es |\n|---|---|---|\n"
            "| Objeto | TRM-A-1064 | TRM-B-2150 |\n"
            "| Línea | L1 y L2 | Una sola línea |\n"
            "| Estación | Todas las estaciones de inserción | Una estación en particular |\n"
            "| Turno | Los tres turnos | Un turno en particular |\n"
            f"| Material | Lote {lote} (Conexa Terminales) | Lotes anteriores de ambos proveedores |\n"
            "| Crimpado | Altura y tracción dentro de especificación | Crimpado no conforme |",
            "## D3 — Contención\n\n1. Del 6 al 18 de junio: prueba de jalón al 100% en inspección final en ambas líneas.\n"
            f"2. 18 de junio: el análisis Es / No es identificó el lote {lote}. Su consumo se detuvo el 19 de junio; el "
            "remanente (61,000 piezas) se puso en cuarentena y se devolvió al proveedor.\n3. Inspección con jalón en "
            "tránsito y en almacenes de ambos clientes: 3,420 arneses, 38 rechazados.",
            f"## D4 — Causa raíz\n\n### Causa de ocurrencia (AMEF RC-02)\n\nLanza de retención primaria deformada en el "
            f"lote {lote} de TRM-A-1064. El proveedor confirmó en su respuesta a SCAR-2026-007 desgaste en la estación de "
            "formado de la lanza de su herramental de estampado, sin control dimensional de la altura de lanza en su "
            "proceso.\n\n**Verificación:** 50 piezas del lote medidas en laboratorio: altura de lanza media 0.21 mm contra "
            "0.32 mm del dibujo del proveedor; 50 piezas del lote anterior, 0.31 mm. Prueba de retención en conector de "
            "referencia: 9 de 50 piezas del lote fallaron contra 0 de 50 del lote anterior.\n\n"
            "| Lote | Proveedor | Consumo | Piezas DEF-04 |\n|---|---|---|---|\n" + comp + "\n\n"
            "### Causa de no detección (ND-02)\n\nConexa es proveedor categoría A; el lote se aceptó por certificado "
            "(SOP-REC-009) sin medición. La prueba de jalón en inspección final es por muestreo (5 arneses por turno).",
            "## D5 — Acciones correctivas permanentes\n\n| Acción | Responsable | Fecha |\n|---|---|---|\n"
            "| Proveedor: reemplazo del herramental de formado y control dimensional de altura de lanza por lote | Conexa "
            "Terminales | 2026-06-30 |\n"
            "| TRM-A-1064 de Conexa a muestreo reforzado (32 piezas, prueba de retención) por 3 lotes | Inspección de "
            "recibo | Desde 2026-06-20 |",
            "## D6 — Implementación y validación\n\nLos 3 lotes siguientes de TRM-A-1064 de Conexa pasaron el muestreo "
            "reforzado sin rechazos. No hubo reclamos de back-out de TRM-A-1064 después del 28 de junio.",
            "## D7 — Prevención de recurrencia\n\n| Acción | Estado al cierre |\n|---|---|\n"
            "| AMEF RC-02: control de detección actualizado con muestreo reforzado tras SCAR | Hecho |\n"
            "| Evaluar extensión a TRM-B-2150 de Conexa | Evaluado: no aplica; el proveedor indica que el herramental "
            "afectado es exclusivo de TRM-A-1064 |\n"
            "| Prueba de retención en recibo para todas las terminales | No aprobado por costo de inspección |",
            "## D8 — Cierre\n\nCriterio de salida: 3 lotes conformes y 4 semanas sin reclamos. Cerrado el 17 de julio de "
            "2026.",
        ])

        # ---------------- 8D-2026-024 (H3, RC-04)
        r = self.resumen_eventos("H3")
        ncrs = ", ".join(self.ncr_por_ep["H3"])
        self.ochod_doc("8D-2026-024", {
            "titulo": "8D-2026-024 — Resistencia alta y circuitos abiertos en circuitos WIR-050, línea L1",
            "fecha": "2026-08-07", "fecha_apertura": "2026-07-09", "estado": "Cerrado", "lineas": ["L1"],
            "clientes": ["Kestrel Modules"],
        }, [
            "# 8D-2026-024 — Resistencia alta y circuitos abiertos en circuitos WIR-050, línea L1",
            f"| Campo | Valor |\n|---|---|\n| Apertura | 9 de julio de 2026 |\n| Cierre | 7 de agosto de 2026 |\n"
            f"| Cliente afectado | Kestrel Modules (B3-FDH-0451) |\n| NCRs relacionadas | {ncrs} |\n| Fila del AMEF | RC-04 |",
            "## D0 — Preparación\n\nSe abre 8D por repetición: 3 NCRs de resistencia alta y circuito abierto en L1 en 4 días.",
            f"## D1 — Equipo\n\n| Rol | Nombre |\n|---|---|\n| Líder, ingeniería de calidad | {P('ing-cal-1')} |\n"
            f"| Ingeniería de proceso | {P('ing-proc-1')} |\n| Laboratorio de calidad | {P('lab')} |\n"
            f"| Supervisión de producción L1 | {P('sup-prod-l1')} |",
            f"## D2 — Descripción del problema\n\n**Qué:** resistencia alta y circuitos abiertos en circuitos de cable "
            f"WIR-050 con terminal TRM-A-1064. **Dónde:** línea L1. **Cuándo:** fabricación del "
            f"{fmt_fecha(r['fab_desde'])} al {fmt_fecha(r['fab_hasta'])}, los tres turnos. **Cuánto:** {r['piezas']} "
            f"piezas, {r['cliente']} detectadas por Kestrel Modules.\n\n"
            + self.tabla_conteo(r["por_det"], "Punto de detección") + "\n\n"
            "| Pregunta | Es | No es |\n|---|---|---|\n"
            "| Objeto | Circuitos de cable WIR-050 (solo arnés B3-FDH-0451) | Circuitos WIR-035, WIR-075, WIR-100 |\n"
            "| Línea | L1 | L2 |\n| Equipo | Varios aplicadores de familia A | Un aplicador en particular |\n"
            "| Tiempo | Desde el 6 de julio, salto repentino | Antes del 6 de julio |",
            "## D3 — Contención\n\n1. Retención de circuitos WIR-050 de L1 fabricados desde el 6 de julio: 1,260 circuitos "
            "revisados en corte transversal por muestreo y retrabajo de los arneses afectados.\n2. Inspección en almacén "
            "de Kestrel Modules: 520 arneses, 3 rechazados.",
            "## D4 — Causa raíz\n\n### Causa de ocurrencia (AMEF RC-04)\n\nEl 6 de julio se migraron las recetas de "
            "CUT-L1-01 al nuevo controlador HMI (CHG-2026-007). Los parámetros de R-050 se capturaron desde la hoja de "
            "parámetros impresa de la estación, que correspondía a la revisión B de SPEC-CRP-001 (desforre 3.8 mm). La "
            "revisión vigente E especifica 4.5 mm desde la revisión D. Con 3.8 mm el aislamiento entra al barril "
            "conductor.\n\n**Verificación:** el laboratorio encontró aislamiento atrapado en 3 de 5 cortes transversales "
            "de circuitos WIR-050 del 6 al 14 de julio y en 0 de 5 después de la corrección. Se reprodujo el defecto "
            "cargando 3.8 mm en una corrida de 20 piezas.\n\n### Causa de no detección (ND-04)\n\nEl primer artículo "
            "(WI-CUT-001) se aprobó contra la misma hoja impresa de la estación, que estaba obsoleta. Ninguna verificación "
            "compara contra la revisión vigente de SPEC-CRP-001.",
            "## D5 — Acciones correctivas permanentes\n\n| Acción | Responsable | Fecha |\n|---|---|---|\n"
            "| Corrección de R-050 en CUT-L1-01 a 4.5 mm (CHG-2026-008) | Ingeniería de proceso | 2026-07-15 |\n"
            "| Retiro de hojas impresas en CUT-L1-01; hoja de primer artículo con código QR a SPEC-CRP-001 vigente | "
            "Ingeniería de proceso | 2026-07-24 |",
            "## D6 — Implementación y validación\n\nDesde el 15 de julio no hubo resistencia alta en circuitos WIR-050 de "
            "L1. Cortes transversales semanales conformes durante 3 semanas.",
            "## D7 — Prevención de recurrencia\n\n| Acción | Estado al cierre |\n|---|---|\n"
            "| Retirar hojas impresas obsoletas de CUT-L2-01 y verificar contra SPEC-CRP-001 vigente antes de la migración "
            "de recetas de L2 al controlador HMI | Pendiente; fecha compromiso 28 de agosto de 2026 |\n"
            "| WI-CUT-001 rev D: primer artículo contra especificación vigente | En revisión |\n"
            "| AMEF RC-04: actualizar control de detección | Pendiente de WI-CUT-001 rev D |",
            "## D8 — Cierre\n\nCriterio de salida: 3 semanas sin recurrencia en L1. Cerrado el 7 de agosto de 2026.",
        ])

        # ---------------- 8D-2026-013 (N1, RC-14)
        r = self.resumen_eventos("N1")
        self.ochod_doc("8D-2026-013", {
            "titulo": "8D-2026-013 — Etiqueta con revisión anterior en arneses B3-FDH-0451, línea L2",
            "fecha": "2026-06-12", "fecha_apertura": "2026-05-08", "estado": "Cerrado", "lineas": ["L2"],
            "clientes": ["Kestrel Modules"],
        }, [
            "# 8D-2026-013 — Etiqueta con revisión anterior en arneses B3-FDH-0451, línea L2",
            f"| Campo | Valor |\n|---|---|\n| Apertura | 8 de mayo de 2026 |\n| Cierre | 12 de junio de 2026 |\n"
            f"| Cliente afectado | Kestrel Modules |\n| NCRs relacionadas | {', '.join(self.ncr_por_ep['N1'])} |\n"
            "| Fila del AMEF | RC-14 |",
            f"## D1 — Equipo\n\n| Rol | Nombre |\n|---|---|\n| Líder, ingeniería de calidad | {P('ing-cal-2')} |\n"
            f"| Ingeniería de manufactura | {P('ing-man')} |\n| Supervisión de empaque L2 | {P('sup-emp-l2')} |",
            f"## D2 — Descripción del problema\n\nArneses B3-FDH-0451 de L2 etiquetados con la revisión C del dibujo en "
            f"lugar de la D, fabricados del {fmt_fecha(r['fab_desde'])} al {fmt_fecha(r['fab_hasta'])}. {r['piezas']} "
            "piezas registradas; el sistema de recibo de Kestrel rechazó una caja. Solo L2; L1 etiqueta correctamente.",
            "## D3 — Contención\n\nRe-etiquetado de inventario en planta y en almacén del cliente (412 arneses).",
            "## D4 — Causa raíz\n\n**Ocurrencia (RC-14):** el 3 de mayo se reinstaló el software de la impresora de EMP-L2 "
            "y se cargó una copia de respaldo con la plantilla revisión 4, anterior al ECN-2026-012.\n\n**No detección "
            "(ND-06):** el escaneo de etiqueta en empaque valida el número de parte, pero no la revisión del dibujo.",
            "## D5 — Acciones correctivas permanentes\n\nPlantilla actualizada (CHG-2026-003). El escáner de empaque valida "
            "número de parte y revisión contra la orden de producción.",
            "## D6 — Validación\n\n4 semanas sin etiquetas con revisión incorrecta en ambas líneas.",
            "## D7 — Prevención de recurrencia\n\nProcedimiento de respaldo de impresoras actualizado; validación de revisión "
            "extendida a EMP-L1. AMEF RC-14 actualizado.",
            "## D8 — Cierre\n\nCerrado el 12 de junio de 2026.",
        ])

        # ---------------- 8D-2026-021 (N2, RC-12)
        r = self.resumen_eventos("N2")
        self.ochod_doc("8D-2026-021", {
            "titulo": "8D-2026-021 — Encintado desprendido en arneses de línea L1",
            "fecha": "2026-08-14", "fecha_apertura": "2026-06-24", "estado": "Cerrado", "lineas": ["L1"],
            "clientes": ["Norvane Motors", "Kestrel Modules"],
        }, [
            "# 8D-2026-021 — Encintado desprendido en arneses de línea L1",
            f"| Campo | Valor |\n|---|---|\n| Apertura | 24 de junio de 2026 |\n| Cierre | 14 de agosto de 2026 |\n"
            f"| NCRs relacionadas | {', '.join(self.ncr_por_ep['N2'])} |\n| Fila del AMEF | RC-12 |",
            f"## D1 — Equipo\n\n| Rol | Nombre |\n|---|---|\n| Líder, ingeniería de calidad | {P('ing-cal-1')} |\n"
            f"| Calidad de proveedores | {P('cal-prov')} |\n| Supervisión de producción L1 | {P('sup-prod-l1')} |",
            f"## D2 — Descripción del problema\n\nCinta desprendida en ramales de arneses A7-DRH-2210-M, A7-DRH-2210-H y "
            f"B3-FDH-0451 de L1, fabricados del {fmt_fecha(r['fab_desde'])} al {fmt_fecha(r['fab_hasta'])}, en los tres "
            f"turnos y con distintos operadores. {r['piezas']} piezas detectadas en inspección final. L2 usa otro lote de "
            "cinta y no presenta el defecto.",
            "## D3 — Contención\n\nRe-encintado del inventario de L1 y cambio inmediato del lote de cinta.",
            "## D4 — Causa raíz\n\n**Ocurrencia (RC-12):** lote de cinta con adhesión de 1.9 N/cm contra mínimo de 2.5 N/cm "
            "de la especificación de compra, confirmado por el laboratorio.\n\n**No detección (ND-02):** la cinta se "
            "acepta por certificado del proveedor sin prueba de adhesión.\n\nSe descartó la técnica de encintado porque el "
            "defecto apareció en los tres turnos al mismo tiempo y desapareció con el cambio de lote.",
            "## D5 — Acciones correctivas permanentes\n\nPrueba de adhesión por lote de cinta en recibo durante 6 meses; "
            "SCAR al proveedor de cinta.",
            "## D6 — Validación\n\n6 semanas sin encintado desprendido en L1.",
            "## D7 — Prevención de recurrencia\n\nAMEF RC-12 actualizado; prueba de adhesión aplicada a todas las cintas.",
            "## D8 — Cierre\n\nCerrado el 14 de agosto de 2026.",
        ])

        # ---------------- 8D-2026-027 (N3, RC-15)
        r = self.resumen_eventos("N3")
        self.ochod_doc("8D-2026-027", {
            "titulo": "8D-2026-027 — Aislamiento raspado en ramal principal, línea L2",
            "fecha": "2026-09-18", "fecha_apertura": "2026-08-20", "estado": "Cerrado", "lineas": ["L2"],
            "clientes": [],
        }, [
            "# 8D-2026-027 — Aislamiento raspado en ramal principal, línea L2",
            f"| Campo | Valor |\n|---|---|\n| Apertura | 20 de agosto de 2026 |\n| Cierre | 18 de septiembre de 2026 |\n"
            f"| NCRs relacionadas | {', '.join(self.ncr_por_ep['N3'])} |\n| Fila del AMEF | RC-15 |",
            f"## D1 — Equipo\n\n| Rol | Nombre |\n|---|---|\n| Líder, ingeniería de calidad | {P('ing-cal-2')} |\n"
            f"| Mantenimiento | {P('sup-mant')} |\n| Supervisión de producción L2 | {P('sup-prod-l2')} |",
            f"## D2 — Descripción del problema\n\nAislamiento raspado o cortado en el ramal principal, siempre en la misma "
            f"zona, en arneses de las tres variantes de L2 fabricados del {fmt_fecha(r['fab_desde'])} al "
            f"{fmt_fecha(r['fab_hasta'])}. {r['piezas']} piezas; algunas con corto detectado en prueba eléctrica. L1 sin "
            "el defecto.",
            "## D3 — Contención\n\nInspección 100% del ramal principal en L2 hasta el reemplazo de la guía.",
            "## D4 — Causa raíz\n\n**Ocurrencia (RC-15):** guía del ramal principal en el tablero BRD-L2 con borde filoso "
            "por desgaste del recubrimiento.\n\n**No detección (ND-08):** WI-BRD-005 pide verificar guías al inicio del "
            "turno, pero la verificación no se registraba ni se ejecutaba de forma consistente.",
            "## D5 — Acciones correctivas permanentes\n\nReemplazo de la guía (CHG-2026-016) y lista de verificación de "
            "tablero con registro por turno.",
            "## D6 — Validación\n\n3 semanas sin daño de aislamiento en L2.",
            "## D7 — Prevención de recurrencia\n\nRevisión de guías de BRD-L1; mantenimiento trimestral de guías agregado al "
            "plan.",
            "## D8 — Cierre\n\nCerrado el 18 de septiembre de 2026.",
        ])

    def generar(self):
        self.ncrs_escenarios()
        self.ncrs_ruido()
        self.numerar_ncrs()
        self.generar_8d()
        return self
