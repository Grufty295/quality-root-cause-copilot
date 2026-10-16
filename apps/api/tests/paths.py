"""Ubicación de data/seed para las pruebas, igual dentro y fuera del contenedor.

En el contenedor, data/ se monta en /workspace/data (docker-compose.yml) y el código vive
en /app, así que no se puede llegar a data/ subiendo desde __file__. Orden de búsqueda:

1. SEED_DATA_DIR, si está definido.
2. /workspace/data/seed (el montaje del compose).
3. data/seed en algún ancestro de este archivo (repo en el host).

Si nada existe, se devuelve la ruta del montaje: las pruebas que dependen del dataset real
se saltan con su propio `skipif(not ...exists())`.
"""

from __future__ import annotations

import os
from pathlib import Path

_MOUNT = Path("/workspace/data/seed")


def seed_dir() -> Path:
    env = os.environ.get("SEED_DATA_DIR")
    if env:
        return Path(env)
    if _MOUNT.is_dir():
        return _MOUNT
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "data" / "seed"
        if candidate.is_dir():
            return candidate
    return _MOUNT


SEED_DIR = seed_dir()
STRUCTURED_DIR = SEED_DIR / "estructurados"
CORPUS_DIR = SEED_DIR / "corpus"
