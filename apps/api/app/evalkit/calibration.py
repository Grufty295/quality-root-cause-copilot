"""Calibración del juez de citas contra etiquetas humanas.

Un juez LLM no es la verdad: es un instrumento que hay que medir antes de usarlo. El flujo:

1. `python -m app.evalkit.semantic --export-labels 40` escribe una muestra de hechos al azar
   en `data/etiquetas/<nombre>.por_etiquetar.jsonl`, **sin** la etiqueta del juez (para no
   anclar al revisor).
2. Un ingeniero de calidad llena `etiqueta_humana` (respaldada / parcial / sin_respaldo /
   contradice) y `revisor`, y guarda el archivo como `<nombre>.etiquetas.jsonl`. Si dos
   revisores etiquetan los mismos hechos, se mide también su acuerdo entre sí: es el techo de
   lo que se le puede pedir al juez.
3. `semantic.py` empareja por `id` y calcula acuerdo, kappa de Cohen, matriz de confusión y,
   por etiqueta, cuántas veces el juez dice "respaldada" cuando el humano no (el error caro:
   deja pasar una cita que no sostiene nada).

Criterio: `calibrated` = al menos `MIN_LABELS` hechos emparejados y kappa ≥ `MIN_KAPPA`. Hasta
entonces el gate de citas no cuenta. Se recalibra al cambiar el modelo del juez o el prompt.

Las etiquetas viven en `data/etiquetas/`, fuera de `evals/` (que `generate.py` borra al
regenerar el dataset). Son trabajo humano: se versionan.
"""

from __future__ import annotations

import json
import random
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

LABELS = ("respaldada", "parcial", "sin_respaldo", "contradice")
MIN_LABELS = 30
MIN_KAPPA = 0.6
DEFAULT_LABELS_DIR = Path("/workspace/data/etiquetas")


def export_sample(claims: Sequence[Any], n: int, path: Path, seed: int = 0) -> Path:
    rng = random.Random(seed)
    picked = rng.sample(list(claims), min(n, len(claims)))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for c in picked:
            fh.write(
                json.dumps(
                    {
                        "id": c.id,
                        "caso_id": c.caso_id,
                        "tipo": c.kind,
                        "afirmacion": c.texto,
                        "fuentes": dict(zip(c.fuentes, c.contextos, strict=True)),
                        "etiqueta_humana": None,
                        "revisor": None,
                        "nota": None,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return path


def load_labels(path: Path) -> dict[str, dict[str, str]]:
    """id → {revisor: etiqueta}. Ignora líneas sin etiqueta o con una desconocida."""
    out: dict[str, dict[str, str]] = defaultdict(dict)
    if not path.exists():
        return {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        label = row.get("etiqueta_humana")
        if label in LABELS:
            out[row["id"]][row.get("revisor") or "anon"] = label
    return dict(out)


def cohen_kappa(pairs: Sequence[tuple[str, str]]) -> float | None:
    n = len(pairs)
    if n == 0:
        return None
    observed = sum(1 for a, b in pairs if a == b) / n
    ca, cb = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1 - expected)


def calibrate(
    judge: Mapping[str, str], human: Mapping[str, Mapping[str, str]]
) -> dict[str, Any]:
    """`judge`: id → etiqueta del juez. `human`: id → {revisor: etiqueta}.

    Contra el juez se usa la etiqueta del primer revisor (orden alfabético) de cada hecho; si
    hay dos o más revisores, su acuerdo mutuo sale aparte."""
    pairs: list[tuple[str, str]] = []
    for cid, by_rev in human.items():
        if cid in judge and by_rev:
            pairs.append((by_rev[min(by_rev)], judge[cid]))
    confusion: dict[str, dict[str, int]] = {h: dict.fromkeys(LABELS, 0) for h in LABELS}
    for h, j in pairs:
        confusion[h][j] += 1
    n = len(pairs)
    kappa = cohen_kappa(pairs)
    accuracy = sum(1 for h, j in pairs if h == j) / n if n else None
    # El error caro: el juez aprueba una cita que el humano no aprueba.
    judge_ok = [(h, j) for h, j in pairs if j == "respaldada"]
    false_support = (
        sum(1 for h, _ in judge_ok if h != "respaldada") / len(judge_ok)
        if judge_ok
        else None
    )
    human_ok = [(h, j) for h, j in pairs if h == "respaldada"]
    missed_support = (
        sum(1 for _, j in human_ok if j != "respaldada") / len(human_ok)
        if human_ok
        else None
    )
    inter = [
        (by_rev[a], by_rev[b])
        for by_rev in human.values()
        if len(by_rev) >= 2
        for a, b in [sorted(by_rev)[:2]]
    ]
    return {
        "n": n,
        "accuracy": accuracy,
        "kappa": kappa,
        "false_support_rate": false_support,
        "missed_support_rate": missed_support,
        "confusion_humano_x_juez": confusion,
        "inter_rater_n": len(inter),
        "inter_rater_kappa": cohen_kappa(inter),
        "calibrated": n >= MIN_LABELS and kappa is not None and kappa >= MIN_KAPPA,
        "criterio": f"n ≥ {MIN_LABELS} y kappa ≥ {MIN_KAPPA}",
    }


def judge_labels(judged: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    return {c["id"]: c["label"] for r in judged for c in r["claims"] if c.get("label")}


def calibrate_report(
    judged: Sequence[Mapping[str, Any]], labels_path: Path
) -> dict[str, Any]:
    human = load_labels(labels_path)
    out = calibrate(judge_labels(judged), human)
    out["labels_file"] = str(labels_path)
    out["human_labels"] = len(human)
    return out
