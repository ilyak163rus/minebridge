# Python API

This reference describes Minebridge **0.3.1**. Install both the Python package and
the matching Paper plugin using the [getting started guide](en/GETTING_STARTED.md).
Runnable programs are in [examples](../examples).

- [Connection and completion](#connection-and-completion)
- [Blocks and block states](#blocks-and-block-states)
- [Players and selectors](#players-and-selectors)
- [Items and effects](#items-and-effects)
- [Entities](#entities)
- [Inventories and slots](#inventories-and-slots)
- [Events and history](#events-and-history)
- [World settings](#world-settings)
- [Catalogs and models](#catalogs-and-models)
- [Errors](#errors)

## Connection and completion

```python
from minebridge import Minecraft, block

with Minecraft.create("localhost", 4711) as mc:
    mc.setBlock(0, 80, 0, block.COBBLESTONE)
    mc.postToChat("Hello from Python!")
```

`with` closes the connection and waits for pending writes. Coordinates are
absolute world coordinates. The primary Overworld is selected automatically;
its folder name does not need to appear in the plugin configuration.

```text
Minecraft.create(ip="localhost", port=4711, *, writeMode="buffered",
                 token=None, world=None, timeout=5.0, coordinates=None,
                 player=None, logging=False) -> Minecraft
```

| Parameter | Meaning |
|---|---|
| `ip`, `port` | Address and TCP port of the Minebridge plugin, not the Minecraft game port |
| `writeMode` | `"buffered"` by default; `"sync"` waits for each write |
| `player` | Current online player name to bind `selector.SELF` |
| `world` | `None` for the primary Overworld, or an already loaded world's name/key |
| `token` | Optional authentication token; `None` also checks `MINEBRIDGE_TOKEN` |
| `timeout` | Positive timeout in seconds for individual network stages |
| `logging` | `True` enables server action logs for this connection |
| `coordinates` | `None` or `"absolute"`; relative coordinates are not supported |

| Method | Result |
|---|---|
| `mc.flush()` | Wait for all previous writes; raise deferred errors |
| `mc.close()` | Wait for writes and close; repeated calls are safe |
| `mc.withContext(*, player=None)` | Another facade on the same connection, with a separate SELF binding |
| `mc.server.getInfo()` | Immutable `ConnectionInfo`: session, plugin/server versions, capabilities and selected world |
| `mc.server.getCapabilities()` | Tuple of capability names |

In buffered mode, `setBlock`, `setBlocks` and `postToChat` return before server
confirmation. A read, a method returning a server result, `flush()` or `close()`
waits for earlier writes. Normal Python shutdown also drains writes; use `with`
or `flush()` to handle failures in your own code. Forced termination cannot
guarantee completion. Closing a `withContext` facade closes the shared connection.

## Blocks and block states

| Method | Result |
|---|---|
| `mc.setBlock(x, y, z, block, data=0)` | Set one block; returns `None` |
| `mc.setBlocks(x1, y1, z1, x2, y2, z2, block, data=0)` | Fill an inclusive cuboid; returns `None` |
| `mc.getBlock(x, y, z)` | Legacy numeric block ID |
| `mc.getBlocks(x1, y1, z1, x2, y2, z2)` | Dictionary mapping coordinate tuples to legacy IDs |
| `mc.blocks.getBlock(x, y, z)` | Modern `BlockSpec`, including `.key` and `.states` |
| `mc.blocks.getBlocks(x1, y1, z1, x2, y2, z2)` | Dictionary mapping coordinate tuples to `BlockSpec` |

`mc.blocks.setBlock` and `mc.blocks.setBlocks` have the same arguments and behavior
as the top-level setters. A block may be a catalog constant, numeric legacy ID,
`BlockSpec`, `LegacyBlock`, or a namespaced string with optional states.

```python
from minebridge import Minecraft, block

with Minecraft.create("localhost", 4711) as mc:
    mc.setBlocks(0, 80, 0, 9, 80, 9, block.COBBLESTONE)
    mc.setBlock(0, 81, 0, block.OAK_LOG.withStates(axis="x"))
    mc.setBlock(1, 81, 0, block.OAK_STAIRS.withStates(facing="east", half="bottom"))
    mc.setBlock(2, 81, 0, "minecraft:oak_stairs[facing=west,half=top]")
    print(mc.blocks.getBlock(0, 81, 0).states)
```

Both corners are included and may be supplied in either order. Integer and finite
float coordinates are accepted; block coordinates are rounded down, so `-0.2`
becomes `-1`. Chunks load or generate automatically. World height and border
still apply. The maximum is 1,000,000 positions per write and 262,144 per read.

Fills of up to 32,768 blocks use a fast pass once their chunks are ready. Larger
fills run in parts. Chunk generation and block physics affect completion time.
Changes use normal block physics and do not automatically complete structures
such as doors. Failed or interrupted fills can leave partial changes.

Use modern reads for new blocks and states. Numeric reads require an unambiguous
legacy mapping and otherwise raise `UnsupportedLegacyBlockError`; they do not
cover the whole modern catalog. `withStates()` creates a new specification and
does not modify a catalog constant.

## Players and selectors

```python
from minebridge import Minecraft, selector

with Minecraft.create("localhost", 4711, player="YourNick") as mc:
    print(mc.players.list())
    position = mc.players.getPos(selector.SELF)
    mc.setPos(selector.SELF, position.x, position.y + 2, position.z)
```

Replace `YourNick` with your current online name. SELF is bound explicitly to
that player's UUID; it is not inferred from the computer, IP address or the last
player lookup. `mc.getPlayerEntityId(name)` does not change SELF.

| Selector | Meaning |
|---|---|
| `selector.SELF` | The explicitly bound player, `@s` |
| `selector.ALL_PLAYERS` | All online players, `@a` |
| `selector.RANDOM_PLAYER` | A random player, `@r` |
| `selector.NEAREST_PLAYER` | Player nearest the bound execution origin, `@p` |
| `selector.ALL_ENTITIES` | All matching entities, `@e`; individual methods restrict valid target types |
| `selector.playerByName("YourNick")` | At most one online player by current, case-sensitive name |
| `selector.Selector("@a[tag=builders]")` | A custom vanilla selector |

Target-based operations accept selector constants, selector strings, names,
UUIDs, entity/player references, or a sequence of entity/player references.
Spatial selectors need a bound player in the connection's world. Named selectors
are resolved anew for each call; they do not require SELF. A missing named
selector gives an empty group for group operations; methods requiring one player
raise `InvalidTargetError` if the selection is empty or ambiguous.

| Method | Result |
|---|---|
| `mc.getPlayerEntityId(name)` | Runtime numeric ID of one online player |
| `mc.players.get(target)` | `PlayerRef` for an explicit name, UUID or `PlayerRef` |
| `mc.players.list(targets=selector.ALL_PLAYERS)` | List of `PlayerRef` |
| `mc.players.getPos(target)` | One player's `Location`, with world, x/y/z, yaw/pitch |
| `mc.setPos(targets, x, y, z, *, world=None)` | Teleport selected players; `TargetResult` |
| `mc.players.teleport(targets, x, y, z, *, world=None)` | Same operation as `setPos` |
| `mc.players.setPos(targets, x, y, z, *, world=None)` | Same operation as `setPos` |
| `mc.players.getGameMode(target)` / `setGameMode(targets, mode)` | Read one `GameMode` / return `TargetResult` |
| `mc.players.getHealth(target)` / `setHealth(targets, value)` | Read health points / return `TargetResult` |
| `mc.players.getFoodLevel(target)` / `setFoodLevel(targets, value)` | Read food level / return `TargetResult` |

Teleport preserves fractional coordinates and loads destination chunks.
`world=None` uses the connection's world. Ordinary health is 20 points for ten
hearts; health `0` can kill, and the server checks each player's maximum. Food
level is an integer from 0 to 20.

`TargetResult` contains `.matched`, `.applied`, and `.targets`. Each target outcome
contains `.uuid`, `.applied`, and `.code`. Group operations can have partial
results, including rejection by other plugins; they are not transactions.

## Items and effects

```python
from minebridge import Minecraft, effects, items, selector
from minebridge.models import ItemStack

with Minecraft.create("localhost", 4711) as mc:
    player = selector.playerByName("YourNick")
    result = mc.players.giveItem(player, items.EMERALD, 3)
    for outcome in result.targets:
        print(outcome.given, outcome.leftovers, outcome.dropped)
    sword = ItemStack(items.IRON_SWORD, name="Builder's sword", lore=["Made with Python"])
    mc.players.giveItem(player, sword)
    mc.effects.add(player, effects.SPEED, 100, 2)
```

| Method | Result |
|---|---|
| `mc.players.giveItem(targets, item, amount=None, *, overflow="return")` | `InventoryResult` with per-player accounting |
| `mc.effects.add(targets, effect, duration, level=1, *, particles=True)` | `TargetResult` |
| `mc.effects.remove(targets, effect)` | `TargetResult` |
| `mc.effects.clear(targets)` | `TargetResult` |

An item may be an `items` constant, namespaced string or
`ItemStack(material, amount=1, name=None, lore=None)`. Passing `amount` overrides
the stack's amount. `giveItem` accepts 1–2,304 items per recipient and splits
stacks as necessary. The default returns anything that did not fit as
`.leftovers`; `overflow="drop"` drops it at the player's location. Inspect
`.given`, `.leftovers` and `.dropped` on each entry in `.targets`: an
`applied=True` outcome can still have `given=0` when the inventory is full.

Effect arguments are **duration in game seconds, then level**:
`mc.effects.add(target, effects.SPEED, 100, 200)` means 100 seconds at level 200.
Duration must be positive and finite; it rounds up to a whole tick and must fit
2,147,483,647 ticks. Level is one-based, from 1 to 256. Effects require living
targets. All these operations wait for their server results in either write mode.

## Entities

```text
mc.spawnEntity(x, y, z, entityType, *, world=None,
               item=None, block=None, face=None, owner=None) -> EntityRef
mc.entities.spawn(entityType, x, y, z, *, world=None,
                  item=None, block=None, face=None, owner=None) -> EntityRef
```

These two entry points have different argument order. Both wait for the created
entity's reference, including `.uuid`, `.entityId`, and `.key`.

```python
from minebridge import Minecraft, block, entity, items

with Minecraft.create("localhost", 4711) as mc:
    cow = mc.spawnEntity(5.5, 81, 5.5, entity.COW)
    mc.spawnEntity(6.5, 81, 5.5, entity.ITEM, item=items.EMERALD)
    mc.spawnEntity(7.5, 84, 5.5, entity.FALLING_BLOCK, block=block.SAND)
    print(cow.uuid)
```

The catalog includes mobs and non-mob entities. Special requirements:

| Type | Options and behavior |
|---|---|
| `entity.ITEM` | Requires `item` |
| `entity.FALLING_BLOCK` | Requires a non-air `block` |
| `entity.LIGHTNING_BOLT` | Real lightning; can damage entities and change the world |
| `entity.PAINTING` | Requires a horizontal `face`, free space and solid support |
| `entity.ITEM_FRAME`, `entity.GLOW_ITEM_FRAME` | Require `face`, free space and solid support; vertical faces are also accepted |
| `entity.FISHING_BOBBER` | Requires an online player `owner` in the destination world |
| `entity.PLAYER` | Present in the catalog but cannot be spawned; raises `UnsupportedEntityTypeError` |

Faces are lowercase strings: `"north"`, `"south"`, `"east"`, `"west"`, `"up"`,
`"down"`. Peaceful difficulty prevents spawning certain hostile types and raises
`PeacefulSpawnError` before applying the operation.

## Inventories and slots

```python
from minebridge import Minecraft, block, items, selector, slots

with Minecraft.create("localhost", 4711, player="YourNick") as mc:
    mc.setBlock(10, 80, 10, block.CHEST)
    chest = mc.inventories.ofBlock(10, 80, 10)
    chest.setItem(0, items.DIAMOND, 16)
    print(chest.getContents())
    inventory = mc.inventories.ofPlayer(selector.SELF)
    inventory.setItem(slots.HEAD, items.DIAMOND_HELMET)
```

| Method | Result |
|---|---|
| `mc.inventories.ofBlock(x, y, z, *, world=None, combined=False)` | `InventoryRef` for a normal or trapped chest |
| `mc.inventories.ofPlayer(target)` | `InventoryRef` for exactly one selected online player |
| `inventory.getItem(slot)` | `ItemView` or `None` for an empty slot |
| `inventory.getContents()` | Dictionary mapping every public slot to `ItemView` or `None` |
| `inventory.setItem(slot, item, amount=None)` | `SlotWriteResult` with `.previous` and `.current` |
| `inventory.clear(slot=None)` | Clear one slot, or all public slots; `InventoryUpdateResult` |
| `mc.players.setItem(targets, slot, item, amount=None)` | Replace a slot for a group of players; `TargetResult` |

`setItem` **replaces the slot** instead of adding to its existing stack. The
amount must fit that item's native stack limit. To add rewards without choosing
a slot, use `giveItem`.

Player indices `0..8` are the hotbar and `9..35` are main storage. Use
`slots.HEAD`, `CHEST`, `LEGS`, `FEET`, and `OFF_HAND` for equipment; numeric slots
36–40 are not accepted. A chest has integer slots `0..26` by default.
`combined=True` exposes both halves of a double chest with Paper's left/right
ordering; inspect `.size`, `.slots` and `.layout` rather than guessing.

Acquire a new chest reference after changing its type, orientation or double-chest
layout; a stale reference can raise `InventoryChangedError`. `ItemView` is a
read-only description, including `.key`, `.amount`, `.name`, `.lore`,
`.hasAdditionalData`, and `.truncated`. It cannot be passed back to `setItem` as
a lossless copy of arbitrary item metadata.

## Events and history

### Handlers

```python
from minebridge import Minecraft, events, items
from minebridge.models import ChatEvent

with Minecraft.create("localhost", 4711) as mc:
    def on_chat(event: ChatEvent) -> None:
        if event.message == "!reward":
            result = mc.players.giveItem(event.player, items.EMERALD, 3)
            print(result)
        elif event.message == "!stop":
            mc.events.stop()

    subscription = mc.events.subscribe(events.CHAT_MESSAGE, on_chat)
    try:
        mc.events.run()
    finally:
        subscription.unsubscribe()
```

Handlers execute sequentially in the thread calling `events.run()`; subscribing
alone does not run a handler. Minecraft calls are allowed inside handlers. Keep
handlers short so later events can be dispatched. Python observes events and
cannot synchronously cancel the original Minecraft action.

```text
mc.events.subscribe(eventType, handler=None, *, players=selector.ALL_PLAYERS,
                    world=None, region=None, blocks=None) -> Subscription
```

`players` accepts ALL_PLAYERS, SELF, an explicit online name/UUID/PlayerRef, or a
sequence of explicit players. Other selectors, **including `playerByName()`**, are
not supported as event filters; use `players="YourNick"` here. A
`Region(world_uuid, corner1, corner2)` restricts events to an inclusive box.
Chat/join/quit do not support a region. `blocks` restricts block events to a block
description or sequence of descriptions.

| Method | Purpose |
|---|---|
| `mc.events.run()` | Dispatch subscribed handlers until stopped, closed or an error occurs |
| `mc.events.poll(timeout=0.0)` | Consume one live event without calling a handler; `timeout=None` waits indefinitely |
| `mc.events.stop()` | Stop the current consumer while keeping subscriptions and queued events |
| `subscription.unsubscribe()` | Remove the subscription |

| Event constant | Snapshot information |
|---|---|
| `events.CHAT_MESSAGE` | Player, message, cancelled/truncated flags |
| `events.BLOCK_BREAK`, `BLOCK_PLACE` | Player, position, block; replaced block for placement |
| `events.BLOCK_INTERACT` / `BLOCK_HIT` | Player, block, face, action, hand and held item; both names refer to the same type |
| `events.ENTITY_ATTACK` | Player, target and attack/cancellation flags |
| `events.ENTITY_DAMAGE`, `PLAYER_DAMAGE` | Victim, damage cause, direct/causing entity, raw/final damage |
| `events.PROJECTILE_SHOT` | Projectile, shooter, position, velocity and available weapon details |
| `events.PROJECTILE_HIT` | Projectile, shooter, position and hit entity/block/face |
| `events.PLAYER_ENTER_LAVA` | Player and position when contact begins |
| `events.PLAYER_JOIN`, `PLAYER_QUIT` | Player |
| `events.PLAYER_DEATH`, `PLAYER_RESPAWN` | Player and death position or respawn location/reason |

All snapshots carry `.eventId`, `.eventType`, `.world`, `.sequence`, and
`.serverTick`. Event-specific model classes can be imported from
`minebridge.models` for type hints.

### Recent events and polling

History is available without creating a subscription or calling `run()`.

| Method | Purpose |
|---|---|
| `mc.events.pollEvents(eventType, *, limit=100)` | Read the next page and advance this connection's cursor for that type |
| `mc.events.getRecent(eventType, limit=20)` | Read the latest retained events without advancing the polling cursor |
| `mc.events.clearPending(eventType=None)` | Skip unread history for one type, or all types in the connection's world |
| `mc.events.clearAll()` | Alias of `clearPending()` |

Convenience methods, each with keyword-only `limit=100`, are `pollChatPosts()`,
`pollBlockHits()`, `pollEntityAttacks()`, `pollDamageEvents()`,
`pollProjectileShots()`, and `pollProjectileHits()`. They share the corresponding
generic method's cursor. Results are iterable batches; check `.hasMore` on a
`pollEvents` batch to see whether another page is available. Limits are 1–1,000.

History starts when the connection is established, is retained only in a bounded
server memory window, and is independent of live handlers. Each event type and
connection has its own polling cursor; facades sharing a connection share those
cursors. `getRecent` reports `.windowLimited` if retention shortened its window.
`clearPending` does not delete server history or queued live events. Handle
`EventHistoryLostError` if unread history expires. An overflowing live
subscription raises `EventOverflowError`; unsubscribe and create a new one after
addressing the backlog.

## World settings

| Method | Result or accepted value |
|---|---|
| `mc.worlds.getTime(*, world=None)` | Integer time of day, 0–23,999 ticks |
| `mc.worlds.setTime(time, *, world=None)` | Set time of day; returns `None` |
| `mc.worlds.getWeather(*, world=None)` | `Weather` |
| `mc.worlds.setWeather(weather, *, world=None)` | Set CLEAR/RAIN/THUNDER; returns `None` |
| `mc.worlds.getGameRule(rule, *, world=None)` | `bool` or `int`, depending on the rule |
| `mc.worlds.setGameRule(rule, value, *, world=None)` | Set a typed rule; returns `None` |

```python
from minebridge import Minecraft, gamemode, gamerule, selector, weather

with Minecraft.create("localhost", 4711) as mc:
    mc.players.setGameMode(selector.ALL_PLAYERS, gamemode.CREATIVE)
    mc.worlds.setGameRule(gamerule.KEEP_INVENTORY, True)
    mc.worlds.setGameRule(gamerule.DO_DAYLIGHT_CYCLE, False)
    mc.worlds.setTime(6000)
    mc.worlds.setWeather(weather.CLEAR)
```

`world=None` uses the connection's world; a name/key selects another already
loaded world. Game modes also accept lowercase strings. Weather accepts
`"clear"`, `"rain"`, or `"thunder"`. Game rules accept typed constants or
namespaced key strings; preserve their `bool`/`int` value types. Setting earlier
time can advance the absolute day according to Paper's behavior. Normal game
rules and weather cycles continue unless you change their settings.

## Catalogs and models

Import catalogs directly from `minebridge`; their constants and public method
parameters support IDE completion without connecting to a server.

| Catalog | Examples |
|---|---|
| `block` | `COBBLESTONE`, `OAK_LOG`, `OAK_STAIRS` |
| `items` | `IRON_SWORD`, `EMERALD`, `DIAMOND` |
| `entity` | `COW`, `GIANT`, `LIGHTNING_BOLT` |
| `effects` | `SPEED`, `JUMP_BOOST` |
| `selector` | `SELF`, `ALL_PLAYERS`, `playerByName(...)` |
| `events` | `CHAT_MESSAGE`, `BLOCK_BREAK`, `PROJECTILE_SHOT` |
| `gamemode` | `SURVIVAL`, `CREATIVE`, `ADVENTURE`, `SPECTATOR` |
| `weather` | `CLEAR`, `RAIN`, `THUNDER` |
| `gamerule` | `KEEP_INVENTORY`, `DO_DAYLIGHT_CYCLE` |
| `slots` | `HEAD`, `CHEST`, `LEGS`, `FEET`, `OFF_HAND` |
| `damageCause` | Damage-cause constants for inspecting event snapshots |

Catalogs target the tested Paper 26.2 registry. A catalog entry does not imply
every operation is valid for that type: for example, a player cannot be spawned
and an item entity requires an item description. Public descriptions and result
models such as `BlockSpec`, `ItemStack`, `PlayerRef`, `Region`, and `ChatEvent`
are available from `minebridge.models`.

## Errors

```python
from minebridge import Minecraft, entity, errors

with Minecraft.create("localhost", 4711) as mc:
    try:
        mc.spawnEntity(0, 81, 0, entity.GIANT)
    except errors.PeacefulSpawnError:
        print("This mob cannot spawn while the destination world is Peaceful.")
```

Catch `errors.MinecraftError` for Minebridge failures or a specific subclass:

| Error | Typical cause |
|---|---|
| `ConnectionError`, `OperationTimeoutError` | Wrong address/port, unreachable plugin or timeout |
| `AuthenticationError` | Token mismatch when server authentication is enabled |
| `PlayerNotFoundError`, `InvalidTargetError` | Missing explicit player or unsuitable selection |
| `MissingContextError`, `ContextWorldMismatchError` | SELF/spatial selector lacks the required player context |
| `UnsupportedLegacyBlockError` | No supported, unambiguous numeric block mapping |
| `CoordinateOutOfBoundsError`, `ChunkLoadError`, `RegionBusyError` | World bounds, failed chunk load or overlapping active Minebridge changes |
| `PeacefulSpawnError`, `UnsupportedEntityTypeError` | Difficulty blocks the spawn or the type cannot be created this way |
| `InventoryNotFoundError`, `InventoryChangedError`, `InvalidSlotError`, `InvalidItemAmountError` | Unsupported container, stale chest layout, invalid slot or stack amount |
| `EventHistoryLostError`, `EventOverflowError` | Expired unread history or live-event backlog |
| `UnsupportedFeatureError`, `ProtocolVersionError` | Plugin/package capabilities or protocol do not match |

Failures expose `.code`, `.method`, `.request_id`, and `.outcome`; a buffered
barrier may also carry `.failures`. A deferred write error can surface on a later
read, `flush()` or `close()`. If `.outcome == "unknown"`, the server may already
have applied the change. Mutations are never automatically retried. Server
confirmation means the operation ran, not that the world was saved to disk.

For additional Russian-language detail, see the [core API](API_V0_2.ru.md) and
[events, inventories and world settings](API_V0_3.ru.md).
