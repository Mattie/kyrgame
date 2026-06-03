"""Add session lifecycle state for first-login intro flow.

Revision ID: 0002_session_lifecycle_state
Revises: 0001_initial_schema
Create Date: 2026-06-03
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_session_lifecycle_state"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("player_sessions")
    }
    if "lifecycle_state" not in columns:
        op.add_column(
            "player_sessions",
            sa.Column("lifecycle_state", sa.String(length=32), nullable=True),
        )
    if "lifecycle_step" not in columns:
        op.add_column(
            "player_sessions",
            sa.Column("lifecycle_step", sa.Integer(), nullable=True),
        )


def downgrade():
    bind = op.get_bind()
    columns = {
        column["name"]
        for column in sa.inspect(bind).get_columns("player_sessions")
    }
    if "lifecycle_step" in columns:
        op.drop_column("player_sessions", "lifecycle_step")
    if "lifecycle_state" in columns:
        op.drop_column("player_sessions", "lifecycle_state")
