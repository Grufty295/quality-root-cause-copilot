from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Connection, Engine, create_engine

from app.core.config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


def get_conn() -> Iterator[Connection]:
    """Una transaccion por peticion: commit al terminar, rollback si hay error."""
    with get_engine().begin() as conn:
        yield conn
