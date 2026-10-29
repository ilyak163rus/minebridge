"""Игроки и чат Minebridge 0.2; укажите текущий ник онлайн-игрока."""

import argparse

from minebridge import selector
from minebridge.minecraft import Minecraft


def main() -> None:
    parser = argparse.ArgumentParser(description="Игроки, SELF и чат Minebridge 0.2")
    parser.add_argument("player", help="Текущий ник онлайн-игрока")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4711)
    args = parser.parse_args()

    mc = Minecraft.create(args.host, args.port, player=args.player)
    try:
        print("Игроки:", mc.players.list())
        print("Runtime ID:", mc.getPlayerEntityId(args.player))
        position = mc.players.getPos(selector.SELF)
        print("Моя позиция:", position)

        # Teleport to the same position: a harmless example preserving fractions.
        result = mc.players.teleport(selector.SELF, position.x, position.y, position.z,
                                     world=position.world)
        print("Результат:", result)
        mc.postToChat(f"Привет из Python, {args.player}!")
        mc.flush()
    finally:
        mc.close()


if __name__ == "__main__":
    main()
