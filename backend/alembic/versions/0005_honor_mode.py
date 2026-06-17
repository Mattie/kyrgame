"""Add per-player honor mode.

Revision ID: 0005_honor_mode
Revises: 0004_runtime_state
Create Date: 2026-06-17
"""

from alembic import op
import sqlalchemy as sa


revision = "0005_honor_mode"
down_revision = "0004_runtime_state"
branch_labels = None
depends_on = None


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def upgrade():
    bind = op.get_bind()
    if "honor_mode" in _column_names(bind, "players"):
        return
    op.add_column(
        "players",
        sa.Column("honor_mode", sa.Boolean(), nullable=False, server_default=sa.true()),
    )


def downgrade():
    bind = op.get_bind()
    if "honor_mode" in _column_names(bind, "players"):
        op.drop_column("players", "honor_mode")
