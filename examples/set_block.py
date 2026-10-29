"""Place blocks using constants or a supported numeric ID."""

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
