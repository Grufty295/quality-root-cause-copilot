"""Esquema inicial: plantas, líneas, documentos, fragmentos, NCR, citas y auditoría.

Revision ID: 0001
Revises:
Create Date: 2026-10-14
"""

from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    sql = (SQL_DIR / "0001_initial.sql").read_text(encoding="utf-8")
    with op.get_bind().connection.dbapi_connection.cursor() as cur:
        cur.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("Usa make reset-db para volver a cero")
