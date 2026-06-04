from collections.abc import Iterable
from contextlib import asynccontextmanager
from copy import deepcopy

from sqlalchemy import select

from kyrgame import constants, models
from kyrgame.webapp import create_app


DEFAULT_RETURNING_PLAYER_IDS = (
    "alpha",
    "bravo",
    "caster",
    "journey",
    "looker",
    "mystic",
    "rogue",
    "scout",
    "seer",
    "solver",
    "target",
    "watcher",
    "witness",
)


def seed_returning_players(
    app, player_ids: Iterable[str] = DEFAULT_RETURNING_PLAYER_IDS
) -> None:
    with app.state.session_factory() as db:
        template = db.scalar(select(models.Player).where(models.Player.plyrid == "hero"))
        if template is None:
            raise RuntimeError("Seed player 'hero' is required for returning-player tests")

        for player_id in player_ids:
            existing = db.scalar(select(models.Player).where(models.Player.plyrid == player_id))
            if existing is not None:
                continue

            data = {
                column.name: deepcopy(getattr(template, column.name))
                for column in models.Player.__table__.columns
                if column.name != "id"
            }
            data.update(
                {
                    "uidnam": player_id[: constants.UIDSIZ],
                    "plyrid": player_id[: constants.ALSSIZ],
                    "altnam": player_id[: constants.APNSIZ],
                    "attnam": player_id[: constants.APNSIZ],
                    "spouse": player_id[: constants.ALSSIZ],
                    "gamloc": 0,
                    "pgploc": 0,
                }
            )
            db.add(models.Player(**data))

        db.commit()


def create_seeded_app():
    app = create_app()
    original_lifespan = app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app_instance):
        async with original_lifespan(app_instance):
            seed_returning_players(app_instance)
            yield

    app.router.lifespan_context = lifespan
    return app
