"""Minebridge 0.3/I01 source example for a current online player.

python examples/v03_controls.py CurrentNick --host 192.168.0.200 --port 4712
Use --configure-world to apply the optional shared world settings below.
"""

import argparse

from minebridge import Minecraft, effects, gamemode, gamerule, selector, weather


def main() -> None:
    parser = argparse.ArgumentParser(description="Minebridge 0.3/I01: player and world controls")
    parser.add_argument("player", help="Current online, alive Minecraft player nickname")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4711)
    parser.add_argument("--configure-world", action="store_true",
                        help="Set noon, clear weather, keepInventory and disable the daylight cycle")
    args = parser.parse_args()

    with Minecraft.create(args.host, args.port, player=args.player) as mc:
        print("Connection:", mc.server.getInfo())
        print("Capabilities:", mc.server.getCapabilities())
        position = mc.players.getPos(selector.SELF)
        previous_mode = mc.players.getGameMode(selector.SELF)
        health = mc.players.getHealth(selector.SELF)
        food = mc.players.getFoodLevel(selector.SELF)
        print("Before:", previous_mode, health, food, position)

        # The selector comes first. This keeps the same position and world.
        print("Position:", mc.setPos(selector.SELF, position.x, position.y, position.z,
                                     world=position.world))
        print("Creative:", mc.players.setGameMode(selector.SELF, gamemode.CREATIVE))
        try:
            # Values are health points and food level, not hearts or percentages.
            print("Health:", mc.players.setHealth(selector.SELF, health))
            print("Food:", mc.players.setFoodLevel(selector.SELF, food))
            # Positional form: thirty game seconds, second effect level.
            print("Speed:", mc.effects.add(selector.SELF, effects.SPEED, 30, 2))
            print("Remove speed:", mc.effects.remove(selector.SELF, effects.SPEED))

            if args.configure_world:
                mc.worlds.setGameRule(gamerule.KEEP_INVENTORY, True)
                mc.worlds.setGameRule(gamerule.DO_DAYLIGHT_CYCLE, False)
                mc.worlds.setTime(6000)
                mc.worlds.setWeather(weather.CLEAR)
                print("World:", mc.worlds.getTime(), mc.worlds.getWeather())
                print("keepInventory:", mc.worlds.getGameRule(gamerule.KEEP_INVENTORY))
        finally:
            print("Restore mode:", mc.players.setGameMode(selector.SELF, previous_mode))


if __name__ == "__main__":
    main()
