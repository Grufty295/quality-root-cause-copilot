"""Detalle de defect_event y maintenance_order.

Revision ID: 0009
Revises: 0008
Create Date: 2026-10-15
"""

from pathlib import Path

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

SQL_DIR = Path(__file__).resolve().parent.parent / "sql"


def upgrade() -> None:
    sql = (SQL_DIR / "0009_defect_maintenance_detail.sql").read_text(encoding="utf-8")
    with op.get_bind().connection.dbapi_connection.cursor() as cur:
        cur.execute(sql)


def downgrade() -> None:
    raise NotImplementedError("Usa make reset-db para volver a cero")
