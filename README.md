<p align="center">
  <img src="docs/assets/minebridge.svg" alt="Minebridge — build Minecraft worlds with Python" width="860">
</p>

<p align="center">
  <a href="https://github.com/ilyak163rus/minebridge/actions/workflows/ci.yml"><img src="https://github.com/ilyak163rus/minebridge/actions/workflows/ci.yml/badge.svg" alt="Build and test"></a>
  <img src="https://img.shields.io/badge/Python-3.11%2B-3776AB?logo=python&logoColor=white" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/Paper-26.2-59A869" alt="Paper 26.2">
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT license"></a>
</p>

<p align="center">
  <strong>Build worlds. React to players. Make your own Minecraft games — in Python.</strong><br>
  <a href="https://github.com/ilyak163rus/minebridge/releases/tag/v0.3.1">Download</a> ·
  <a href="docs/en/GETTING_STARTED.md">Get started</a> ·
  <a href="docs/API.md">API</a> ·
  <a href="examples/README.md">Examples</a> ·
  <a href="README.ru.md">Русский</a>
</p>

Minebridge connects ordinary Python programs to a **Minecraft Java Edition server running Paper**. It pairs a typed Python library with a server plugin: no Minecraft client mod is required. Use it for coding lessons, procedural builds, chat bots and small multiplayer games.

```python
from minebridge import Minecraft, block

with Minecraft.create("localhost", 4711) as mc:
    mc.setBlocks(0, 79, 0, 10, 79, 10, block.STONE_BRICKS)
    for step in range(10):
        mc.setBlock(step, 80 + step, 5, block.GOLD_BLOCK)
    mc.postToChat("Your staircase to the sky is ready!")
```

Coordinates are absolute. This builds a platform and a staircase in the primary Overworld; choose a clear area before running it.

## What can you make?

| Work with | What you can do |
|---|---|
| **Blocks** | Build and read regions, use modern block states, load chunks automatically |
| **Players** | Find online players, select groups, teleport, change game mode, health and food |
| **Items & effects** | Give rewards, apply effects, use typed catalogs with IDE completion |
| **Entities** | Spawn mobs, items, projectiles and lightning with type-specific parameters |
| **Inventories** | Read and replace exact slots in player inventories and chests |
| **Events** | Handle chat, block breaks, attacks, damage, projectiles, lava and player lifecycle events |
| **Worlds** | Change time, weather and game rules |

Familiar with `mcpi`? Keep `Minecraft.create(ip, port)`, `setBlock`, `setBlocks`, supported numeric block IDs and `block.COBBLESTONE`. Change your imports to `minebridge`. See the [migration notes](docs/MIGRATING_FROM_MCPI.md) for the differences.

## Get running

You need **Python 3.11+** and **Paper 26.2 with Java 25**. The tested server build is **26.2 build 133**; other Minecraft versions are not currently supported. Minebridge is an early release: APIs may evolve before 1.0.

**1. Install the plugin.** Download [minebridge-paper-0.3.1.jar](https://github.com/ilyak163rus/minebridge/releases/download/v0.3.1/minebridge-paper-0.3.1.jar), put it in your stopped server's `plugins/` folder and start the server. The default listener is `127.0.0.1:4711`; no token or world name is needed for this local setup.

**2. Install the Python library.** Run this in your Python environment:

```shell
python -m pip install "https://github.com/ilyak163rus/minebridge/releases/download/v0.3.1/minebridge-0.3.1-py3-none-any.whl"
```

**3. Run the example above.** Join the same server in Minecraft to see your build. The `with` block waits for pending writes before closing the connection.

Python running on another computer? Follow the [LAN setup](docs/en/GETTING_STARTED.md#connecting-from-another-computer). Already using RaspberryJuice? Assign Minebridge a separate TCP port, such as `4712`, in both its config and your Python code.

The Python package has **no runtime dependencies**. Install the Python library and plugin from the same release. Downloads are hosted on GitHub Releases; the package is not yet published to PyPI.

## Turn chat into a game

Players type `!reward` to receive emeralds. Type `!stop` to finish the script.

```python
from minebridge import Minecraft, events, items
from minebridge.models import ChatEvent

with Minecraft.create("localhost", 4711) as mc:
    def on_chat(event: ChatEvent) -> None:
        if event.message == "!reward":
            result = mc.players.giveItem(event.player, items.EMERALD, 3)
            print(result)  # Includes any items that did not fit.
        elif event.message == "!stop":
            mc.events.stop()

    subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
    try:
        mc.events.run()
    finally:
        subscription.unsubscribe()
```

Handlers run in the thread that calls `events.run()`. You can call Minecraft methods inside them. Event callbacks observe server events; they do not cancel them.

## Explore

- [Getting started](docs/en/GETTING_STARTED.md) — installation, multiplayer setup and troubleshooting.
- [API reference](docs/API.md) — methods, selectors, inventories and events in one place.
- [Recipes](docs/en/RECIPES.md) and [runnable examples](examples/README.md) — build on working code.
- [Документация на русском](docs/README.md#русский) — установка и подробные справочники.
- [Changelog](CHANGELOG.md) — [Report a bug or suggest a feature](https://github.com/ilyak163rus/minebridge/issues/new/choose) — [Contribute](CONTRIBUTING.md).

Found Minebridge useful? A star helps other Python and Minecraft learners find it. Sharing something you built helps even more.

## License

[MIT](LICENSE). See [third-party notices](THIRD_PARTY_NOTICES.md) for bundled components.

Minebridge is an independent project, not an official Minecraft product. It is not approved by or associated with Mojang or Microsoft.
