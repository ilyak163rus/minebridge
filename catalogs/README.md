# Block catalog provenance

`paper-26.2-build133-blocks.json` is a runtime snapshot of every entry in
`Registry.BLOCK` on the project's pinned Paper 26.2 build 133. Each row records
the canonical key and the server's default `BlockData`, including its properties.
The snapshot is data, not a list inferred from item names or a different release.
The pinned Paper download URL and SHA-256 are embedded in the snapshot.

`mcpi-upstream-constants.json` records the historical constant names and numeric
IDs from RaspberryJuice's bundled `mcpi/block.py`, pinned to its source commit
and file SHA-256. Conversion to modern blocks is independently measured on
Paper with `Bukkit.getUnsafe().fromLegacy(Material, byte)`. This deprecated API
is used only by the disposable exporter; production code uses the checked-in
conversion table and has no dependency on legacy server conversion APIs.

The requested legacy pairs include the upstream Java-compatible base constants
and explicit metadata for stone, dirt, woods, logs, leaves, flowers, colored
blocks, slabs, stairs, and the covered directional blocks. The export stores the
complete converted states so that, for example, old stair metadata is not
silently replaced with a modern default direction. Undefined wood slab variants
are omitted. This is a bounded compatibility table, not a claim that every old
numeric ID/data combination works.

Java semantics apply to historical numeric IDs. Pi-only `BEDROCK_INVISIBLE`,
`GLOWING_OBSIDIAN`, and `NETHER_REACTOR_CORE` are deliberately absent: Java ID 95
means stained glass. `FLOWER_CYAN` retains the upstream Java numeric meaning
(ID 38, the modern poppy), not a promise of a blue Pi flower. Flowing/stationary
water IDs 8/9 and lava IDs 10/11 can represent identical modern states; a reverse
numeric read must report ambiguity instead of inventing a distinction.

Three historical names refer to different modern keys: `PUMPKIN` (old 86) is
carved pumpkin, `STONE_SLAB` (old 44) is smooth-stone slab, and default legacy
`TORCH` (old 50/data 0) converts to wall torch. The modern registry keys remain
available as `MINECRAFT_PUMPKIN`, `MINECRAFT_STONE_SLAB`, and `MINECRAFT_TORCH`,
respectively, or directly by their `minecraft:...` strings. Similarly, legacy
IDs 31/data 0 and 32 both become dead bush and cannot be uniquely reversed.

The generated `minebridge.block` module contains static `Final` assignments and
`__all__` for IDE completion without a running server or network access.
Historical names retain `LegacyBlock` with `.id`/`.data`; modern-only names use
`BlockSpec`. Both accept `.withStates(...)`. A catalog constant identifies one
block state; it does not automatically create the second half of a door/bed,
invent block-entity contents, or keep unsupported plants alive against physics.

To regenerate after an intentional pinned-server update:

```powershell
# Requires the existing project toolchain, bootstrap caches, and prior EULA consent.
.venv-t01-314\Scripts\python.exe tools\export_block_catalog.py
.venv-t01-314\Scripts\python.exe tools\generate_block_catalog.py
.venv-t01-314\Scripts\python.exe tools\generate_block_catalog.py --check
```

The exporter compiles a disposable fixture JAR inside `.work`, starts one local
server on a free loopback port, writes its snapshot, and stops that server. It
does not build a production release JAR or wheel, add a production export command,
accept an EULA, or touch any other running server. The generator is entirely
offline and deterministic; generated package JSON files are normal package data.

## I04 item, effect and entity registries

`paper-26.2-build133-game.json` records the actual `Registry.ITEM`,
`Registry.MOB_EFFECT` and `Registry.ENTITY_TYPE` from the same pinned build 133.
It contains 1537 item keys (including AIR), 40 effect keys and 158 real entity keys.
UNKNOWN is not a registered entity key. AIR cannot be given as an inventory item.

The export also probes entity creation in a disposable loaded flat Overworld.
All 150 types classified `generic` returned their exact requested type and were
valid at return, then immediately removed. This tests creation, not persistence,
AI behavior or survival in an arbitrary location. Six of seven special adapters
were tested there; the fishing bobber requires an online owner and is checked
by the I04 two-player integration fixture. PLAYER requires an actual login and
is the single unsupported entity type in this API.

