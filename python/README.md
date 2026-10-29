# Minebridge

**Build Minecraft worlds and games with Python.**

Minebridge pairs a typed Python library with a Paper server plugin. Build and
read blocks, react to chat and gameplay events, work with players, entities,
effects, inventories and world settings. Minecraft clients do not need a mod.

Requires **Python 3.11+**, **Paper 26.2** and **Java 25**. The tested server build
is Paper 26.2 build 133. Install the plugin and library from the same release.
The Python package has no runtime dependencies. License: MIT.

## Install

1. Download [minebridge-paper-0.3.1.jar](https://github.com/ilyak163rus/minebridge/releases/download/v0.3.1/minebridge-paper-0.3.1.jar), place it in your stopped Paper server's `plugins/` folder and start the server.
2. Install the Python library:

   ```shell
   python -m pip install "https://github.com/ilyak163rus/minebridge/releases/download/v0.3.1/minebridge-0.3.1-py3-none-any.whl"
   ```

Downloads are hosted on GitHub Releases. The package is not yet published to
PyPI. See [getting started](https://github.com/ilyak163rus/minebridge/blob/main/docs/en/GETTING_STARTED.md)
for LAN setup, optional authentication and troubleshooting.

## Build something

```python
from minebridge import Minecraft, block

with Minecraft.create("localhost", 4711) as mc:
    mc.setBlocks(0, 79, 0, 10, 79, 10, block.STONE_BRICKS)
    for step in range(10):
        mc.setBlock(step, 80 + step, 5, block.GOLD_BLOCK)
    mc.postToChat("Built with Python!")
```

Coordinates are absolute. Choose a clear area in the primary Overworld.
Block writes and chat are buffered by default. Use `mc.flush()` to wait for
completion; reads and leaving the `with` block also wait for earlier writes.
`writeMode="sync"` waits after each write. Chunks load automatically.

## React to chat

```python
from minebridge import Minecraft, events, items
from minebridge.models import ChatEvent

with Minecraft.create("localhost", 4711) as mc:
    def on_chat(event: ChatEvent) -> None:
        if event.message == "!reward":
            print(mc.players.giveItem(event.player, items.EMERALD, 3))
        elif event.message == "!stop":
            mc.events.stop()

    subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
    try:
        mc.events.run()
    finally:
        subscription.unsubscribe()
```

Handlers run in the thread calling `events.run()` and can use library methods.
`giveItem` returns any items that did not fit. Exact inventory `setItem` methods
replace a slot instead. To use `selector.SELF`, explicitly bind a current online
player with `Minecraft.create(ip, port, player="YourNick")`.

Typed catalogs include `block`, `items`, `entity`, `effects`, `selector`, `events`,
`slots`, `gamemode`, `weather`, `gamerule` and `damageCause`. VS Code/Pylance can
complete methods and constants without connecting to a server.

- [API reference](https://github.com/ilyak163rus/minebridge/blob/main/docs/API.md)
- [Recipes](https://github.com/ilyak163rus/minebridge/blob/main/docs/en/RECIPES.md)
- [Examples](https://github.com/ilyak163rus/minebridge/tree/main/examples)
- [Russian documentation](https://github.com/ilyak163rus/minebridge/blob/main/README.ru.md)
- [Source and issues](https://github.com/ilyak163rus/minebridge)

Minebridge is an independent project, not an official Minecraft product.
It is not approved by or associated with Mojang or Microsoft.
