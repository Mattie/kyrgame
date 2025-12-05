"""Initial database schema for Kyrandia backend.

Revision ID: 0001_initial_schema
Revises: 
Create Date: 2025-02-24
"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0001_initial_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "spells",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("sbkref", sa.Integer(), nullable=False),
        sa.Column("bitdef", sa.BigInteger(), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("splrou", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "objects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("objdes", sa.Integer(), nullable=False),
        sa.Column("auxmsg", sa.Integer(), nullable=False),
        sa.Column("flags", sa.String(length=64), nullable=False),
        sa.Column("objrou", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("brfdes", sa.String(length=80), nullable=False),
        sa.Column("objlds", sa.String(length=160), nullable=False),
        sa.Column("nlobjs", sa.Integer(), nullable=False),
        sa.Column("objects", sa.JSON(), nullable=False),
        sa.Column("gi_north", sa.Integer(), nullable=False),
        sa.Column("gi_south", sa.Integer(), nullable=False),
        sa.Column("gi_east", sa.Integer(), nullable=False),
        sa.Column("gi_west", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "players",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("uidnam", sa.String(length=14), nullable=False),
        sa.Column("plyrid", sa.String(length=14), nullable=False),
        sa.Column("altnam", sa.String(length=30), nullable=False),
        sa.Column("attnam", sa.String(length=30), nullable=False),
        sa.Column("gpobjs", sa.JSON(), nullable=False),
        sa.Column("nmpdes", sa.Integer(), nullable=True),
        sa.Column("modno", sa.Integer(), nullable=True),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("gamloc", sa.Integer(), nullable=False),
        sa.Column("pgploc", sa.Integer(), nullable=False),
        sa.Column("flags", sa.BigInteger(), nullable=False),
        sa.Column("gold", sa.Integer(), nullable=False),
        sa.Column("npobjs", sa.Integer(), nullable=False),
        sa.Column("obvals", sa.JSON(), nullable=False),
        sa.Column("nspells", sa.Integer(), nullable=False),
        sa.Column("spts", sa.Integer(), nullable=False),
        sa.Column("hitpts", sa.Integer(), nullable=False),
        sa.Column("offspls", sa.BigInteger(), nullable=False),
        sa.Column("defspls", sa.BigInteger(), nullable=False),
        sa.Column("othspls", sa.BigInteger(), nullable=False),
        sa.Column("charms", sa.JSON(), nullable=False),
        sa.Column("spells", sa.JSON(), nullable=False),
        sa.Column("gemidx", sa.Integer(), nullable=True),
        sa.Column("stones", sa.JSON(), nullable=False),
        sa.Column("macros", sa.Integer(), nullable=True),
        sa.Column("stumpi", sa.Integer(), nullable=True),
        sa.Column("spouse", sa.String(length=14), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "commands",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("command", sa.String(length=32), nullable=False),
        sa.Column("payonl", sa.Integer(), nullable=False),
        sa.Column("cmdrou", sa.String(length=64), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("text", sa.String(length=255), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "player_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("session_token", sa.String(length=128), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("session_token", name="uq_player_session_token"),
    )
    op.create_index(op.f("ix_player_sessions_player_id"), "player_sessions", ["player_id"], unique=False)

    op.create_table(
        "player_inventories",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("slot_index", sa.Integer(), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("object_value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "slot_index", name="uq_player_slot"),
    )
    op.create_index(op.f("ix_player_inventories_player_id"), "player_inventories", ["player_id"], unique=False)

    op.create_table(
        "spell_timers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("spell_id", sa.Integer(), nullable=False),
        sa.Column("remaining_ticks", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("player_id", "spell_id", name="uq_player_spell_timer"),
    )
    op.create_index(op.f("ix_spell_timers_player_id"), "spell_timers", ["player_id"], unique=False)

    op.create_table(
        "room_occupants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("room_id", sa.Integer(), nullable=False),
        sa.Column("player_id", sa.Integer(), nullable=False),
        sa.Column("entered_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["player_id"], ["players.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("room_id", "player_id", name="uq_room_player"),
    )
    op.create_index(op.f("ix_room_occupants_room_id"), "room_occupants", ["room_id"], unique=False)
    op.create_index(op.f("ix_room_occupants_player_id"), "room_occupants", ["player_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_room_occupants_player_id"), table_name="room_occupants")
    op.drop_index(op.f("ix_room_occupants_room_id"), table_name="room_occupants")
    op.drop_table("room_occupants")
    op.drop_index(op.f("ix_spell_timers_player_id"), table_name="spell_timers")
    op.drop_table("spell_timers")
    op.drop_index(op.f("ix_player_inventories_player_id"), table_name="player_inventories")
    op.drop_table("player_inventories")
    op.drop_index(op.f("ix_player_sessions_player_id"), table_name="player_sessions")
    op.drop_table("player_sessions")
    op.drop_table("messages")
    op.drop_table("commands")
    op.drop_table("players")
    op.drop_table("locations")
    op.drop_table("objects")
    op.drop_table("spells")
