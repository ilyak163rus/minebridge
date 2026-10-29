# Changelog

## 0.3.1 — 2026-10-29

- Faster region building: fills of up to 32,768 blocks run in one bounded server pass once chunks are ready. Larger regions remain incremental.
- `selector.playerByName("YourNick")` targets a current online player by exact name.
- `PeacefulSpawnError` clearly explains when the world's Peaceful difficulty prevents an entity from spawning.
- Public English and Russian guides, API reference, runnable examples, MIT license and downloadable plugin/library release.

See [release details in Russian](docs/releases/0.3.1.ru.md).

## 0.3.0 — 2026-10-29

- Fourteen event types with Python callbacks, filters and independent in-memory history.
- Exact player and chest inventory slots.
- Player game modes, health and food; world time, weather and game rules.
- Selector-based `setPos` and positional effect duration/level arguments.

## 0.2.1 — 2026-10-26

- Normal Python shutdown waits for buffered commands.
- `Minecraft.create(..., logging=True)` enables action logs for the connection.

## 0.2.0

- Buffered block writes, block states, region reads and automatic chunk loading.
- Players, selectors, teleportation, chat, items, effects and entity spawning.
- Typed catalogs and optional connection token; automatic primary Overworld selection.
