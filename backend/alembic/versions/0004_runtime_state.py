"""Add runtime state storage.

Revision ID: 0004_runtime_state
Revises: 0003_accounts_session_metadata
Create Date: 2026-06-09
"""

from alembic import op
import sqlalchemy as sa


revision = "0004_runtime_state"
down_revision = "0003_accounts_session_metadata"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def upgrade():
    bind = op.get_bind()
    if "runtime_state" in _table_names(bind):
        return

    op.create_table(
        "runtime_state",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade():
    bind = op.get_bind()
    if "runtime_state" in _table_names(bind):
        op.drop_table("runtime_state")
