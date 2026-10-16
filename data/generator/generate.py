"""Genera el corpus y los datos sintéticos del Agente 8D.

Uso:
    python data/generator/generate.py            # semilla 42 por defecto
    python data/generator/generate.py --seed 7

Salidas:
    data/seed/estructurados/*.csv   datos que consultan las tools
    data/seed/corpus/**.md          documentos que se indexan para el RAG (con metadatos en front matter)
    evals/*                         casos de evaluación y verdad de fondo (nunca se indexan)
"""

import argparse
import csv
import json
import shutil
from datetime import date
from pathlib import Path

import config as C
import documentos as D
import estructurados as E
import evals as V
from episodios import EPISODIOS

RAIZ = Path(__file__).resolve().parents[2]
SEED_DIR = RAIZ / "data" / "seed"
EST = SEED_DIR / "estructurados"
CORPUS = SEED_DIR / "corpus"
EVALS = RAIZ / "evals"
ESTATICOS = RAIZ / "data" / "static_docs"


def escribir_csv(ruta, filas, campos=None):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if not filas:
        return
    campos = campos or [k for k in filas[0] if not k.startswith("_")]
    with open(ruta, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader()
        w.writerows(filas)


def escribir_jsonl(ruta, filas):
    ruta.parent.mkdir(parents=True, exist_ok=True)
    with open(ruta, "w", encoding="utf-8") as f:
        for r in filas:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def serial(o):
    if isinstance(o, date):
        return o.isoformat()
    if isinstance(o, (set, tuple)):
        return list(o)
    raise TypeError(type(o))


def catalogos():
    equipos = []
    for apl, v in C.APLICADORES.items():
        equipos.append({"equipo_id": apl, "tipo": "Aplicador", "linea": v["linea"], "familia_terminal": v["familia"],
                        "numero_parte_terminal": C.TERMINAL_POR_FAMILIA[v["familia"]], "aloja_en": v["prensa"],
                        "umbral_pm_ciclos": C.UMBRAL_PM_CICLOS})
    for ln in C.LINEAS:
        for p in ("01", "02"):
            equipos.append({"equipo_id": f"PRS-{ln}-{p}", "tipo": "Prensa de crimpado", "linea": ln})
        equipos.append({"equipo_id": f"CUT-{ln}-01", "tipo": "Máquina de corte y desforre", "linea": ln})
        for p in ("01", "02"):
            equipos.append({"equipo_id": f"INS-{ln}-{p}", "tipo": "Estación de inserción y TPA", "linea": ln})
        for est, tipo in (("BRD", "Tablero de ensamble"), ("TST", "Probador eléctrico"), ("INF", "Inspección final"),
                          ("EMP", "Empaque")):
            equipos.append({"equipo_id": f"{est}-{ln}", "tipo": tipo, "linea": ln})
    campos_eq = ["equipo_id", "tipo", "linea", "familia_terminal", "numero_parte_terminal", "aloja_en", "umbral_pm_ciclos"]

    partes = []
    for pn, a in C.ARNESES.items():
        cli = C.CLIENTES[a["cliente"]]
        partes.append({"numero_parte": pn, "tipo": "Arnés", "descripcion": f"Arnés de puerta delantera, variante {a['variante']}",
                       "variante": a["variante"], "cliente": cli["nombre"], "confidencialidad": cli["confidencialidad"],
                       "terminales_familia_A": a["term_A"], "terminales_familia_B": a["term_B"],
                       "cables": " ".join(a["cables"])})
    for pn, t in C.TERMINALES.items():
        partes.append({"numero_parte": pn, "tipo": "Terminal", "descripcion": t["descripcion"],
                       "confidencialidad": "interno"})
    for pn, c in C.CABLES.items():
        partes.append({"numero_parte": pn, "tipo": "Cable", "descripcion": f"Cable automotriz {c['seccion']} mm²",
                       "confidencialidad": "interno"})
    campos_pn = ["numero_parte", "tipo", "descripcion", "variante", "cliente", "confidencialidad",
                 "terminales_familia_A", "terminales_familia_B", "cables"]

    proveedores = [{"proveedor_id": k, "nombre": v["nombre"], "categoria": v["categoria"],
                    "suministra": "TRM-A-1064, TRM-B-2150"} for k, v in C.PROVEEDORES.items()]
    defectos = [{"defecto_codigo": k, "descripcion": v["descripcion"], "estacion_origen_tipica": v["origen"]}
                for k, v in C.DEFECTOS.items()]
    usuarios = [{**u, "lineas": " ".join(u["lineas"])} for u in C.USUARIOS]
    clientes = [{"cliente_id": k, **v} for k, v in C.CLIENTES.items()]

    escribir_csv(EST / "catalogo_equipos.csv", equipos, campos_eq)
    escribir_csv(EST / "catalogo_numeros_parte.csv", partes, campos_pn)
    escribir_csv(EST / "catalogo_proveedores.csv", proveedores)
    escribir_csv(EST / "catalogo_defectos.csv", defectos)
    escribir_csv(EST / "catalogo_clientes.csv", clientes)
    escribir_csv(EST / "usuarios_demo.csv", usuarios)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", type=int, default=C.SEED)
    args = ap.parse_args()

    for d in (SEED_DIR, EVALS):
        if d.exists():
            shutil.rmtree(d)

    mundo = E.Mundo(args.seed).generar()
    docs = D.Documentos(mundo).generar()

    # ---- estructurados
    catalogos()
    escribir_csv(EST / "produccion.csv", mundo.produccion)
    escribir_csv(EST / "eventos_defecto.csv", mundo.eventos,
                 ["evento_id", "fecha_fabricacion", "fecha_deteccion", "turno", "linea", "estacion_origen",
                  "aplicador_id", "maquina_corte", "numero_parte", "variante", "cliente", "defecto_codigo", "defecto",
                  "cantidad", "numero_parte_terminal", "lote_terminal", "numero_parte_cable", "detectado_en"])
    escribir_csv(EST / "mediciones_crimpado.csv", mundo.mediciones)
    escribir_csv(EST / "ciclos_aplicador.csv",
                 [{"fecha": d.isoformat(), "aplicador_id": a, "ciclos": c} for (a, d), c in sorted(mundo.ciclos.items(),
                                                                                                key=lambda x: (x[0][1], x[0][0]))])
    escribir_csv(EST / "mantenimiento.csv", mundo.mantenimiento)
    escribir_csv(EST / "lotes_material.csv", mundo.lotes)
    escribir_csv(EST / "cambios.csv", mundo.cambios)
    escribir_csv(EST / "ncr.csv", docs.ncrs,
                 ["ncr_id", "fecha", "linea", "turno", "detectado_en", "origen", "cliente", "numero_parte", "variante",
                  "defecto_codigo", "defecto", "cantidad", "descripcion", "contencion", "disposicion",
                  "causa_preliminar", "estado", "ocho_d", "reportado_por", "confidencialidad"])

    # ---- corpus para RAG
    (CORPUS / "documentos").mkdir(parents=True, exist_ok=True)
    for f in sorted(ESTATICOS.glob("*.md")):
        shutil.copy(f, CORPUS / "documentos" / f.name)
    (CORPUS / "ncr").mkdir(parents=True, exist_ok=True)
    for r in docs.ncrs:
        (CORPUS / "ncr" / f"{r['ncr_id']}.md").write_text(docs.ncr_markdown(r), encoding="utf-8")
    (CORPUS / "8d").mkdir(parents=True, exist_ok=True)
    for doc_id, (meta, texto) in docs.ochod.items():
        (CORPUS / "8d" / f"{doc_id}.md").write_text(D.front_matter(meta) + texto + "\n", encoding="utf-8")

    # ---- evals (fuera del índice)
    escribir_jsonl(EVALS / "casos_calidad.jsonl", V.CASOS_CALIDAD)
    escribir_jsonl(EVALS / "casos_adversariales.jsonl", V.CASOS_ADVERSARIALES)
    escribir_jsonl(EVALS / "casos_permisos.jsonl", V.CASOS_PERMISOS)
    (EVALS / "documentos_adversariales").mkdir(parents=True, exist_ok=True)
    for doc_id, d in V.DOCUMENTOS_ADVERSARIALES.items():
        (EVALS / "documentos_adversariales" / f"{doc_id}.md").write_text(
            D.front_matter(d["meta"]) + d["texto"], encoding="utf-8")
    verdad = {}
    for k, ep in EPISODIOS.items():
        evs = [e for e in mundo.eventos if e["_episodio"] == k]
        verdad[k] = {**ep, "piezas": sum(e["cantidad"] for e in evs),
                     "fabricacion_desde": min(e["fecha_fabricacion"] for e in evs),
                     "fabricacion_hasta": max(e["fecha_fabricacion"] for e in evs),
                     "eventos": [e["evento_id"] for e in evs],
                     "ncrs_historicas": docs.ncr_por_ep.get(k, [])}
        if k in ("H2", "E7"):
            verdad[k]["lote"] = mundo.lote_de_episodio(k)
    (EVALS / "episodios_verdad.json").write_text(json.dumps(verdad, ensure_ascii=False, indent=2, default=serial),
                                                  encoding="utf-8")

    print(f"Producción: {len(mundo.produccion)} filas | eventos de defecto: {len(mundo.eventos)} | "
          f"mediciones: {len(mundo.mediciones)} | OTs: {len(mundo.mantenimiento)} | lotes: {len(mundo.lotes)} | "
          f"cambios: {len(mundo.cambios)}")
    print(f"NCRs: {len(docs.ncrs)} | 8Ds: {len(docs.ochod)} | documentos estáticos: "
          f"{len(list(ESTATICOS.glob('*.md')))}")
    print(f"Evals: {len(V.CASOS_CALIDAD)} calidad, {len(V.CASOS_ADVERSARIALES)} adversariales, "
          f"{len(V.CASOS_PERMISOS)} permisos")


if __name__ == "__main__":
    main()
