"""Build near an online player and try rewards, effects and entities."""

import argparse
import math

from minebridge import Minecraft, block, effects, entity, items, selector
from minebridge.models import ItemStack


def main() -> None:
    parser = argparse.ArgumentParser(description="A short Minebridge building lesson")
    parser.add_argument("player", help="Текущий ник онлайн-игрока в основном Overworld")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4711)
    parser.add_argument("--lightning", action="store_true", help="Создать настоящую молнию в 12 блоках")
    args = parser.parse_args()

    mc = Minecraft.create(args.host, args.port, player=args.player)
    try:
        print("Игроки:", mc.players.list())
        print("Мой runtime ID:", mc.getPlayerEntityId(args.player))
        position = mc.players.getPos(selector.SELF)
        print("Моя позиция:", position)

        # Выберите для занятия свободное место: эта область будет изменена.
        x = math.floor(position.x) + 4
        y = math.floor(position.y) - 1
        z = math.floor(position.z)
        mc.setBlocks(x, y, z, x + 5, y, z + 5, block.COBBLESTONE)
        for offset in range(6):
            mc.setBlock(x + offset, y + 1, z, block.OAK_LOG.withStates(axis="x"))
        mc.setBlock(x, y + 1, z + 1, block.OAK_STAIRS.withStates(facing="east", half="bottom"))

        # Чтение ждёт завершения предыдущих buffered-записей.
        print("Числовой ID:", mc.getBlock(x, y, z))
        print("Координаты → ID:", mc.getBlocks(x, y, z, x + 1, y, z + 1))
        print("Состояния лестницы:", mc.blocks.getBlock(x, y + 1, z + 1))
        print("Современная область:", mc.blocks.getBlocks(x, y + 1, z, x + 1, y + 1, z))

        print("Телепортация:", mc.players.teleport(selector.SELF, x + 2.5, y + 1, z + 2.5))
        reward = ItemStack(items.IRON_SWORD, name="Меч строителя", lore=["Награда за площадку"])
        result = mc.players.giveItem(selector.SELF, reward)
        for outcome in result.targets:
            print("Награда:", outcome.given, "Остаток:", outcome.leftovers, "Выброшено:", outcome.dropped)
        print("Скорость:", mc.effects.add(selector.SELF, effects.SPEED, duration=30, level=2))

        cow = mc.spawnEntity(x + 4.5, y + 1, z + 4.5, entity.COW)
        print("Корова:", cow)
        print("Эффект корове:", mc.effects.add(cow, effects.GLOWING, duration=15))
        print("Предмет:", mc.entities.spawn(entity.ITEM, x + 3.5, y + 2, z + 3.5,
                                             item=ItemStack(items.EMERALD, amount=3)))
        if args.lightning:
            print("Молния:", mc.spawnEntity(x + 12, y + 1, z, entity.LIGHTNING_BOLT))

        mc.postToChat(f"{args.player} построил площадку и получил награду из Python!")
        mc.flush()
    finally:
        mc.close()


if __name__ == "__main__":
    main()
