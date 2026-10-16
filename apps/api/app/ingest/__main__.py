"""Ingesta del corpus.

    python -m app.ingest                                   # corpus por defecto, planta JRZ1
    python -m app.ingest --corpus /workspace/data/seed/corpus --plant JRZ1
    python -m app.ingest --dry-run                         # solo parsea y fragmenta; no toca la base

Requiere los catálogos (plant, line) cargados. Sale con código 1 si algún
documento falló, para que `make seed` lo haga visible.

Nunca apuntes --corpus a evals/: los casos de evaluación no se indexan.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

DEFAULT_CORPUS = Path("/workspace/data/seed/corpus")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.ingest", description=__doc__.split("\n\n")[0])
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--plant", default="JRZ1", help="planta a la que pertenece el corpus")
    parser.add_argument("--dry-run", action="store_true", help="parsea y fragmenta sin base ni embeddings")
    args = parser.parse_args(argv)

    if "evals" in args.corpus.resolve().parts:
        print("Se rechaza indexar evals/: contaminaría la medición.", file=sys.stderr)
        return 2

    if args.dry_run:
        return _dry_run(args.corpus)

    from app.core.db import get_engine
    from app.ingest.service import IngestError, IngestService
    from app.retrieval.embedder import get_embedder

    service = IngestService(get_engine().begin, get_embedder(), plant_id=args.plant)
    try:
        service.check_environment()
        report = service.ingest_directory(args.corpus)
    except IngestError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(
        f"creados {len(report.created)} · actualizados {len(report.updated)} · "
        f"sin cambios {len(report.unchanged)} · fallidos {len(report.failed)} · fragmentos {report.fragments}"
    )
    for name, msg in report.warnings:
        print(f"  aviso  {name}: {msg}")
    for name, msg in report.failed:
        print(f"  fallo  {name}: {msg}", file=sys.stderr)
    return 0 if report.ok else 1


def _dry_run(root: Path) -> int:
    from app.ingest.frontmatter import FrontMatterError, parse_document
    from app.retrieval.chunker import chunk_markdown

    total, failed = 0, 0
    for path in sorted(root.rglob("*.md")):
        try:
            doc = parse_document(path.read_text(encoding="utf-8"))
        except FrontMatterError as exc:
            failed += 1
            print(f"  fallo  {path.relative_to(root)}: {exc}", file=sys.stderr)
            continue
        drafts = chunk_markdown(source_key=doc.source_key, title=doc.title, kind=doc.kind, body=doc.body)
        total += len(drafts)
        longest = max(len(d.content) for d in drafts)
        print(f"{doc.source_key:<18} {doc.kind.value:<17} {doc.level.value:<12} {len(drafts):>3} frag  max {longest}c")
    print(f"total {total} fragmentos, {failed} fallidos")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
