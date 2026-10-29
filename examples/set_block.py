"""Пример Minebridge 0.2. Укажите адрес, порт и координаты своей площадки.

Нужен Paper с плагином Minebridge; имя/IP, порт и позиции измените для своего стенда.
"""

from minebridge.minecraft import Minecraft
from minebridge import block


def main() -> None:
    mc = Minecraft.create("localhost", 4711)
    try:
        mc.setBlock(0, 80, 0, 4)
        mc.blocks.setBlock(1, 80, 0, block.COBBLESTONE)
        mc.flush()
    finally:
        mc.close()


if __name__ == "__main__":
    main()
