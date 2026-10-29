# Examples

Install the [library and Paper plugin](../docs/en/GETTING_STARTED.md) first.
These programs change the world: choose a clear area and review coordinates
before running them. Default connection: `localhost:4711`.

| Example | What it demonstrates |
|---|---|
| [set_block.py](set_block.py) | First blocks using constants and numeric IDs |
| [block_regions.py](block_regions.py) | Region building, reads and block states |
| [buffered_blocks.py](buffered_blocks.py) | Buffered writes and completion barriers |
| [players_and_chat.py](players_and_chat.py) | Online players, selectors and teleportation |
| [rewards_effects_entities.py](rewards_effects_entities.py) | Item rewards, effects and entity spawning |
| [chat_bot.py](chat_bot.py) | `!diamond` chat command and independent chat history |
| [game_events.py](game_events.py) | Block-break rewards and lava notifications |
| [inventories.py](inventories.py) | Exact chest/player slots, armor and offhand |
| [world_and_players.py](world_and_players.py) | Game mode, health, food, weather and game rules |
| [lesson.py](lesson.py) | A combined interactive lesson near an online player |
| [blocks_and_rewards.py](blocks_and_rewards.py) | Building, rewards and entities near a player |

Run a small example from the repository root:

```shell
python examples/set_block.py
python examples/chat_bot.py
```

For examples with fixed connection settings, change the address and port in
`Minecraft.create(...)` if your server is elsewhere. Examples using
`player="CurrentNick"` require your actual online name.

The combined lesson accepts command-line arguments:

```shell
python examples/lesson.py YourNick --host 127.0.0.1 --port 4711
```

It changes your game mode to Creative, builds a small platform and chest nearby,
replaces the offhand slot and starts event handlers. `!reward` replaces slot 0,
`!recent` prints chat history and `!stop` exits. Breaking cobblestone in the area
gives a diamond. Lava contact prints a notification.

For shorter copy-and-paste programs, see [recipes](../docs/en/RECIPES.md) and the
[API reference](../docs/API.md). Русский: [быстрый старт](../docs/QUICKSTART.ru.md).
