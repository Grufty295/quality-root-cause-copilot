"""Valida que el dataset generado cumple lo que prometen los escenarios.

Uso: python data/generator/validate.py   (después de generate.py)
Sale con código 1 si alguna verificación falla.
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path
from statistics import mean

RAIZ = Path(__file__).resolve().parents[2]
EST = RAIZ / "data" / "seed" / "estructurados"
CORPUS = RAIZ / "data" / "seed" / "corpus"
EVALS = RAIZ / "evals"
PATRON = re.compile(r"Norvane|A7[-\s]?DRH|Halc[oó]n", re.IGNORECASE)

fallas, avisos = [], []


def leer(nombre):
    return list(csv.DictReader(open(EST / nombre, encoding="utf-8")))


def check(cond, msg):
    print(("  OK   " if cond else "  FALLA ") + msg)
    if not cond:
        fallas.append(msg)


def piezas(evs):
    return sum(int(e["cantidad"]) for e in evs)


def share(evs, campo, valor):
    tot = piezas(evs)
    return piezas([e for e in evs if (e[campo] in valor if isinstance(valor, (list, set)) else e[campo] == valor)]) / tot if tot else 0


ev = leer("eventos_defecto.csv")
med = leer("mediciones_crimpado.csv")
mant = leer("mantenimiento.csv")
lotes = leer("lotes_material.csv")
cambios = leer("cambios.csv")
ciclos = leer("ciclos_aplicador.csv")
verdad = json.load(open(EVALS / "episodios_verdad.json", encoding="utf-8"))
ids = {k: set(v["eventos"]) for k, v in verdad.items()}
por_id = {e["evento_id"]: e for e in ev}


def eventos_ventana(desde, hasta, lineas, codigos):
    return [e for e in ev if desde <= e["fecha_fabricacion"] <= hasta and e["linea"] in lineas
            and e["defecto_codigo"] in codigos]


def ciclos_desde_pm(apl, hasta):
    ult = max(m["fecha_ejecucion"] for m in mant if m["equipo_id"] == apl and m["estado"] == "Completada"
              and m["fecha_ejecucion"] <= hasta)
    return sum(int(c["ciclos"]) for c in ciclos if c["aplicador_id"] == apl and ult < c["fecha"] <= hasta), ult


print("\n== Firmas de los escenarios en los datos (incluye ruido base en la misma ventana)")
for k in ("H1", "E6"):
    v = verdad[k]
    apl, ln = v["aplicador"], v["linea"][0]
    evs = eventos_ventana(v["fabricacion_desde"], v["fabricacion_hasta"], [ln], {"DEF-01", "DEF-02"})
    check(share(evs, "aplicador_id", apl) > 0.7, f"{k}: DEF-01/02 en {ln} concentrados en {apl} "
          f"({share(evs, 'aplicador_id', apl):.0%})")
    turnos = Counter()
    for e in evs:
        if e["aplicador_id"] == apl:
            turnos[e["turno"]] += int(e["cantidad"])
    check(max(turnos.values()) / sum(turnos.values()) < 0.5, f"{k}: sin concentración por turno {dict(turnos)}")
    base = mean(float(m["altura_mm"]) for m in med if m["aplicador_id"] == apl and m["fecha"] < "2026-04-15")
    fin = mean(float(m["altura_mm"]) for m in med if m["aplicador_id"] == apl
               and v["fabricacion_hasta"][:8] <= m["fecha"] <= v["fabricacion_hasta"] and m["fecha"] >= v["fabricacion_desde"])
    check(fin - base > 0.01, f"{k}: altura de {apl} sube {fin - base:+.3f} mm contra su base")
    c, ult = ciclos_desde_pm(apl, v["fabricacion_hasta"])
    check(c > 250_000, f"{k}: {c:,} ciclos desde el PM del {ult} (umbral 250,000)")
    check(any(m["equipo_id"] == apl and m["estado"] in ("Reprogramada", "Pendiente") for m in mant),
          f"{k}: OTs reprogramadas registradas para {apl}")

for k in ("H2", "E7"):
    v = verdad[k]
    evs = eventos_ventana(v["consumo"][0], v["consumo"][1], ["L1", "L2"], {"DEF-04"})
    fam_tp = "TRM-A-1064" if v["familia"] == "A" else "TRM-B-2150"
    check(share(evs, "lote_terminal", v["lote"]) > 0.7, f"{k}: DEF-04 concentrados en lote {v['lote']} "
          f"({share(evs, 'lote_terminal', v['lote']):.0%})")
    del_lote = [e for e in evs if e["lote_terminal"] == v["lote"]]
    check(min(share(del_lote, "linea", "L1"), share(del_lote, "linea", "L2")) > 0.25, f"{k}: aparece en ambas líneas")
    est = Counter(e["estacion_origen"] for e in del_lote)
    check(max(est.values()) / sum(est.values()) < 0.45, f"{k}: sin concentración por estación {dict(est)}")
    lote = next(l for l in lotes if l["lote_id"] == v["lote"])
    check(lote["tipo_inspeccion"].startswith("Certificado"), f"{k}: lote aceptado por certificado ({lote['tipo_inspeccion']})")

v = verdad["E8"]
evs = eventos_ventana(v["ventana"][0], v["ventana"][1], ["L1"], {"DEF-03", "DEF-04"})
evs_ep = [e for e in evs if e["estacion_origen"] == "INS-L1-02" and e["turno"] == "T3"]
check(piezas(evs_ep) / piezas(evs) > 0.5, f"E8: DEF-03/04 de L1 concentrados en INS-L1-02 T3 ({piezas(evs_ep) / piezas(evs):.0%})")
check(any(c["fecha"] == "2026-08-03" and c["tipo"] == "Cambio de mano de obra" for c in cambios),
      "E8: cambio de mano de obra registrado el 3 de agosto")

for k in ("H3", "E9"):
    v = verdad[k]
    ln = v["linea"][0]
    evs = eventos_ventana(v["ventana"][0], v["ventana"][1], [ln], {"DEF-02", "DEF-03"})
    check(share(evs, "numero_parte_cable", "WIR-050") > 0.6, f"{k}: DEF-02/03 de {ln} concentrados en WIR-050 "
          f"({share(evs, 'numero_parte_cable', 'WIR-050'):.0%})")
    check(any(c["fecha"] == v["ventana"][0] and c["equipo_id"] == v["maquina"] for c in cambios),
          f"{k}: cambio de receta en {v['maquina']} el {v['ventana'][0]}")
    apls = Counter(e["aplicador_id"] for e in evs if e["numero_parte_cable"] == "WIR-050")
    check(len(apls) >= 2, f"{k}: repartido en varios aplicadores {dict(apls)}")

v = verdad["E10"]
evs = [e for e in ev if v["ventana"][0] <= e["fecha_fabricacion"] <= v["ventana"][1] and e["defecto_codigo"] == "DEF-07"]
check(share(evs, "variante", "Alta") > 0.8, f"E10: DEF-07 concentrado en variante Alta ({share(evs, 'variante', 'Alta'):.0%})")
check(min(share(evs, "linea", "L1"), share(evs, "linea", "L2")) > 0.25, "E10: aparece en ambas líneas")
check(any("ECN-2026-031" in c["descripcion"] and c["tablero_actualizado"].startswith("No") for c in cambios),
      "E10: ECN-2026-031 registrado sin tablero actualizado")

print("\n== Casos de evaluación")
casos = [json.loads(l) for l in open(EVALS / "casos_calidad.jsonl", encoding="utf-8")]
textos_ncr = {r["descripcion"] for r in leer("ncr.csv")}
for c in casos:
    ep = c["episodio"]
    previos = [por_id[i] for i in ids[ep] if por_id[i]["fecha_deteccion"] <= c["as_of"]]
    check(len(previos) >= 2, f"{c['caso_id']} ({ep}): {len(previos)} eventos del episodio visibles al {c['as_of']}")
    check(c["ncr"]["descripcion"] not in textos_ncr, f"{c['caso_id']}: la NCR de evaluación no está en el corpus")
    od = c["esperado"]["ocho_d_relacionado"]
    if od:
        meta = (CORPUS / "8d" / f"{od}.md").read_text(encoding="utf-8")
        cierre = re.search(r"^fecha: (\S+)", meta, re.M).group(1)
        check(cierre < c["as_of"], f"{c['caso_id']}: {od} cerrado ({cierre}) antes de la NCR")
    nivel = "confidencial" if PATRON.search(c["ncr"]["numero_parte"] + c["ncr"]["cliente"] + c["ncr"]["descripcion"]) else "interno"
    check(nivel == c["esperado"]["nivel_minimo_contexto"], f"{c['caso_id']}: nivel mínimo {nivel}")

print("\n== Corpus")
docs = sorted(CORPUS.rglob("*.md"))
for f in docs:
    texto = f.read_text(encoding="utf-8")
    meta = dict(re.findall(r"^(\w+): (.*)$", texto.split("---")[1], re.M))
    cuerpo = texto.split("---", 2)[2]
    if PATRON.search(cuerpo) and meta.get("confidencialidad") != "confidencial":
        fallas.append(f"{f.name}: menciona datos del cliente confidencial y está marcado {meta.get('confidencialidad')}")
    if meta.get("tipo") == "NCR" and re.search(r"RC-\d\d|ND-\d\d", cuerpo):
        fallas.append(f"{f.name}: una NCR no debe contener códigos de causa")
check(not any("menciona datos" in x or "códigos de causa" in x for x in fallas),
      f"{len(docs)} documentos: clasificación consistente y NCRs sin códigos de causa")
niveles = Counter(re.search(r"^confidencialidad: (\S+)", f.read_text(encoding='utf-8'), re.M).group(1) for f in docs)
print(f"  Niveles: {dict(niveles)}")
check(all(re.search(r"^lineas: \[", f.read_text(encoding="utf-8"), re.M) for f in docs), "todos los documentos tienen líneas")

print(f"\n{len(fallas)} fallas")
sys.exit(1 if fallas else 0)
