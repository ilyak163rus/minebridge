"""Чтение областей и состояния блоков Minebridge 0.2.

Новая область загружается/генерируется сервером без подхода игрока.
Перед запуском установите wheel 0.2.0 и соответствующий серверный плагин.
"""

from minebridge import Minecraft, block


def main() -> None:
    mc = Minecraft.create("localhost", 4711)
    try:
        x, y, z = 20_000, 80, 20_000
        mc.setBlocks(x + 8, y, z + 8, x, y, z, block.COBBLESTONE)

        # Чтение автоматически дожидается предшествующей buffered-постройки.
        print("Старый ID:", mc.getBlock(x, y, z))
        print("Координаты → ID:", mc.getBlocks(x, y, z, x + 1, y, z + 1))

        mc.setBlock(x, y + 1, z, block.OAK_STAIRS.withStates(facing="east", half="bottom"))
        mc.setBlock(x + 1, y + 1, z, "minecraft:oak_log[axis=x]")
        print("Лестница со всеми состояниями:", mc.blocks.getBlock(x, y + 1, z))
        print("Современная область:", mc.blocks.getBlocks(x, y + 1, z, x + 1, y + 1, z))
    finally:
        mc.close()


if __name__ == "__main__":
    main()