Special parameters are intentional: ITEM takes `item`, FALLING_BLOCK takes
`block`, PAINTING/ITEM_FRAME/GLOW_ITEM_FRAME take `face` and supporting blocks,
FISHING_BOBBER takes `owner`. LIGHTNING_BOLT uses a real strike, with gameplay
effects. The snapshot records a category, adapter, required parameters and reason
for every entity. [The contract](../docs/contracts/V0_2_CONTRACT.ru.md) describes
runtime validation and lifetime limits.

```powershell
.venv-i01-314\Scripts\python.exe tools\export_game_catalog.py
.venv-i01-314\Scripts\python.exe tools\generate_game_catalog.py
.venv-i01-314\Scripts\python.exe tools\generate_game_catalog.py --check
```

The generator writes static typed `minebridge.items`, `minebridge.effects`,
`minebridge.entity` and packaged `game-paper-26.2.json`, without network access.
The exporter reuses the prior EULA consent and cached toolchain, starts/stops
only its own disposable server and does not package a production release.

## 0.3 / I01 game rules

`paper-26.2-build133-gamerules.json` was exported from the real pinned server's
`Registry.GAME_RULE` and `GameRules` constants. It contains 59 canonical rules
(47 boolean, 12 integer), plus 23 legacy names whose objects are identical to
the canonical rules. The generated Python module contains 82 typed constants.

Five legacy wrappers convert or invert values and are listed in
`unsupportedLegacyAliases`, rather than emitted as misleading aliases:
`ALLOW_FIRE_TICKS_AWAY_FROM_PLAYER`, `DISABLE_ELYTRA_MOVEMENT_CHECK`,
`DISABLE_PLAYER_MOVEMENT_CHECK`, `DISABLE_RAIDS`, and `DO_FIRE_TICK`.
Use canonical modern keys/constants for those rules. For example,
`DO_DAYLIGHT_CYCLE` safely aliases `ADVANCE_TIME`, while the legacy boolean
`DO_FIRE_TICK` cannot simply alias the modern integer fire-spread radius.

Snapshot SHA-256:
`84daf9b4dafa7a9e8092fcfe27ffb26a2ed45fbb63b63a7a85f4b39e73e0c476`.
The snapshot records the exact Paper/API and exporter hashes. The separate
read-only fixture [GameRuleRegistryExport.java](../tools/catalog/GameRuleRegistryExport.java)
runs inside the disposable I01 Paper acceptance server; it never becomes a
production command or updates another running server.

```powershell
.\.venv-tools\Scripts\python.exe tools/prepare_gamerule_export.py
# After copying that fixture JAR to the disposable server and exporting the snapshot:
.\.venv-tools\Scripts\python.exe tools/generate_gamerule_catalog.py
.\.venv-tools\Scripts\python.exe tools/generate_gamerule_catalog.py --check
```

The generator is offline. It writes `minebridge.gamerule` and packaged
`gamerules-paper-26.2.json`; each constant is `GameRuleKey[bool]` or
`GameRuleKey[int]` with its real default value. Limits for individual integer
rules are validated by the actual server codec, not inferred from defaults.

## 0.3 / I03 damage causes

`paper-26.2-build133-damage-causes.json` contains the 33 actual constants in
`EntityDamageEvent.DamageCause` from the pinned API133 class file. The snapshot
records the API JAR SHA-256 (`e8079e853374d75e571a24379573e96f6dfe1581b97bae5465163c77f00f327a`).
The exporter uses the pinned local javap rather than a live Javadoc version.

```powershell
.\.venv-v021-311\Scripts\python.exe tools/export_damage_cause_catalog.py
.\.venv-v021-311\Scripts\python.exe tools/export_damage_cause_catalog.py --check
.\.venv-v021-311\Scripts\python.exe tools/generate_damage_cause_catalog.py
.\.venv-v021-311\Scripts\python.exe tools/generate_damage_cause_catalog.py --check
```

The offline generator writes static `minebridge.damageCause.DamageCause`
StrEnum values and constants such as `damageCause.LAVA`, `FALL`, and `PROJECTILE`.
An unknown future native cause remains a string in the event snapshot. Damage
cause describes the observed calculation; it does not prove an exact HP delta.
