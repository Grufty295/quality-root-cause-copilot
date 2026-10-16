"""Generación de los datos estructurados que consultan las tools del agente."""

import random
from collections import defaultdict
from datetime import date, timedelta

import config as C
from episodios import EPISODIOS as EP


def dias(a, b):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


def es_dia_produccion(d):
    return d.weekday() < 6  # lunes a sábado


def poisson(rng, lam):
    if lam <= 0:
        return 0
    l, k, p = pow(2.718281828459045, -lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= l:
            return k
        k += 1


def elegir(rng, pesos):
    total = sum(pesos.values())
    r = rng.random() * total
    acc = 0.0
    for k, w in pesos.items():
        acc += w
        if r <= acc:
            return k
    return k


class Mundo:
    def __init__(self, seed=C.SEED):
        self.rng = random.Random(seed)
        self.produccion = []          # filas
        self.prod_idx = {}            # (fecha, linea, turno, pn) -> unidades
        self.ciclos = {}              # (aplicador, fecha) -> ciclos del día
        self.mantenimiento = []
        self.pm_completados = defaultdict(list)  # aplicador -> [fechas en que se reinicia el contador]
        self.mediciones = []
        self.lotes = []
        self.cambios = []
        self.eventos = []
        self.sesgo_aplicador = {a: self.rng.uniform(-0.004, 0.004) for a in C.APLICADORES}

    # ------------------------------------------------------------------ producción
    def generar_produccion(self):
        for d in dias(C.START, C.END):
            if not es_dia_produccion(d):
                continue
            for ln in C.LINEAS:
                for t in C.TURNOS:
                    total = int(self.rng.gauss(400, 15))
                    asignado = 0
                    pns = list(C.ARNESES)
                    for i, pn in enumerate(pns):
                        u = total - asignado if i == len(pns) - 1 else round(total * C.ARNESES[pn]["mezcla"])
                        asignado += u
                        self.prod_idx[(d, ln, t, pn)] = u
                        self.produccion.append({
                            "fecha": d.isoformat(), "turno": t, "linea": ln, "numero_parte": pn,
                            "variante": C.ARNESES[pn]["variante"],
                            "cliente": C.CLIENTES[C.ARNESES[pn]["cliente"]]["nombre"], "unidades": u,
                        })
        for apl, info in C.APLICADORES.items():
            fam = info["familia"]
            for d in dias(C.START, C.END):
                c = 0
                if es_dia_produccion(d):
                    for t in C.TURNOS:
                        for pn, a in C.ARNESES.items():
                            c += self.prod_idx[(d, info["linea"], t, pn)] * a[f"term_{fam}"] / 2
                self.ciclos[(apl, d)] = int(c)

    # ------------------------------------------------------------------ mantenimiento
    def _ot(self, apl, tipo, programada, ejecucion, estado, motivo, descripcion):
        n = len(self.mantenimiento) + 1
        self.mantenimiento.append({
            "ot_id": f"OT-2026-{n:04d}", "equipo_id": apl, "linea": C.APLICADORES[apl]["linea"],
            "tipo": tipo, "fecha_programada": programada.isoformat() if programada else "",
            "fecha_ejecucion": ejecucion.isoformat() if ejecucion else "", "estado": estado,
            "motivo_reprogramacion": motivo, "descripcion": descripcion, "ciclos_al_evento": "",
        })
        if estado == "Completada":
            self.pm_completados[apl].append(ejecucion)

    def generar_mantenimiento(self):
        domingos_a = [date(2026, 3, 29) + timedelta(days=14 * i) for i in range(14)]
        for apl, info in C.APLICADORES.items():
            # PM previo a la ventana para tener contador conocido
            self._ot(apl, "Preventivo", date(2026, 3, 29), date(2026, 3, 29), "Completada", "",
                     "PM de aplicador: limpieza, inspección de punzón y yunque, ajuste de altura")
            if info["familia"] == "A":
                fechas = domingos_a[1:]
            else:
                desfase = 0 if apl.endswith("03") else 7
                fechas = [date(2026, 3, 29) + timedelta(days=28 * i + desfase) for i in range(1, 8)]
            fechas = [f for f in fechas if f <= C.END]

            if apl == "APL-L1-02":  # H1
                self._ot(apl, "Preventivo", date(2026, 4, 12), None, "Reprogramada",
                         "Auditoría de cliente; técnicos asignados a soporte de la auditoría", "PM de aplicador")
                self._ot(apl, "Preventivo", date(2026, 4, 19), None, "Reprogramada",
                         "Recuperación de volumen; sin ventana de paro disponible", "PM de aplicador")
                self._ot(apl, "Preventivo", date(2026, 4, 26), None, "Reprogramada",
                         "Falta de juego de punzón y yunque de repuesto para familia A", "PM de aplicador")
                self._ot(apl, "Correctivo", date(2026, 5, 2), date(2026, 5, 2), "Completada", "",
                         "Correctivo por NCR de calidad: desgaste visible en radios de punzón y yunque; "
                         "reemplazo de ambos; ajuste de altura de cierre; primer artículo conforme")
                fechas = [date(2026, 5, 2) + timedelta(days=15 + 14 * i) for i in range(11)]
                fechas = [f for f in fechas if f <= C.END]
            elif apl == "APL-L2-01":  # E6
                fechas = [f for f in fechas if f <= date(2026, 8, 16)]
            for f in fechas:
                if apl == "APL-L2-02" and f == date(2026, 7, 19):
                    self._ot(apl, "Preventivo", f, None, "Reprogramada", "Carga de producción", "PM de aplicador")
                    self._ot(apl, "Preventivo", f + timedelta(days=7), f + timedelta(days=7), "Completada", "",
                             "PM de aplicador: limpieza, inspección de punzón y yunque, ajuste de altura")
                    continue
                if apl == "APL-L1-04" and f.month == 6:
                    self._ot(apl, "Preventivo", f, None, "Reprogramada", "Carga de producción", "PM de aplicador")
                    self._ot(apl, "Preventivo", f + timedelta(days=7), f + timedelta(days=7), "Completada", "",
                             "PM de aplicador: limpieza, inspección de punzón y yunque, ajuste de altura")
                    continue
                self._ot(apl, "Preventivo", f, f, "Completada", "",
                         "PM de aplicador: limpieza, inspección de punzón y yunque, ajuste de altura")
            if apl == "APL-L2-01":
                self._ot(apl, "Preventivo", date(2026, 8, 30), None, "Reprogramada",
                         "Carga de producción; prensa sin ventana de paro", "PM de aplicador")
                self._ot(apl, "Preventivo", date(2026, 9, 6), None, "Reprogramada",
                         "Falta de juego de punzón y yunque de repuesto; requisición REQ-2026-1187 en trámite",
                         "PM de aplicador")
                self._ot(apl, "Preventivo", date(2026, 9, 13), None, "Reprogramada",
                         "Refacción en tránsito del proveedor del aplicador", "PM de aplicador")
                self._ot(apl, "Preventivo", date(2026, 9, 27), None, "Pendiente",
                         "Refacción en tránsito del proveedor del aplicador", "PM de aplicador")
        # otras prensas: un correctivo de ruido en PRS-L1-01
        self._ot_prensa("PRS-L1-01", date(2026, 6, 9), "Correctivo",
                        "Fuga en cilindro neumático de alimentación; reemplazo de sello")
        self._ot_prensa("CUT-L2-01", date(2026, 5, 20), "Correctivo",
                        "Cambio de cuchillas de desforre por contador")
        self._ot_prensa("CUT-L1-01", date(2026, 6, 24), "Correctivo",
                        "Cambio de cuchillas de desforre por contador")
        self._calcular_ciclos_en_ot()
        self.mantenimiento.sort(key=lambda r: (r["fecha_programada"], r["equipo_id"]))
        for i, r in enumerate(self.mantenimiento, 1):
            r["ot_id"] = f"OT-2026-{i:04d}"

    def _ot_prensa(self, equipo, f, tipo, desc):
        ln = equipo.split("-")[1]
        n = len(self.mantenimiento) + 1
        self.mantenimiento.append({
            "ot_id": f"OT-2026-{n:04d}", "equipo_id": equipo, "linea": ln, "tipo": tipo,
            "fecha_programada": f.isoformat(), "fecha_ejecucion": f.isoformat(), "estado": "Completada",
            "motivo_reprogramacion": "", "descripcion": desc, "ciclos_al_evento": "",
        })

    def ciclos_desde_pm(self, apl, d, fraccion_dia=1.0, estricto=False):
        """Ciclos acumulados desde el último PM completado hasta la fracción indicada del día d.

        Un PM ejecutado en d se considera hecho antes del primer turno. Con estricto=True se
        ignora el PM del mismo día (sirve para registrar los ciclos al momento de ese PM)."""
        previos = [f for f in self.pm_completados[apl] if (f < d if estricto else f <= d)]
        ultimo = max(previos) if previos else date(2026, 3, 29)
        if ultimo == d:
            return int(self.ciclos.get((apl, d), 0) * fraccion_dia), ultimo
        total = 0
        x = ultimo + timedelta(days=1)
        while x < d:
            total += self.ciclos.get((apl, x), 0)
            x += timedelta(days=1)
        total += int(self.ciclos.get((apl, d), 0) * fraccion_dia)
        return total, ultimo

    def _calcular_ciclos_en_ot(self):
        for r in self.mantenimiento:
            apl = r["equipo_id"]
            if apl in C.APLICADORES and r["estado"] == "Completada" and r["fecha_ejecucion"]:
                f = date.fromisoformat(r["fecha_ejecucion"])
                if f >= C.START:
                    c, _ = self.ciclos_desde_pm(apl, f, fraccion_dia=0.0, estricto=True)
                    r["ciclos_al_evento"] = c

    # ------------------------------------------------------------------ crimpado
    def deriva(self, ciclos):
        exceso = max(0, ciclos - C.CICLOS_INICIO_DESGASTE)
        return exceso / 100_000 * C.DERIVA_MM_POR_100K

    def generar_mediciones(self):
        fracciones = {"T1": 0.05, "T2": 0.38, "T3": 0.71}
        for d in dias(C.START, C.END):
            if not es_dia_produccion(d):
                continue
            for apl, info in C.APLICADORES.items():
                spec = C.SPEC_CRIMPADO[info["familia"]]
                for t in C.TURNOS:
                    ciclos, _ = self.ciclos_desde_pm(apl, d, fracciones[t])
                    dv = self.deriva(ciclos) if info["familia"] == "A" else 0.0
                    ruido = 0.006 if info["familia"] == "A" else 0.008
                    altura = spec["nominal"] + self.sesgo_aplicador[apl] + dv + self.rng.gauss(0, ruido)
                    traccion = spec["traccion_base"] - (dv / 0.04) * 14 + self.rng.gauss(0, 2.5 if info["familia"] == "A" else 4.0)
                    altura, traccion = round(altura, 3), round(traccion, 1)
                    res_a = "OK" if spec["lsl"] <= altura <= spec["usl"] else "NOK"
                    res_t = "OK" if traccion >= spec["traccion_min"] else "NOK"
                    acciones = []
                    if res_a == "NOK":
                        acciones.append("Re-medición de la misma pieza dentro de especificación; se continúa")
                    if res_t == "NOK":
                        acciones.append("Repetición con nueva muestra conforme; se continúa")
                    self.mediciones.append({
                        "fecha": d.isoformat(), "turno": t, "linea": info["linea"], "aplicador_id": apl,
                        "prensa_id": info["prensa"], "combinacion": spec["combinacion"],
                        "altura_mm": altura, "altura_lsl": spec["lsl"], "altura_usl": spec["usl"],
                        "resultado_altura": res_a, "traccion_n": traccion,
                        "traccion_min": spec["traccion_min"], "resultado_traccion": res_t,
                        "accion": "; ".join(acciones),
                    })

    # ------------------------------------------------------------------ lotes
    def generar_lotes(self):
        rng = self.rng
        forzados = {"A": [("H2", EP["H2"])], "B": [("E7", EP["E7"])]}
        seq = {"A": 0, "B": 0}
        reforzados_restantes = 0
        for fam in ("A", "B"):
            inicio = date(2026, 3, 27)
            ventanas = []
            cortes = sorted(forzados[fam], key=lambda x: x[1]["consumo"][0])
            cursor = inicio
            for clave, ep in cortes:
                a, b = ep["consumo"]
                while (a - cursor).days > 18:
                    largo = rng.randint(9, 15)
                    if (a - (cursor + timedelta(days=largo))).days < 7:
                        largo = (a - cursor).days
                    ventanas.append((cursor, cursor + timedelta(days=largo - 1), None))
                    cursor = cursor + timedelta(days=largo)
                if cursor < a:
                    ventanas.append((cursor, a - timedelta(days=1), None))
                ventanas.append((a, b, clave))
                cursor = b + timedelta(days=1)
            while cursor <= C.END:
                largo = rng.randint(9, 15)
                ventanas.append((cursor, min(C.END, cursor + timedelta(days=largo - 1)), None))
                cursor += timedelta(days=largo)

            alterna = 0
            for (a, b, clave) in ventanas:
                seq[fam] += 1
                if clave:
                    prov = EP[clave]["proveedor"]
                    recep = EP[clave]["recepcion"]
                else:
                    if fam == "A":
                        prov = "PRV-01" if alterna % 2 == 0 else "PRV-02"
                        alterna += 1
                    else:
                        prov = "PRV-02" if rng.random() < 0.7 else "PRV-01"
                    recep = a - timedelta(days=rng.randint(2, 6))
                inspeccion = "Certificado (skip-lot)"
                estado = "Consumido"
                if clave == "H2":
                    estado = "Consumo detenido el 2026-06-19; remanente en cuarentena y devuelto (SCAR-2026-007)"
                    reforzados_restantes = 3
                elif fam == "A" and prov == "PRV-02" and reforzados_restantes > 0 and a > EP["H2"]["consumo"][1]:
                    inspeccion = "Muestreo reforzado 32 piezas (SCAR-2026-007)"
                    reforzados_restantes -= 1
                if b >= C.END:
                    estado = "En consumo"
                lote_id = f"LT-{fam}-{recep.strftime('%y%m')}-{seq[fam]:02d}"
                self.lotes.append({
                    "lote_id": lote_id, "numero_parte": C.TERMINAL_POR_FAMILIA[fam], "familia": fam,
                    "proveedor_id": prov, "proveedor": C.PROVEEDORES[prov]["nombre"],
                    "fecha_recepcion": recep.isoformat(), "cantidad": rng.choice([150_000, 200_000, 250_000]) if fam == "A" else rng.choice([40_000, 50_000, 60_000]),
                    "tipo_inspeccion": inspeccion, "resultado_inspeccion": "Liberado",
                    "consumo_desde": a.isoformat(), "consumo_hasta": b.isoformat(), "estado": estado,
                    "_episodio": clave or "",
                })

    def lote_activo(self, fam, d):
        for l in self.lotes:
            if l["familia"] == fam and l["consumo_desde"] <= d.isoformat() <= l["consumo_hasta"]:
                return l["lote_id"]
        return ""

    def lote_de_episodio(self, clave):
        return next(l["lote_id"] for l in self.lotes if l["_episodio"] == clave)

    # ------------------------------------------------------------------ cambios
    def generar_cambios(self):
        filas = [
            # (fecha, tipo, equipo, numero_parte, variante, linea, rev_ant, rev_nueva, descripcion, tablero, programa, aprobado)
            ("2026-04-08", "Cambio de herramienta", "APL-L2-03", "TRM-B-2150", "", "L2", "", "",
             "Reemplazo programado de yunque por vida útil del fabricante", "", "", "Mantenimiento"),
            ("2026-04-20", "ECN", "", "B3-FDH-0451", "Base", "L1, L2", "C", "D",
             "ECN-2026-012: cambio de color de cinta de identificación en ramal de espejo", "Sí", "No aplica",
             "Ingeniería de producto"),
            ("2026-05-12", "Cambio de plantilla", "EMP-L2", "B3-FDH-0451", "Base", "L2", "4", "5",
             "Actualización de plantilla de etiqueta en impresora EMP-L2 a revisión vigente", "", "",
             "Ingeniería de manufactura"),
            ("2026-05-25", "Receta de máquina", "CUT-L1-01", "WIR-075", "", "L1", "B", "C",
             "Ajuste de velocidad de alimentación en receta R-075 para reducir rayado de aislamiento", "", "",
             "Ingeniería de proceso"),
            ("2026-06-08", "Cambio de mano de obra", "INS-L2-01", "", "", "L2", "", "",
             "Rotación de 2 operadores certificados de INS-L2-02 a INS-L2-01, turno T2", "", "",
             "Producción"),
            ("2026-06-15", "ECN", "", "A7-DRH-2210-M", "Media", "L1, L2", "F", "G",
             "ECN-2026-024: reubicación de clip K3 en ramal de cerradura (variante Media)", "Sí", "Sí (rev 9)",
             "Ingeniería de producto"),
            ("2026-07-06", "Receta de máquina", "CUT-L1-01", "WIR-050", "", "L1", "C", "D",
             "Migración de recetas al nuevo controlador HMI de CUT-L1-01; parámetros de R-050 capturados "
             "desde la hoja de parámetros impresa de la estación. Primer artículo conforme contra la hoja de la estación",
             "", "", "Ingeniería de proceso"),
            ("2026-07-15", "Receta de máquina", "CUT-L1-01", "WIR-050", "", "L1", "D", "E",
             "Corrección de R-050: longitud de desforre a 4.5 mm según SPEC-CRP-001 rev E (8D-2026-024)", "", "",
             "Ingeniería de proceso"),
            ("2026-07-20", "Receta de máquina", "CUT-L1-01", "WIR-035", "", "L1", "D", "E",
             "Migración de receta R-035 al controlador HMI de CUT-L1-01 verificada contra SPEC-CRP-001 rev E", "", "",
             "Ingeniería de proceso"),
            ("2026-07-27", "Cambio de mano de obra", "BRD-L1", "", "", "L1", "", "",
             "Ingreso de 2 operadores de nuevo ingreso a BRD-L1, turno T1", "", "", "Producción"),
            ("2026-08-03", "Cambio de mano de obra", "INS-L1-02", "", "", "L1", "", "",
             "Ingreso de 3 operadores de nuevo ingreso a INS-L1-02, turno T3; inducción en estación con WI-INS-004 rev B",
             "", "", "Producción"),
            ("2026-08-10", "Receta de máquina", "CUT-L2-01", "WIR-050", "", "L2", "C", "D",
             "Migración de recetas al nuevo controlador HMI de CUT-L2-01; parámetros de R-050 capturados "
             "desde la hoja de parámetros impresa de la estación. Primer artículo conforme contra la hoja de la estación",
             "", "", "Ingeniería de proceso"),
            ("2026-08-19", "Receta de máquina", "CUT-L2-01", "WIR-050", "", "L2", "D", "E",
             "Corrección de R-050 en CUT-L2-01: longitud de desforre a 4.5 mm según SPEC-CRP-001 rev E", "", "",
             "Ingeniería de proceso"),
            ("2026-08-20", "ECN", "", "A7-DRH-2210-H", "Alta", "L1, L2", "H", "J",
             "ECN-2026-031 liberado: nueva ruta del ramal del conector C14 (bocina) por clip K7 en lugar de K5; "
             "fecha efectiva 2026-08-24", "No", "No", "Ingeniería de producto"),
            ("2026-08-24", "ECN", "", "A7-DRH-2210-H", "Alta", "L1, L2", "H", "J",
             "ECN-2026-031 efectivo en producción (punto de corte: lote del 2026-08-22)",
             "No (plantillas en fabricación)", "No", "Planeación"),
            ("2026-08-25", "Cambio de herramienta", "BRD-L2", "", "", "L2", "", "",
             "Reemplazo de guía de ramal principal en tablero BRD-L2 por borde desgastado (8D-2026-027)", "", "",
             "Mantenimiento"),
            ("2026-09-02", "Receta de máquina", "CUT-L2-01", "WIR-035", "", "L2", "D", "E",
             "Migración de receta R-035 al controlador HMI de CUT-L2-01 verificada contra SPEC-CRP-001 rev E", "", "",
             "Ingeniería de proceso"),
            ("2026-09-11", "ECN", "BRD-L1, BRD-L2", "A7-DRH-2210-H", "Alta", "L1, L2", "H", "J",
             "ECN-2026-031: plantillas de tablero L1 y L2 actualizadas; programa de prueba rev 14 cargado", "Sí",
             "Sí (rev 14)", "Ingeniería de manufactura"),
            ("2026-09-14", "Cambio de herramienta", "APL-L1-01", "TRM-A-1064", "", "L1", "", "",
             "Reemplazo preventivo de punzón y yunque en PM", "", "", "Mantenimiento"),
        ]
        for i, f in enumerate(filas, 1):
            self.cambios.append({
                "cambio_id": f"CHG-2026-{i:03d}", "fecha": f[0], "tipo": f[1], "equipo_id": f[2],
                "numero_parte": f[3], "variante": f[4], "linea": f[5], "revision_anterior": f[6],
                "revision_nueva": f[7], "descripcion": f[8], "tablero_actualizado": f[9],
                "programa_prueba_actualizado": f[10], "aprobado_por_rol": f[11],
            })

    # ------------------------------------------------------------------ defectos
    def _evento(self, d, t, ln, codigo, pn=None, familia=None, aplicador=None, estacion=None,
                lote=None, cable=None, deteccion=None, cantidad=None, episodio="", origen=None):
        rng = self.rng
        info = C.DEFECTOS[codigo]
        if pn is None:
            pesos = {p: self.prod_idx[(d, ln, t, p)] for p in C.ARNESES}
            pn = elegir(rng, pesos)
        arn = C.ARNESES[pn]
        origen = origen or info["origen"]
        terminal = lote_t = cable_t = maquina = ""
        if origen in ("CRP", "INS", "CUT"):
            if familia is None:
                familia = "A" if rng.random() < arn["term_A"] / (arn["term_A"] + arn["term_B"]) else "B"
            terminal = C.TERMINAL_POR_FAMILIA[familia]
            lote_t = lote or self.lote_activo(familia, d)
            cables = [c for c in arn["cables"] if C.CABLES[c]["familia"] == familia]
            cable_t = cable or rng.choice(cables)
            if origen == "CRP" and aplicador is None:
                aplicador = rng.choice([a for a, v in C.APLICADORES.items() if v["linea"] == ln and v["familia"] == familia])
            if origen == "CUT":
                maquina = f"CUT-{ln}-01"
        if estacion is None:
            estacion = {"CRP": f"CRP-{ln}", "INS": f"INS-{ln}-0{rng.randint(1, 2)}", "CUT": f"CUT-{ln}-01",
                        "BRD": f"BRD-{ln}", "EMP": f"EMP-{ln}"}[origen]
        if deteccion is None:
            deteccion = elegir(rng, info["deteccion"])
        if cantidad is None:
            r = rng.random()
            cantidad = 1 if r < 0.8 else (2 if r < 0.95 else 3)
        lag = {"CLIENTE": rng.randint(3, 10), "LAB": rng.randint(0, 5)}.get(deteccion, 0)
        self.eventos.append({
            "fecha_fabricacion": d.isoformat(), "fecha_deteccion": (d + timedelta(days=lag)).isoformat(),
            "turno": t, "linea": ln, "estacion_origen": estacion, "aplicador_id": aplicador or "",
            "maquina_corte": maquina, "numero_parte": pn, "variante": arn["variante"],
            "cliente": C.CLIENTES[arn["cliente"]]["nombre"], "defecto_codigo": codigo,
            "defecto": info["descripcion"], "cantidad": cantidad, "numero_parte_terminal": terminal,
            "lote_terminal": lote_t, "numero_parte_cable": cable_t, "detectado_en": deteccion,
            "_episodio": episodio,
        })

    def generar_defectos(self):
        rng = self.rng
        fracciones = {"T1": 0.05, "T2": 0.38, "T3": 0.71}
        lote_h2, lote_e7 = self.lote_de_episodio("H2"), self.lote_de_episodio("E7")
        for d in dias(C.START, C.END):
            if not es_dia_produccion(d):
                continue
            for ln in C.LINEAS:
                for t in C.TURNOS:
                    # ruido base
                    for codigo, info in C.DEFECTOS.items():
                        for _ in range(poisson(rng, info["tasa"])):
                            self._evento(d, t, ln, codigo)
                    # RC-01: desgaste de aplicador (H1, E6)
                    for clave in ("H1", "E6"):
                        apl = EP[clave]["aplicador"]
                        if C.APLICADORES[apl]["linea"] != ln:
                            continue
                        ciclos, _ = self.ciclos_desde_pm(apl, d, fracciones[t])
                        dv = self.deriva(ciclos)
                        f = max(0.0, dv - 0.006) / 0.020
                        for codigo, k, det in (("DEF-01", 1.5, {"AUD": 0.45, "CLIENTE": 0.4, "INF": 0.15}),
                                               ("DEF-02", 1.0, {"TST": 0.55, "AUD": 0.45})):
                            for _ in range(poisson(rng, k * f)):
                                self._evento(d, t, ln, codigo, familia="A", aplicador=apl,
                                             deteccion=elegir(rng, det), episodio=clave)
                    # RC-02: lote de terminal con lanza deformada (H2, E7)
                    for clave, lote in (("H2", lote_h2), ("E7", lote_e7)):
                        a, b = EP[clave]["consumo"]
                        if a <= d <= b:
                            fam = EP[clave]["familia"]
                            esc = 1.0 if fam == "A" else 0.75
                            for codigo, k, det in (("DEF-04", 0.85, {"INF": 0.6, "CLIENTE": 0.4}),
                                                   ("DEF-01", 0.25, {"AUD": 0.4, "CLIENTE": 0.6}),
                                                   ("DEF-03", 0.20, {"TST": 0.8, "CLIENTE": 0.2})):
                                for _ in range(poisson(rng, k * esc)):
                                    self._evento(d, t, ln, codigo, familia=fam, lote=lote,
                                                 deteccion=elegir(rng, det), episodio=clave, origen="INS")
                    # RC-03: inserción sin verificación (E8)
                    ep = EP["E8"]
                    a, b = ep["ventana"]
                    if ln == "L1" and t == ep["turno"] and a <= d <= b:
                        progreso = (d - a).days / (b - a).days
                        lam = 1.7 * (1 - 0.55 * progreso)
                        for _ in range(poisson(rng, lam)):
                            codigo = elegir(rng, {"DEF-03": 0.5, "DEF-04": 0.3, "DEF-01": 0.2})
                            det = {"DEF-03": {"TST": 0.9, "CLIENTE": 0.1},
                                   "DEF-04": {"INF": 0.6, "CLIENTE": 0.4},
                                   "DEF-01": {"CLIENTE": 0.7, "AUD": 0.3}}[codigo]
                            self._evento(d, t, ln, codigo, estacion=ep["estacion"],
                                         deteccion=elegir(rng, det), episodio="E8", origen="INS")
                    # RC-04: receta de corte con desforre corto (H3, E9)
                    for clave in ("H3", "E9"):
                        ep = EP[clave]
                        a, b = ep["ventana"]
                        if ln in ep["linea"] and a <= d <= b:
                            for codigo, k, det in (("DEF-02", 0.9, {"TST": 0.9, "CLIENTE": 0.1}),
                                                   ("DEF-03", 0.45, {"TST": 0.85, "CLIENTE": 0.15}),
                                                   ("DEF-06", 0.12, {"LAB": 1.0})):
                                for _ in range(poisson(rng, k)):
                                    self._evento(d, t, ln, codigo, pn="B3-FDH-0451", familia="A",
                                                 cable="WIR-050",
                                                 estacion=ep["maquina"] if codigo == "DEF-06" else f"CRP-{ln}",
                                                 origen="CUT" if codigo == "DEF-06" else "CRP",
                                                 deteccion=elegir(rng, det), episodio=clave)
                    # RC-05: ECN no implementado (E10)
                    ep = EP["E10"]
                    a, b = ep["ventana"]
                    if a <= d <= b:
                        for _ in range(poisson(rng, 0.45)):
                            self._evento(d, t, ln, "DEF-07", pn="A7-DRH-2210-H",
                                         deteccion=elegir(rng, {"CLIENTE": 0.9, "AUD": 0.1}), episodio="E10")
                    # Ruido con 8D propio (N1, N2, N3)
                    for clave in ("N1", "N2", "N3"):
                        ep = EP[clave]
                        a, b = ep["ventana"]
                        if ln in ep["linea"] and a <= d <= b:
                            for _ in range(poisson(rng, 0.9)):
                                self._evento(d, t, ln, ep["defecto"], pn=ep.get("numero_parte"),
                                             episodio=clave)
        self.eventos.sort(key=lambda r: (r["fecha_fabricacion"], r["linea"], r["turno"], r["defecto_codigo"]))
        for i, r in enumerate(self.eventos, 1):
            r["evento_id"] = f"EV-{i:05d}"

    def generar(self):
        self.generar_produccion()
        self.generar_mantenimiento()
        self.generar_mediciones()
        self.generar_lotes()
        self.generar_cambios()
        self.generar_defectos()
        return self
