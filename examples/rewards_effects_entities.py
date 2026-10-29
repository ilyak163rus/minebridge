"""Give rewards, apply effects and spawn entities near an online player."""

import argparse

from minebridge import Minecraft, block, effects, entity, items, selector
from minebridge.models import ItemStack


def main() -> None:
    parser = argparse.ArgumentParser(description="Minebridge rewards, effects and entities")
    parser.add_argument("player", help="Текущий ник онлайн-игрока")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4711)
    parser.add_argument("--lightning", action="store_true", help="Создать настоящую молнию в 12 блоках")
    args = parser.parse_args()

    mc = Minecraft.create(args.host, args.port, player=args.player)
    try:
        prize = ItemStack(items.IRON_SWORD, name="Меч строителя", lore=["Награда из Python"])
        print("Моя награда:", mc.players.giveItem(selector.SELF, prize))
        print("Случайный игрок:", mc.players.giveItem(selector.RANDOM_PLAYER, items.DIAMOND, 2))
        print("Эффект:", mc.effects.add(selector.SELF, effects.SPEED, duration=30, level=2))

        position = mc.players.getPos(selector.SELF)
        x, y, z = position.x + 4, position.y + 1, position.z
        print("Корова:", mc.spawnEntity(x, y, z, entity.COW, world=position.world))
        print("Предмет:", mc.spawnEntity(x + 2, y, z, entity.ITEM,
                                          world=position.world, item=ItemStack(items.EMERALD, amount=3)))
        print("Падающий блок:", mc.spawnEntity(x + 4, y + 3, z, entity.FALLING_BLOCK,
                                                world=position.world, block=block.OAK_LOG.withStates(axis="x")))
        if args.lightning:
            print("Молния:", mc.spawnEntity(position.x + 12, position.y, position.z,
                                            entity.LIGHTNING_BOLT, world=position.world))
        mc.postToChat("Награды и сущности созданы из Python!")
        mc.flush()
    finally:
        mc.close()


if __name__ == "__main__":
    main()
