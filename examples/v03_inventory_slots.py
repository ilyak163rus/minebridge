"""I04 source example: exact replacement, public player slots and a chest."""

from minebridge import Minecraft, block, items, selector, slots
from minebridge.models import ItemStack


def main() -> None:
    with Minecraft.create("192.168.0.200", 4712, player="CurrentNick") as mc:
        mc.setBlock(10, 80, 10, block.CHEST)
        chest = mc.inventories.ofBlock(10, 80, 10)
        print(chest.size, chest.layout)

        result = chest.setItem(0, ItemStack(items.DIAMOND, 16, name="Reward"))
        print(result.previous, result.current)
        print(chest.getContents())
        chest.clear(0)

        inventory = mc.inventories.ofPlayer(selector.SELF)
        inventory.setItem(slots.HEAD, items.DIAMOND_HELMET, 1)
        inventory.setItem(slots.OFF_HAND, items.SHIELD, 1)
        mc.players.setItem(selector.ALL_PLAYERS, 8, items.COMPASS, 1)
        print(inventory.getItem(slots.OFF_HAND))

        # combined=True uses Paper's left/right ordering if a second half exists.
        combined = mc.inventories.ofBlock(10, 80, 10, combined=True)
        print(combined.size, combined.layout)
        # ItemView is a description; passing it back to setItem is intentionally invalid.


if __name__ == "__main__":
    main()
