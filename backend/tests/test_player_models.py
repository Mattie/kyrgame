import pytest
from pydantic import ValidationError

from kyrgame import constants, fixtures, models


def _player_payload():
    return fixtures.build_player().model_dump()


def test_player_model_round_trip_serialization():
    payload = _player_payload()
    restored = models.PlayerModel(**payload)

    assert restored.model_dump() == payload


def test_player_model_requires_all_gmplyr_fields():
    payload = _player_payload()
    payload.pop("macros")

    with pytest.raises(ValidationError):
        models.PlayerModel(**payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("charms", [constants.CHARM_TIMER_MAX + 1] * constants.NCHARM),
        ("gemidx", constants.GEM_INDEX_MAX + 1),
        ("stumpi", constants.STUMPI_MAX + 1),
        ("macros", constants.MACROS_MAX + 1),
    ],
)
def test_player_model_rejects_out_of_range_fields(field, value):
    payload = _player_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        models.PlayerModel(**payload)


def test_player_model_rejects_unknown_flags():
    payload = _player_payload()
    payload["flags"] = int(constants.PlayerFlag.FEMALE) | (1 << 20)

    with pytest.raises(ValidationError):
        models.PlayerModel(**payload)


def test_player_model_rejects_spell_ids_out_of_range():
    payload = _player_payload()
    payload["spells"] = [constants.NGSPLS]
    payload["nspells"] = 1

    with pytest.raises(ValidationError):
        models.PlayerModel(**payload)


def test_player_model_rejects_spell_slot_overflow():
    payload = _player_payload()
    payload["spells"] = list(range(constants.MAXSPL + 1))
    payload["nspells"] = len(payload["spells"])

    with pytest.raises(ValidationError):
        models.PlayerModel(**payload)
