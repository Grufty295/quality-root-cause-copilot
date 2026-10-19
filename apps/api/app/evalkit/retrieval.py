"""Eval de recuperación: ¿las dos búsquedas del agente traen lo que D4 necesita?

    docker compose exec api python -m app.evalkit.retrieval            # solo dev
    docker compose exec api python -m app.evalkit.retrieval --test     # añade la partición sellada

Corre contra la base ya sembrada con el embedder real: lo que se mide es el índice que usa el
agente (chunker + embedder + RRF). Usa la misma consulta (`graph.build_query`), los mismos
tipos de documento y el mismo corte `as_of` que el agente, y el usuario del caso, así que los
permisos también cuentan. Para comparar configuraciones (re-ranking, otro chunking, otro
embedder) se siembra una base por configuración y se corre esto contra cada una.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import Connection, text

from app.agent.graph import QUERY_CHARS, build_query
from app.agent.tools import CASE_KINDS, CONTROL_KINDS
from app.evalkit import metrics as m
from app.evalkit.qrels import (
    AMEF_KEY,
    DEV_EPISODES,
    TEST_EPISODES,
    Qrel,
    anchor_of,
    build_qrels,
)
from app.retrieval.models import SearchMode, SearchQuery
from app.retrieval.service import RetrievalService

DEFAULT_EVALS = Path("/workspace/evals")
DEFAULT_OUT = Path("/workspace/traces/evals")
MODES: tuple[SearchMode, ...] = ("text", "vector", "hybrid")
KS = (5, 10)
FETCH = max(KS)
KINDS = {"cases": CASE_KINDS, "controls": CONTROL_KINDS}
AGENT_TOP_K = {
    "cases": 5,
    "controls": 6,
}  # lo que el agente realmente pide (tools.search_*)


@dataclass(frozen=True)
class Ranked:
    """Un fragmento recuperado, reducido a lo que la métrica necesita."""

    source_key: str
    section: str
    kind: str


@dataclass(frozen=True)
class CaseRow:
    caso_id: str
    episodio: str
    split: str
    search: str
    mode: str
    metrics: Mapping[str, float | None]
    top: tuple[str, ...]
    """Primeras posiciones como `documento#sección`, para ver qué trajo (y qué no) sin repetir la corrida."""
    missing: tuple[str, ...]
    """Anclas esenciales que no salieron en los primeros 10."""


def score(
    ranked: Sequence[Ranked], qrel: Qrel
) -> tuple[dict[str, float | None], tuple[str, ...]]:
    """Métricas de un caso para una búsqueda. Pura: se prueba sin base."""
    keys = [anchor_of(r.source_key, r.section, qrel.grades) for r in ranked]
    out: dict[str, float | None] = {"mrr": m.reciprocal_rank(keys, qrel.grades)}
    for k in KS:
        out[f"recall@{k}"] = m.recall_at_k(keys, qrel.grades, k)
        out[f"hit@{k}"] = m.hit_at_k(keys, qrel.grades, k)
        out[f"ndcg@{k}"] = m.ndcg_at_k(keys, qrel.grades, k)
        out[f"precision@{k}"] = m.precision_at_k(keys, qrel.grades, k)
    if qrel.precedent:
        # ¿Salió el 8D precedente, en cualquier sección? Es lo que el agente necesita para citarlo.
        for k in KS:
            top = ranked[:k]
            direct = any(r.source_key == qrel.precedent for r in top)
            out[f"precedent@{k}"] = 1.0 if direct else 0.0
            # Con un salto: una NCR del top que cita el 8D (lo que haría una expansión por enlace).
            linked = direct or any(r.source_key in qrel.precedent_links for r in top)
            out[f"precedent_link@{k}"] = 1.0 if linked else 0.0
    else:
        for k in KS:
            out[f"precedent@{k}"] = None
            out[f"precedent_link@{k}"] = None
    if qrel.distractor_kinds:
        # Un caso sin recurrencia no debería traer un 8D de otra causa: el agente lo leería como precedente.
        top = ranked[: KS[0]]
        out["distractor@5"] = (
            1.0 if any(r.kind in qrel.distractor_kinds for r in top) else 0.0
        )
    if qrel.search == "cases":
        # 8D de OTRA causa alcanzables desde el top-5, directo o por una NCR que lo cita. Si se
        # agrega una expansión por enlace, esto es lo que el modelo tendría que descartar.
        top = ranked[: KS[0]]
        reach = {r.source_key for r in top if r.kind == "8d"}
        reach |= {qrel.cites[r.source_key] for r in top if r.source_key in qrel.cites}
        out["wrong_8d_link@5"] = 1.0 if reach - {qrel.precedent} else 0.0
    essential = {a for a, g in qrel.grades.items() if g >= 2}
    found = set(keys)
    missing = tuple(sorted(a.label() for a in essential - found))
    return out, missing


def aggregate(rows: Iterable[CaseRow]) -> list[dict[str, Any]]:
    """Promedio por (búsqueda, modo, partición) a dos niveles: por caso y por episodio.

    Los 4 casos de un episodio comparten causa, línea y 8D: no son 4 muestras independientes.
    El promedio por episodio (macro) es el número honesto; el de casos solo sirve de referencia.
    """
    groups: dict[tuple[str, str, str], list[CaseRow]] = defaultdict(list)
    for r in rows:
        groups[(r.search, r.mode, r.split)].append(r)
        groups[(r.search, r.mode, "all")].append(r)
    out = []
    for (search, mode, split), rs in sorted(groups.items()):
        names = sorted({k for r in rs for k in r.metrics})
        by_case = {n: m.mean([r.metrics.get(n) for r in rs]) for n in names}
        episodes: dict[str, list[CaseRow]] = defaultdict(list)
        for r in rs:
            episodes[r.episodio].append(r)
        by_episode = {
            n: m.mean(
                [m.mean([r.metrics.get(n) for r in grp]) for grp in episodes.values()]
            )
            for n in names
        }
        out.append(
            {
                "search": search,
                "mode": mode,
                "split": split,
                "n_cases": len({r.caso_id for r in rs}),
                "n_episodes": len(episodes),
                "por_caso": by_case,
                "por_episodio": by_episode,
            }
        )
    return out


def run_retrieval_eval(
    conn: Connection,
    service: RetrievalService,
    users: Callable[[str], Any],
    cases: Sequence[Mapping[str, Any]],
    qrels: Sequence[Qrel],
    modes: Sequence[str] = MODES,
) -> list[CaseRow]:
    by_id = {c["caso_id"]: c for c in cases}
    rows: list[CaseRow] = []
    for q in qrels:
        case = by_id[q.caso_id]
        ncr = case["ncr"]
        query = build_query(ncr["descripcion"], ncr.get("numero_parte") or None)
        user = users(case["usuario"]["usuario_id"])
        as_of = date.fromisoformat(case["as_of"])

        for mode in modes:
            hits = service.search(
                user,
                SearchQuery(
                    text=query,
                    top_k=FETCH,
                    mode=mode,  # type: ignore[arg-type]
                    as_of=as_of,
                    kinds=KINDS[q.search],
                ),
            )
            ranked = [Ranked(h.source_key, h.section, h.kind.value) for h in hits]
            metrics_, missing = score(ranked, q)
            rows.append(
                CaseRow(
                    q.caso_id,
                    q.episodio,
                    q.split,
                    q.search,
                    mode,
                    metrics_,
                    tuple(f"{r.source_key}#{r.section}" for r in ranked),
                    missing,
                )
            )
    return rows


# ------------------------------------------------------------------ datos y validación


def load_cases(evals_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    raw = (evals_dir / "casos_calidad.jsonl").read_bytes()
    cases = [
        json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()
    ]
    episodios = json.loads(
        (evals_dir / "episodios_verdad.json").read_text(encoding="utf-8")
    )
    return cases, episodios, hashlib.sha256(raw).hexdigest()[:12]


def doc_dates(conn: Connection) -> dict[str, date | None]:
    return {
        r.source_key: r.doc_date
        for r in conn.execute(text("SELECT source_key, doc_date FROM document"))
    }


def _norm(code: str) -> str:
    return "".join(ch for ch in code.lower() if ch.isalnum())


def control_links(conn: Connection) -> dict[str, tuple[str, ...]]:
    """RC-xx → documentos de control que su fila del AMEF referencia (columna `codes` del fragmento)."""
    controls = {
        _norm(r.source_key): r.source_key
        for r in conn.execute(
            text(
                "SELECT source_key FROM document WHERE kind::text = ANY(:kinds) AND source_key <> :amef"
            ),
            {"kinds": [k.value for k in CONTROL_KINDS], "amef": AMEF_KEY},
        )
    }
    out: dict[str, tuple[str, ...]] = {}
    for r in conn.execute(
        text(
            "SELECT f.section, f.codes FROM fragment f JOIN document d ON d.id = f.document_id "
            "WHERE d.source_key = :amef AND f.section LIKE 'RC-%'"
        ),
        {"amef": AMEF_KEY},
    ):
        docs = sorted({controls[t] for t in r.codes.split() if t in controls})
        out[r.section] = tuple(docs)
    return out


def check_anchors(conn: Connection, qrels: Iterable[Qrel]) -> list[str]:
    """Todo ancla del qrel debe existir en el índice: si no, el caso mediría un 0 por un error de datos."""
    present = {
        (r.source_key, r.section)
        for r in conn.execute(
            text(
                "SELECT d.source_key, f.section FROM fragment f JOIN document d ON d.id = f.document_id"
            )
        )
    }
    docs = {k for k, _ in present}
    problems = []
    for q in qrels:
        for a in q.grades:
            ok = (
                a.source_key in docs
                if a.section is None
                else (a.source_key, a.section) in present
            )
            if not ok:
                problems.append(
                    f"{q.caso_id}/{q.search}: ancla {a.label()} no está en el índice"
                )
    return sorted(set(problems))


# ------------------------------------------------------------------ reporte


def render_markdown(report: Mapping[str, Any]) -> str:
    meta = report["meta"]
    lines = [
        "# Eval de recuperación",
        "",
        f"- Índice: `{meta['index_version']}` · embedder `{meta['embedder']}`",
        f"- Dataset: `casos_calidad.jsonl` sha `{meta['dataset_sha']}` · consulta ≤ {meta['query_chars']} caracteres",
        f"- Particiones incluidas: {', '.join(meta['splits'])} · {meta['generated_at']}",
        "",
        (
            "Promedio **por episodio** (los 4 casos de un episodio no son independientes). "
            "`precedente@k` = salió algún fragmento del 8D del que el caso es recurrencia; `prec. vía NCR@5` = el 8D o una NCR que lo cita; `hit@k` = salió un ancla esencial (en `cases`, la sección D4 con la causa; en `controls`, un documento de control que la fila RC referencia); `recall@k` cuenta también las útiles."
        ),
        "",
    ]
    if "test" in meta["splits"]:
        lines += [
            "> La partición `test` está incluida. No se ajusta nada con estos números.",
            "",
        ]
    for search in ("cases", "controls"):
        lines += [
            f"## Búsqueda `{search}` (el agente pide top_k={AGENT_TOP_K[search]})",
            "",
            "| split | modo | eps | casos | precedente@5 | precedente@10 | prec. vía NCR@5 | hit@5 | hit@10 | recall@5 | recall@10 | MRR | nDCG@10 | prec@5 | 8D distractor@5 | 8D ajeno vía NCR@5 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for a in report["aggregates"]:
            if a["search"] != search:
                continue
            e = a["por_episodio"]

            def f(key: str, e: Mapping[str, float | None] = e) -> str:
                v = e.get(key)
                return "—" if v is None else f"{v:.2f}"

            lines.append(
                f"| {a['split']} | {a['mode']} | {a['n_episodes']} | {a['n_cases']} | {f('precedent@5')} | {f('precedent@10')} | {f('precedent_link@5')} | {f('hit@5')} | {f('hit@10')} "
                f"| {f('recall@5')} | {f('recall@10')} | {f('mrr')} | {f('ndcg@10')} | {f('precision@5')} | {f('distractor@5')} | {f('wrong_8d_link@5')} |"
            )
        lines.append("")
    misses = [r for r in report["casos"] if r["missing"] and r["mode"] == "hybrid"]
    if misses:
        lines += ["## Fallos (híbrida): anclas esenciales fuera del top-10", ""]
        lines += [
            f"- {r['caso_id']} ({r['episodio']}) · {r['search']}: {', '.join(r['missing'])}"
            for r in misses
        ]
        lines.append("")
    return "\n".join(lines)


def build_report(
    rows: Sequence[CaseRow],
    *,
    index_version: str,
    embedder: str,
    dataset_sha: str,
    splits: Sequence[str],
) -> dict[str, Any]:
    return {
        "meta": {
            "index_version": index_version,
            "embedder": embedder,
            "dataset_sha": dataset_sha,
            "query_chars": QUERY_CHARS,
            "ks": list(KS),
            "splits": list(splits),
            "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        },
        "aggregates": aggregate(rows),
        "casos": [
            {
                "caso_id": r.caso_id,
                "episodio": r.episodio,
                "split": r.split,
                "search": r.search,
                "mode": r.mode,
                "metrics": dict(r.metrics),
                "missing": list(r.missing),
                "top": list(r.top),
            }
            for r in rows
        ],
    }


# ------------------------------------------------------------------ CLI


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--evals",
        type=Path,
        default=DEFAULT_EVALS,
        help="carpeta con casos_calidad.jsonl y episodios_verdad.json",
    )
    ap.add_argument("--out-dir", type=Path, default=DEFAULT_OUT)
    ap.add_argument(
        "--test", action="store_true", help="incluye la partición sellada (E9, E10)"
    )
    ap.add_argument("--modes", default=",".join(MODES))
    ap.add_argument(
        "--name", default="recuperacion", help="prefijo de los archivos de salida"
    )
    args = ap.parse_args(argv)

    from app.core.db import get_engine
    from app.modules.auth import repository as auth_repo
    from app.retrieval.embedder import get_embedder

    modes = [x for x in args.modes.split(",") if x]
    bad = set(modes) - set(MODES)
    if bad:
        raise SystemExit(f"modos desconocidos: {sorted(bad)}")
    wanted = DEV_EPISODES | (TEST_EPISODES if args.test else frozenset())
    cases, episodios, sha = load_cases(args.evals)
    cases = [c for c in cases if c["episodio"] in wanted]

    embedder = get_embedder()
    engine = get_engine()
    with engine.connect() as conn:
        qrels = build_qrels(cases, episodios, doc_dates(conn), control_links(conn))
        problems = check_anchors(conn, qrels)
        if problems:
            print("\n".join(problems), file=sys.stderr)
            print(
                "¿Sembraste el corpus (make seed) con el dataset actual?",
                file=sys.stderr,
            )
            return 2
        service = RetrievalService(conn, embedder)
        cache: dict[str, Any] = {}

        def users(username: str) -> Any:
            if username not in cache:
                uid = auth_repo.find_active_user_id(conn, username)
                user = auth_repo.get_user(conn, uid) if uid else None
                if user is None:
                    raise SystemExit(
                        f"el usuario {username!r} no existe (¿corriste el seed?)"
                    )
                cache[username] = user
            return cache[username]

        rows = run_retrieval_eval(conn, service, users, cases, qrels, modes)  # type: ignore[arg-type]
        report = build_report(
            rows,
            index_version=service.index_version,
            embedder=embedder.model_name,
            dataset_sha=sha,
            splits=["dev", "test"] if args.test else ["dev"],
        )

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stem = args.out_dir / f"{args.name}{'-con-test' if args.test else ''}"
    stem.with_suffix(".json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    md = render_markdown(report)
    stem.with_suffix(".md").write_text(md, encoding="utf-8")
    print(md)
    print(f"guardado en {stem}.json / .md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
