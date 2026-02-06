from . import models


def pop_inventory_index(player: models.PlayerModel, index: int) -> tuple[int, int]:
    """Remove and return an inventory slot as ``(object_id, object_value)``.

    Legacy-derived paths frequently mutate ``gpobjs``/``obvals`` together; this helper
    keeps both arrays and ``npobjs`` aligned when removing a specific slot.
    """

    object_id = player.gpobjs.pop(index)
    object_value = player.obvals.pop(index) if index < len(player.obvals) else 0
    player.npobjs = len(player.gpobjs)
    return object_id, object_value


def remove_inventory_item(player: models.PlayerModel, object_id: int) -> bool:
    """Remove the first matching object id from inventory.

    Returns ``True`` when an item was removed.
    """

    try:
        index = player.gpobjs.index(object_id)
    except ValueError:
        return False
    pop_inventory_index(player, index)
    return True
