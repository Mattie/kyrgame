from dataclasses import dataclass


@dataclass(frozen=True)
class ModernFeature:
    id: str
    title: str
    scope: str
    status: str
    honor_behavior: str
    modern_behavior: str
    legacy_refs: tuple[str, ...]
    test_refs: tuple[str, ...] = ()

    def public_payload(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "scope": self.scope,
            "status": self.status,
            "honor_behavior": self.honor_behavior,
            "modern_behavior": self.modern_behavior,
            "legacy_refs": list(self.legacy_refs),
        }


FOUNTAIN_IMMEDIATE_SP_RESTORE = "fountain_immediate_sp_restore"
MODERN_DEATH_RECOVERY = "modern_death_recovery"


MODERN_FEATURES = (
    ModernFeature(
        id=FOUNTAIN_IMMEDIATE_SP_RESTORE,
        title="Fountain immediate spell-point restore",
        scope="room:38",
        status="active",
        honor_behavior=(
            "Drinking from the Fountain of Eternal Magic uses the legacy water-drinking "
            "message and does not restore spell points outside the recurring tick."
        ),
        modern_behavior=(
            "Non-honor players recover up to 2 spell points immediately when drinking "
            "from the Fountain of Eternal Magic."
        ),
        legacy_refs=("legacy/KYRROUS.C:759-819",),
        test_refs=("backend/tests/test_room_scripts.py",),
    ),
    ModernFeature(
        id=MODERN_DEATH_RECOVERY,
        title="Modern death recovery",
        scope="player_lifecycle:death",
        status="active",
        honor_behavior=(
            "Honor-mode and force-honor deaths keep the legacy hitoth()/initgp() "
            "full reset to level 1 with inventory, gold, spells, spellbook bits, "
            "birthstone progress, and temporary state cleared."
        ),
        modern_behavior=(
            "Non-honor deaths lose one level, drop eligible inventory, clear temporary "
            "effects and memorized spells, preserve spellbook ownership, restore HP/SP "
            "for the new level, and return exhausted to the willow."
        ),
        legacy_refs=(
            "legacy/KYRSPEL.C:303-321",
            "legacy/KYRANDIA.C:325-356",
            "legacy/KYRSYSP.C:148",
        ),
        test_refs=(
            "backend/tests/test_player_lifecycle.py",
            "backend/tests/test_commands_cast.py",
            "backend/tests/test_yaml_room_engine.py",
            "backend/tests/world/test_animation_tick_system.py",
        ),
    ),
)

_FEATURES_BY_ID = {feature.id: feature for feature in MODERN_FEATURES}


def require_feature(feature_id: str) -> ModernFeature:
    try:
        return _FEATURES_BY_ID[feature_id]
    except KeyError as exc:
        raise ValueError(f"Unknown modern feature id: {feature_id}") from exc


def public_feature_payloads() -> list[dict]:
    return [feature.public_payload() for feature in MODERN_FEATURES]
