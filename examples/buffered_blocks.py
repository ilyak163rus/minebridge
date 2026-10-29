"""Построить ряд блоков и измерить время до подтверждённого завершения.

Нужные чанки Minebridge 0.2 загружает автоматически; выберите свободную площадку.
Пример: python buffered_blocks.py --host 192.168.0.200 --port 4712 --y 80
"""

import argparse
import time

from minebridge import Minecraft, block


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=4711)
    parser.add_argument("--x", type=int, default=0)
    parser.add_argument("--y", type=int, default=80)
    parser.add_argument("--z", type=int, default=0)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--write-mode", choices=("buffered", "sync"), default="buffered")
    args = parser.parse_args()
    if args.count < 1:
        parser.error("--count должен быть положительным")
    mc = Minecraft.create(args.host, args.port, writeMode=args.write_mode)
    try:
        started = time.perf_counter()
        for index in range(args.count):
            mc.setBlock(args.x + index, args.y, args.z, block.COBBLESTONE)
        mc.flush()
        elapsed = time.perf_counter() - started
        print(f"Подтверждено блоков: {args.count}; время: {elapsed:.3f} с; режим: {args.write_mode}")
    finally:
        mc.close()


if __name__ == "__main__":
    main()
