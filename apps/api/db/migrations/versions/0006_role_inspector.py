"""Agrega el rol inspector a user_role.

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-15
"""

from pathlib import Path

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    sql = (SQL_DIR / "0006_role_inspector.sql").read_text(encoding="utf-8")
    with op.get_bind().connection.dbapi_connection.cursor() as cur:
        cur.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("Usa make reset-db para volver a cero")
