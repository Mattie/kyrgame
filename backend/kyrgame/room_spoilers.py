from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from . import fixtures
from .yaml_rooms import extract_room_spoilers

LEGACY_ROOM_SPOILERS: dict[int, dict[str, str]] = {
    0: {
        "summary": "Willow grove with a hidden phrase that grants early defensive magic.",
        "interaction": (
            "Look/examine/see the tree or willow for a special description, then speak the "
            "secret WILCMD phrase to trigger the level 2 gate and gain the willow spell."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:59-60; legacy/KYRROUS.C:169-195",
        # Legacy: legacy/KYRLOCS.C:59-60; legacy/KYRROUS.C:169-195
    },
    7: {
        "summary": "Temple of Tashanna with chants, offerings, and marriage rites.",
        "interaction": (
            "Chant 'tashanna' to brighten the altar, place the key offerings on the altar "
            "for level 9/10 gates, say the temple phrase for the level 3 gate, pray/meditate "
            "for flavor, offer gold pieces for credit, or marry/wed another player."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:67; legacy/KYRROUS.C:288-407",
        # Legacy: legacy/KYRLOCS.C:67; legacy/KYRROUS.C:288-407
    },
    8: {
        "summary": "Gem cutter's hut where a jeweler quietly evaluates offered stones.",
        "interaction": (
            "Give/sell/trade gems to receive fixed gold payouts, trade a kyragem for a "
            "soulstone, and get a refusal for anything else."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:68; legacy/KYRROUS.C:197-239",
        # Legacy: legacy/KYRLOCS.C:68; legacy/KYRROUS.C:197-239
    },
    9: {
        "summary": "Spell shop stocked with a fixed inventory of spells.",
        "interaction": (
            "Buy/order/pay/purchase <spell> to purchase from the stocked list; the shop "
            "charges gold if you can afford it and refuses otherwise."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:69; legacy/KYRROUS.C:241-286",
        # Legacy: legacy/KYRLOCS.C:69; legacy/KYRROUS.C:241-286
    },
    10: {
        "summary": "Healer's dwelling where a rose offering brings restorative magic.",
        "interaction": (
            "Offer a rose to consume it and heal 10 HP (up to 4× level); other offers are "
            "rejected and missing roses draw a gentle refusal."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:70; legacy/KYRROUS.C:409-436",
        # Legacy: legacy/KYRLOCS.C:70; legacy/KYRROUS.C:409-436
    },
    12: {
        "summary": "Bubbling brook where scavenging may turn up a little gold.",
        "interaction": (
            "Dig/hunt/search/look at the brook to attempt a small gold find if you're under "
            "101 gold; drink water for a flavor message and pick roses if you have room."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:72; legacy/KYRROUS.C:438-469",
        # Legacy: legacy/KYRLOCS.C:72; legacy/KYRROUS.C:438-469
    },
    14: {
        "summary": "Pine glade where reaching for pinecones is a game of chance.",
        "interaction": (
            "Get/grab/pick/take pinecone for a 40% success chance; you need inventory "
            "space to keep the cone."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:74; legacy/KYRROUS.C:492-509",
        # Legacy: legacy/KYRLOCS.C:74; legacy/KYRROUS.C:492-509
    },
    16: {
        "summary": "Fear-haunted glade with a secret phrase that dispels it.",
        "interaction": (
            "Say the EGLADE phrase to attempt the level 5 gate; the goddess grants a "
            "level if you're exactly one short and refuses otherwise."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:76; legacy/KYRROUS.C:661-677",
        # Legacy: legacy/KYRLOCS.C:76; legacy/KYRROUS.C:661-677
    },
    18: {
        "summary": "Ancient stump puzzle that rewards offering the right sequence of items.",
        "interaction": (
            "Drop offerings into the stump in the expected order while at level 5; correct "
            "items advance the counter and the 12th completes the level 6 gate and spell, "
            "while mistakes reset progress."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:78; legacy/KYRROUS.C:511-552",
        # Legacy: legacy/KYRLOCS.C:78; legacy/KYRROUS.C:511-552
    },
    19: {
        "summary": "Flaming thicket that scorches the unwary.",
        "interaction": "Walk the thicket to take immediate fire damage and broadcast the mishap.",
        "legacy_ref": "legacy/KYRLOCS.C:79; legacy/KYRROUS.C:645-659",
        # Legacy: legacy/KYRLOCS.C:79; legacy/KYRROUS.C:645-659
    },
    20: {
        "summary": "Ruby cache guarded by a risky grab.",
        "interaction": (
            "Get/grab/pick/take ruby for a 20% success chance; failure triggers a snake "
            "strike that deals damage."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:80; legacy/KYRROUS.C:599-618",
        # Legacy: legacy/KYRLOCS.C:80; legacy/KYRROUS.C:599-618
    },
    24: {
        "summary": "Silver altar where birthstone offerings advance a gem quest.",
        "interaction": (
            "Offer the correct stones in sequence; completing all four at the level 4 gate "
            "grants a defensive spell, while wrong offerings reset progress. Pray/meditate "
            "for flavor."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:84; legacy/KYRROUS.C:554-597",
        # Legacy: legacy/KYRLOCS.C:84; legacy/KYRROUS.C:554-597
    },
    26: {
        "summary": "Ash tree grove where tears can summon a crystal shard.",
        "interaction": (
            "Cry/weep at the ashes or trees to spawn a shard on the ground if there is "
            "room; otherwise the shard vanishes."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:86; legacy/KYRROUS.C:707-727",
        # Legacy: legacy/KYRLOCS.C:86; legacy/KYRROUS.C:707-727
    },
    27: {
        "summary": "Misty sword-in-the-rock ritual site.",
        "interaction": (
            "Pray at the rock to stir the mists, then drop a sword onto the rock to trade "
            "it for a tiara; the ritual fails without the sword."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:87; legacy/KYRROUS.C:679-705",
        # Legacy: legacy/KYRLOCS.C:87; legacy/KYRROUS.C:679-705
    },
    32: {
        "summary": "Quiet spring with water to drink and roses to gather.",
        "interaction": "Drink water for flavor text and pick roses if you have inventory space.",
        "legacy_ref": "legacy/KYRLOCS.C:92; legacy/KYRROUS.C:729-739",
        # Legacy: legacy/KYRLOCS.C:92; legacy/KYRROUS.C:729-739
    },
    34: {
        "summary": "Druid circle where an orb rewards a sceptre sacrifice.",
        "interaction": (
            "Touch the orb with a sceptre to consume it and grant a random offensive spell; "
            "missing sceptres draw a rebuke."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:94; legacy/KYRROUS.C:620-643",
        # Legacy: legacy/KYRLOCS.C:94; legacy/KYRROUS.C:620-643
    },
    35: {
        "summary": "Quiet terrace where sipping water is the only notable action.",
        "interaction": "Drink water to receive a simple message; other actions fall through.",
        "legacy_ref": "legacy/KYRLOCS.C:95; legacy/KYRROUS.C:471-478",
        # Legacy: legacy/KYRLOCS.C:95; legacy/KYRROUS.C:471-478
    },
    38: {
        "summary": "Magic fountain that blesses pilgrims and transforms offerings.",
        "interaction": (
            "Speak the fountain phrase to gain the blessing, then toss pinecones (when "
            "blessed) to eventually spawn a scroll in the world, or toss shards to earn a "
            "crystal after six; other items are rejected."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:98; legacy/KYRROUS.C:759-819",
        # Legacy: legacy/KYRLOCS.C:98; legacy/KYRROUS.C:759-819
    },
    101: {
        "summary": "Heart-and-soul ritual altar dedicated to Tashanna.",
        "interaction": (
            "Offer heart and soul to Tashanna to clear the level 7 gate and gain the "
            "heart-and-soul spell."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:161; legacy/KYRROUS.C:821-838",
        # Legacy: legacy/KYRLOCS.C:161; legacy/KYRROUS.C:821-838
    },
    181: {
        "summary": "Tashanna's statue that answers imagination with a dagger.",
        "interaction": (
            "Imagine a dagger to receive one if you have inventory space; look/examine/see "
            "the statue for its lore text."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:241; legacy/KYRROUS.C:840-860",
        # Legacy: legacy/KYRLOCS.C:241; legacy/KYRROUS.C:840-860
    },
    182: {
        "summary": "Reflecting pool that reforges a dagger.",
        "interaction": (
            "Drop/throw a dagger into the pool to trade it for a refined blade; look at the "
            "pool for its reflection message."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:242; legacy/KYRROUS.C:863-885",
        # Legacy: legacy/KYRLOCS.C:242; legacy/KYRROUS.C:863-885
    },
    183: {
        "summary": "Pantheon with a spoken riddle that rewards the faithful.",
        "interaction": (
            "Say the full phrase about legends and time ('legends ... time ... true ... never "
            "die') to gain the reward if you have space; look at symbols or pillars for lore."
        ),
        "legacy_ref": "legacy/KYRLOCS.C:243; legacy/KYRROUS.C:888-917",
        # Legacy: legacy/KYRLOCS.C:243; legacy/KYRROUS.C:888-917
    },
}


@lru_cache(maxsize=4)
def load_room_spoilers(path: Path | None = None) -> dict[int, dict[str, str]]:
    definitions = fixtures.load_room_scripts(path)
    yaml_spoilers = extract_room_spoilers(definitions)
    merged: dict[int, dict[str, str]] = {
        room_id: spoiler.copy() for room_id, spoiler in LEGACY_ROOM_SPOILERS.items()
    }
    for room_id, spoiler in yaml_spoilers.items():
        entry = merged.get(room_id, {}).copy()
        for key in ("summary", "interaction", "legacy_ref"):
            value = spoiler.get(key)
            if value:
                entry[key] = value
        if entry:
            merged[room_id] = entry
    return merged
