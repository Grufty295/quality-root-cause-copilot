"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

Convención del proyecto: el cambio de esquema va en db/migrations/sql/ como SQL
crudo, y esta versión solo lo ejecuta. Ver 0003_scope_fix.py como ejemplo.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = ${repr(up_revision)}
down_revision: str | Sequence[str] | None = ${repr(down_revision)}
branch_labels: str | Sequence[str] | None = ${repr(branch_labels)}
depends_on: str | Sequence[str] | None = ${repr(depends_on)}

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    sql = (SQL_DIR / "${up_revision}_NOMBRE.sql").read_text(encoding="utf-8")
    with op.get_bind().connection.dbapi_connection.cursor() as cur:
        cur.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("Usa make reset-db para volver a cero")
