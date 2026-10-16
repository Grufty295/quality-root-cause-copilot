"""Línea base trivial: copiar la causa del 8D de la NCR histórica más parecida.

    docker compose exec api python -m app.evalkit.baseline        # o: make eval-baseline

Para cada caso de `casos_calidad.jsonl`, busca la NCR histórica con 8D (anterior a `as_of`)
cuya descripción más se parece (TF-IDF + coseno) y copia la RC y la ND de ese 8D. No usa el
modelo ni la base: lee los CSV y el corpus del dataset.

Es la vara que el gate `pass-linea-base` tiene que superar, y tiene que medirse sobre la MISMA
partición que el agente: en las 20 da 11/20 (11/12 recurrentes, 0/8 causa nueva), pero en dev
(E6, E7, E8) da 7/12. Comparar el agente en dev contra el 55 % de las 20 lo dejaría "pasar"
rindiendo menos que la línea base.

TF-IDF propio (sin scikit-learn) con los mismos valores por defecto que `TfidfVectorizer`:
minúsculas, tokens de 2+ caracteres de palabra, idf suavizado, norma L2. El resultado coincide
con el de scikit-learn en las 20.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from app.evalkit.qrels import split_of

DEFAULT_DATA = Path("/workspace/data/seed")
DEFAULT_EVALS = Path("/workspace/evals")

_TOKEN = re.compile(r"(?u)\b\w\w+\b")
_RC = re.compile(r"Fila del AMEF \| (RC-\d+)")
_ND = re.compile(r"\((ND-\d+)\)")


def _tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def _tfidf(docs: Sequence[str]) -> list[dict[str, float]]:
    toks = [_tokens(d) for d in docs]
    n = len(docs)
    df = Counter(t for ts in toks for t in set(ts))
    idf = {t: math.log((1 + n) / (1 + c)) + 1 for t, c in df.items()}
    out = []
    for ts in toks:
        tf = Counter(ts)
        vec = {t: c * idf[t] for t, c in tf.items()}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        out.append({t: v / norm for t, v in vec.items()})
    return out


def _cos(a: Mapping[str, float], b: Mapping[str, float]) -> float:
    if len(a) > len(b):
        a, b = b, a
    return sum(v * b.get(t, 0.0) for t, v in a.items())


def eight_d_causes(corpus_8d: Path) -> dict[str, tuple[str, str | None]]:
    """8D → (RC, ND) declarados en su ficha y su D4."""
    out: dict[str, tuple[str, str | None]] = {}
    for p in sorted(corpus_8d.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        rc = _RC.search(text)
        if rc is None:
            continue
        nd = _ND.search(text)
        out[p.stem] = (rc.group(1), nd.group(1) if nd else None)
    return out


def predict(
    case: Mapping[str, Any],
    history: Sequence[Mapping[str, str]],
    causes: Mapping[str, tuple[str, str | None]],
) -> dict[str, Any]:
    cand = [r for r in history if r.get("ocho_d") and r["fecha"] < case["as_of"]]
    if not cand:
        return {"ncr": None, "ocho_d": None, "rc": None, "nd": None}
    vecs = _tfidf([r["descripcion"] for r in cand] + [case["ncr"]["descripcion"]])
    query = vecs[-1]
    scores = [_cos(query, v) for v in vecs[:-1]]
    best = cand[
        max(range(len(cand)), key=scores.__getitem__)
    ]  # primer máximo, como argmax
    rc, nd = causes.get(best["ocho_d"], (None, None))
    return {"ncr": best["ncr_id"], "ocho_d": best["ocho_d"], "rc": rc, "nd": nd}


def score(cases: Iterable[Mapping[str, Any]], preds: Mapping[str, Mapping[str, Any]]):
    rows = []
    for c in cases:
        p, e = preds[c["caso_id"]], c["esperado"]
        rc_ok = p["rc"] == e["causa_ocurrencia"]
        nd_ok = p["nd"] in (
            e.get("no_deteccion_aceptables") or [e["causa_no_deteccion"]]
        )
        rows.append(
            {
                "caso_id": c["caso_id"],
                "episodio": c["episodio"],
                "split": split_of(c["episodio"]),
                "recurrent": bool(e["recurrente"]),
                "rc_top1": rc_ok,
                "pass": rc_ok and nd_ok,
                **p,
            }
        )
    return rows


def _macro(rows: Sequence[Mapping[str, Any]], key: str) -> float | None:
    """Promedio por episodio, igual que `_rate` del eval del agente."""
    by_ep: dict[str, list[float]] = {}
    for r in rows:
        by_ep.setdefault(r["episodio"], []).append(float(r[key]))
    if not by_ep:
        return None
    return sum(sum(v) / len(v) for v in by_ep.values()) / len(by_ep)


def summarize(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    out = {}
    for split in ("dev", "test", "all"):
        rs = [r for r in rows if split == "all" or r["split"] == split]
        rec = [r for r in rs if r["recurrent"]]
        new = [r for r in rs if not r["recurrent"]]
        out[split] = {
            "casos": len(rs),
            "pass": sum(r["pass"] for r in rs),
            "pass@1": _macro(rs, "pass"),
            "rc_top1_recurrent": f"{sum(r['rc_top1'] for r in rec)}/{len(rec)}",
            "rc_top1_new_cause": f"{sum(r['rc_top1'] for r in new)}/{len(new)}",
        }
    return out


def run(data_dir: Path, evals_dir: Path) -> dict[str, Any]:
    with (data_dir / "estructurados" / "ncr.csv").open(
        encoding="utf-8-sig", newline=""
    ) as fh:
        history = list(csv.DictReader(fh))
    causes = eight_d_causes(data_dir / "corpus" / "8d")
    cases = [
        json.loads(line)
        for line in (evals_dir / "casos_calidad.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    preds = {c["caso_id"]: predict(c, history, causes) for c in cases}
    rows = score(cases, preds)
    return {"summary": summarize(rows), "cases": rows}


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--data", type=Path, default=DEFAULT_DATA)
    ap.add_argument("--evals", type=Path, default=DEFAULT_EVALS)
    ap.add_argument(
        "--json", action="store_true", help="imprime el resultado completo en JSON"
    )
    args = ap.parse_args(argv)
    result = run(args.data, args.evals)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    print(
        "Línea base trivial (NCR más parecida con 8D, TF-IDF): pass = RC y ND correctas"
    )
    for split, s in result["summary"].items():
        print(
            f"  {split:<4} {s['pass']}/{s['casos']}  pass@1 {s['pass@1']:.3f}  "
            f"recurrentes {s['rc_top1_recurrent']}  causa nueva {s['rc_top1_new_cause']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
