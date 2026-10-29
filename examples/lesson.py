"""A complete interactive lesson. Choose a clear area near the online player."""

import argparse
import math

from minebridge import Minecraft, block, events, gamemode, items, selector, slots
from minebridge.models import BlockBreakEvent, ChatEvent, LavaEnterEvent, Region


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("player", help="Current online Minecraft player name")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=4711)
    args = parser.parse_args()

    with Minecraft.create(args.host, args.port, player=args.player) as mc:
        position = mc.players.getPos(selector.SELF)
        x, y, z = (math.floor(value) for value in (position.x, position.y, position.z))
        world = mc.server.getInfo().world
        if position.world != world.name:
            raise ValueError("Enter the connection's Overworld before running this lesson")
        if y - 1 < world.minY or y >= world.maxYExclusive:
            raise ValueError("Choose a position inside the world's build height")
        print(mc.server.getInfo())
        mc.players.setGameMode(selector.SELF, gamemode.CREATIVE)
        mc.setBlocks(x - 2, y - 1, z - 2, x + 2, y - 1, z + 2, block.COBBLESTONE)
        mc.setBlock(x + 2, y, z + 2, block.CHEST)
        chest = mc.inventories.ofBlock(x + 2, y, z + 2)
        chest.setItem(0, items.DIAMOND, 8)
        print(chest.getContents())
        inventory = mc.inventories.ofPlayer(selector.SELF)
        inventory.setItem(slots.OFF_HAND, items.SHIELD, 1)
        arena = Region(world.uuid, (x - 5, world.minY, z - 5),
                       (x + 5, world.maxYExclusive - 1, z + 5))

        def on_chat(event: ChatEvent) -> None:
            if event.message == "!reward":
                target = mc.inventories.ofPlayer(event.player)
                target.setItem(0, items.EMERALD, 3)
            elif event.message == "!recent":
                for message in mc.events.getRecent(events.CHAT_MESSAGE, 5):
                    print(message.player.name, message.message)
            elif event.message == "!stop":
                mc.events.stop()

        def on_break(event: BlockBreakEvent) -> None:
            print(event.player.name, event.position, event.block)
            mc.players.giveItem(event.player, items.DIAMOND, 1)

        def on_lava(event: LavaEnterEvent) -> None:
            # An observation; it does not cancel damage or pause the server.
            print("Lava:", event.player.name, event.position)

        subscriptions = [
            mc.events.subscribe(events.CHAT_MESSAGE, on_chat, players=selector.SELF),
            mc.events.subscribe(events.BLOCK_BREAK, on_break, players=selector.SELF,
                                region=arena, blocks=block.COBBLESTONE),
            mc.events.subscribe(events.PLAYER_ENTER_LAVA, on_lava, players=selector.SELF),
        ]
        print("Commands: !reward replaces slot 0; !recent prints history; !stop exits.")
        try:
            mc.events.run()
        except KeyboardInterrupt:
            pass
        finally:
            for subscription in subscriptions:
                subscription.unsubscribe()


if __name__ == "__main__":
    main()
