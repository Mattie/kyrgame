"""Add account login and session metadata.

Revision ID: 0003_accounts_session_metadata
Revises: 0002_session_lifecycle_state
Create Date: 2026-06-06
"""

from alembic import op
import sqlalchemy as sa


revision = "0003_accounts_session_metadata"
down_revision = "0002_session_lifecycle_state"
branch_labels = None
depends_on = None


def _table_names(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _column_names(bind, table_name: str) -> set[str]:
    return {column["name"] for column in sa.inspect(bind).get_columns(table_name)}


def _foreign_key_names(bind, table_name: str) -> set[str | None]:
    return {fk["name"] for fk in sa.inspect(bind).get_foreign_keys(table_name)}


def upgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "accounts" not in tables:
        op.create_table(
            "accounts",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("userid_norm", sa.String(length=14), nullable=False),
            sa.Column("userid", sa.String(length=14), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("player_id", sa.Integer(), nullable=False),
            sa.Column("disabled", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
            sa.Column("first_login_completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("player_id", name="uq_accounts_player_id"),
            sa.UniqueConstraint("userid_norm", name="uq_accounts_userid_norm"),
        )
        op.create_index(op.f("ix_accounts_userid_norm"), "accounts", ["userid_norm"], unique=True)
        tables.add("accounts")

    columns = _column_names(bind, "player_sessions")
    if "account_id" not in columns:
        op.add_column("player_sessions", sa.Column("account_id", sa.Integer(), nullable=True))
        op.create_index(
            op.f("ix_player_sessions_account_id"),
            "player_sessions",
            ["account_id"],
            unique=False,
        )
        columns.add("account_id")
    if (
        bind.dialect.name != "sqlite"
        and "accounts" in tables
        and "account_id" in columns
        and "fk_player_sessions_account_id" not in _foreign_key_names(bind, "player_sessions")
    ):
        op.create_foreign_key(
            "fk_player_sessions_account_id",
            "player_sessions",
            "accounts",
            ["account_id"],
            ["id"],
            ondelete="SET NULL",
        )
    if "session_kind" not in columns:
        op.add_column(
            "player_sessions",
            sa.Column("session_kind", sa.String(length=16), nullable=False, server_default="game"),
        )
    if "hidden_from_activity" not in columns:
        op.add_column(
            "player_sessions",
            sa.Column("hidden_from_activity", sa.Boolean(), nullable=False, server_default=sa.false()),
        )


def downgrade():
    bind = op.get_bind()
    tables = _table_names(bind)

    if "player_sessions" in tables:
        columns = _column_names(bind, "player_sessions")
        if "hidden_from_activity" in columns:
            op.drop_column("player_sessions", "hidden_from_activity")
        if "session_kind" in columns:
            op.drop_column("player_sessions", "session_kind")
        if "account_id" in columns:
            if (
                bind.dialect.name != "sqlite"
                and "fk_player_sessions_account_id"
                in _foreign_key_names(bind, "player_sessions")
            ):
                op.drop_constraint(
                    "fk_player_sessions_account_id",
                    "player_sessions",
                    type_="foreignkey",
                )
            op.drop_index(op.f("ix_player_sessions_account_id"), table_name="player_sessions")
            op.drop_column("player_sessions", "account_id")

    if "accounts" in tables:
        op.drop_index(op.f("ix_accounts_userid_norm"), table_name="accounts")
        op.drop_table("accounts")
