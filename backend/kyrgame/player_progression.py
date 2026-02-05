from . import constants, models


def level_up_player(player: models.PlayerModel):
    """Apply a single level gain to a player.

    Legacy parity: mirrors ``glvutl`` progression updates
    (legacy/KYRROUS.C lines 1439-1461).
    """

    player.level += 1
    if player.nmpdes is None:
        player.nmpdes = constants.level_to_nmpdes(player.level)
    else:
        player.nmpdes += 1
    player.hitpts += 4
    player.spts += 2
