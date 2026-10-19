"""Muestrea las conexiones de Postgres cada pocos segundos mientras corre una prueba de carga.

    docker compose exec api python -m app.evalkit.pool_sampler --every 2 --for 900 > traces/carga/conexiones.csv

Imprime CSV: segundo, activas, ociosas, ociosas_en_transaccion, total. "Ociosa en transacción" es la conexión que una
petición tiene tomada mientras espera (por ejemplo, al modelo): la señal de la deuda conocida.
"""

from __future__ import annotations

import argparse
import time

from sqlalchemy import text

from app.core.db import get_engine

SQL = text(
    """
    SELECT
      count(*) FILTER (WHERE state = 'active'),
      count(*) FILTER (WHERE state = 'idle'),
      count(*) FILTER (WHERE state = 'idle in transaction'),
      count(*)
    FROM pg_stat_activity
    WHERE datname = current_database() AND pid <> pg_backend_pid()
    """
)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--every", type=float, default=2.0)
    ap.add_argument("--for", dest="duration", type=float, default=900.0)
    args = ap.parse_args()
    print("segundo,activas,ociosas,ociosas_en_transaccion,total", flush=True)
    t0 = time.monotonic()
    # Una conexión propia, fuera del pool de la API: no compite con lo que se mide.
    engine = get_engine()
    with engine.connect() as conn:
        while (elapsed := time.monotonic() - t0) < args.duration:
            a, i, it, total = conn.execute(SQL).one()
            conn.rollback()
            print(f"{elapsed:.0f},{a},{i},{it},{total}", flush=True)
            time.sleep(args.every)


if __name__ == "__main__":
    main()
