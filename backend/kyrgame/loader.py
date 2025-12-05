from pathlib import Path
from typing import Iterable

from sqlalchemy.orm import Session

from . import fixtures, models


def _reset_tables(session: Session):
    session.query(models.Message).delete()
    session.query(models.Location).delete()
    session.query(models.GameObject).delete()
    session.query(models.Spell).delete()
    session.commit()


def _persist_all(session: Session, entities: Iterable[object]):
    for entity in entities:
        session.add(entity)
    session.commit()


def load_all_from_fixtures(session: Session, fixture_root: Path | None = None):
    """Load all JSON/YAML fixtures into the provided database session."""
    _reset_tables(session)

    locations = fixtures.load_locations(fixture_root)
    objects = fixtures.load_objects(fixture_root)
    spells = fixtures.load_spells(fixture_root)
    messages = fixtures.load_messages(fixture_root)

    _persist_all(
        session,
        [
            models.Location(
                id=item.id,
                brfdes=item.brfdes,
                objlds=item.objlds,
                objects=item.objects,
                gi_north=item.gi_north,
                gi_south=item.gi_south,
                gi_east=item.gi_east,
                gi_west=item.gi_west,
            )
            for item in locations
        ],
    )

    _persist_all(
        session,
        [
            models.GameObject(
                id=item.id,
                name=item.name,
                objdes=item.objdes,
                auxmsg=item.auxmsg,
                flags=",".join(item.flags),
                objrou=item.objrou,
            )
            for item in objects
        ],
    )

    _persist_all(
        session,
        [
            models.Spell(
                id=item.id,
                name=item.name,
                sbkref=item.sbkref,
                bitdef=item.bitdef,
                level=item.level,
                splrou=item.splrou,
            )
            for item in spells
        ],
    )

    _persist_all(
        session,
        [models.Message(id=key, text=value) for key, value in messages.messages.items()],
    )
