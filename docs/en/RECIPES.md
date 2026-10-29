# Recipes

Small programs you can adapt for builds, lessons, and game mechanics. Each
example opens and closes its own connection. Use your server's address and port
and choose a clear area before changing blocks. Installation is covered in
[Getting started](GETTING_STARTED.md).

## Build and read blocks

```python
from minebridge import Minecraft, block

with Minecraft.create("127.0.0.1", 4711) as mc:
    # Both corners are included: 10 × 1 × 10 blocks.
    mc.setBlocks(0, 80, 0, 9, 80, 9, block.COBBLESTONE)
    mc.setBlock(0, 81, 0, block.OAK_STAIRS.withStates(facing="east"))
    mc.setBlock(1, 81, 0, block.OAK_LOG.withStates(axis="z"))

    print(mc.getBlock(0, 80, 0))                  # Legacy numeric ID: 4
    print(mc.getBlocks(0, 80, 0, 1, 80, 1))       # {(x, y, z): numeric_id}
    print(mc.blocks.getBlock(0, 81, 0))           # BlockSpec: key and states
    print(mc.blocks.getBlocks(0, 81, 0, 1, 81, 0)) # {(x, y, z): BlockSpec}
```

`block.` contains typed constants for the pinned Minecraft version. States are
named string properties; Paper validates property names and values. Numeric IDs
work for the supported legacy subset. Modern blocks or states without an
unambiguous legacy mapping require `mc.blocks.getBlock()` / `getBlocks()`.

The server loads needed chunks automatically. In 0.3.1, fills of up to 32,768
blocks use one server pass once the chunks are ready; larger fills continue in
portions. Generation and block physics still affect the time required. The
maximum volume of one fill request is 1,000,000 blocks.

## Select players, teleport, and give rewards

Replace `YourNick` with a player who is currently online.

```python
from minebridge import Minecraft, effects, gamemode, items, selector

with Minecraft.create("127.0.0.1", 4711, player="YourNick") as mc:
    print(mc.players.list())
    print(mc.getPlayerEntityId("YourNick"))
    print(mc.players.getPos(selector.SELF))

    # Create a small platform before teleporting onto it.
    from minebridge import block
    mc.setBlocks(10, 80, 10, 14, 80, 14, block.STONE)
    print(mc.setPos(selector.SELF, 12.5, 81, 12.5))
    mc.players.setGameMode(selector.SELF, gamemode.CREATIVE)

    result = mc.players.giveItem(selector.SELF, items.EMERALD, 3)
    for outcome in result.targets:
        print("Given:", outcome.given, "Left over:", outcome.leftovers)

    mc.effects.add(selector.SELF, effects.SPEED, 100, 200)
    # The two numbers mean 100 seconds, level 200.
    mc.effects.remove(selector.SELF, effects.SPEED)
```

Other targets include `selector.ALL_PLAYERS`, `selector.RANDOM_PLAYER`, and
`selector.playerByName("YourNick")`. `selector.NEAREST_PLAYER` requires an
explicit player context, as does SELF. A named selector is case-sensitive and
resolves the online player again on each request; it does not bind SELF.

Group operations return per-target results. An offline name can select an empty
group, whereas methods requiring exactly one player report a selection error.
`giveItem` leaves inventory overflow in its result by default. Use
`overflow="drop"` explicitly to drop leftover items beside the recipient.

## React to chat

Run the program, then send `!reward` or `!stop` in Minecraft chat.

```python
from minebridge import Minecraft, events, items
from minebridge.models import ChatEvent

with Minecraft.create("127.0.0.1", 4711) as mc:
    def on_chat(event: ChatEvent) -> None:
        print(event.player.name, event.message)
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

Registering a handler starts the subscription. Call `mc.events.run()` to execute
handlers in the thread calling `run`; commands inside a handler are supported.
Keep handlers short so other incoming events can be processed. Python observes
events after they occur and cannot synchronously cancel them on the server.
`mc.postToChat()` does not trigger a new player chat event.

## React to broken blocks and lava

```python
from minebridge import Minecraft, block, events, items
from minebridge.models import BlockBreakEvent, LavaEnterEvent

with Minecraft.create("127.0.0.1", 4711) as mc:
    def on_break(event: BlockBreakEvent) -> None:
        if not event.cancelled:
            mc.players.giveItem(event.player, items.DIAMOND, 1)

    def on_lava(event: LavaEnterEvent) -> None:
        print(event.player.name, "entered lava at", event.position)

    subscriptions = [
        mc.events.subscribe(events.BLOCK_BREAK, on_break, blocks=block.COBBLESTONE),
        mc.events.subscribe(events.PLAYER_ENTER_LAVA, on_lava),
    ]
    try:
        mc.events.run()  # Ctrl+C stops this example.
    finally:
        for subscription in subscriptions:
            subscription.unsubscribe()
```

The event catalog also includes block placement and interaction, entity attacks
and damage, player damage, projectile shots and hits, joining, quitting, death,
and respawning. For a subscription's `players` filter, use an explicit name such
as `players="YourNick"`, a player reference, ALL_PLAYERS, or SELF; arbitrary
selector expressions, including `playerByName()`, are not accepted there.

## Read event history without callbacks

```python
import time
from minebridge import Minecraft, events

with Minecraft.create("127.0.0.1", 4711) as mc:
    print("Send a few chat messages or fire an arrow during the next 10 seconds.")
    time.sleep(10)

    for message in mc.events.pollChatPosts():
        print(message.player.name, message.message)

    for shot in mc.events.pollProjectileShots():
        print("Projectile:", shot.projectile, "Shooter:", shot.shooter)

    for message in mc.events.getRecent(events.CHAT_MESSAGE, 5):
        print("Recent:", message.message)
```

History starts when the connection is established and is independent of live
callbacks. `pollChatPosts()` advances the chat cursor; `getRecent()` reads recent
records without advancing it. History and live queues are bounded in memory:
`EventHistoryLostError` and `EventOverflowError` report missed history and live
queue overflow respectively. This is not persistent replay across connections.

## Put items in chest and player slots

This example creates a chest, replacing the block at the chosen coordinates.

```python
from minebridge import Minecraft, block, items, selector, slots

with Minecraft.create("127.0.0.1", 4711, player="YourNick") as mc:
    mc.setBlock(20, 80, 20, block.CHEST)
    chest = mc.inventories.ofBlock(20, 80, 20)
    chest.setItem(0, items.DIAMOND, 16)
    print(chest.getItem(0))
    print(chest.getContents())
    chest.clear(0)

    player_inventory = mc.inventories.ofPlayer(selector.SELF)
    player_inventory.setItem(0, items.IRON_SWORD, 1)
    player_inventory.setItem(slots.OFF_HAND, items.SHIELD, 1)
```

`setItem()` **replaces** that slot's contents. Slot numbers start at zero:
physical chest slots are 0–26; player storage slots are 0–35, with armor and
off-hand addressed by `slots.` constants. Item amounts must fit the item's
native stack limit. Empty slots read as `None`.

For a double chest, `ofBlock(..., combined=True)` addresses the combined
27- or 54-slot inventory. Obtain a new reference if the chest layout changes.
`ItemView` is a read-only snapshot of supported fields; it is not a complete
copy of every Minecraft item component.

## Spawn entities

```python
from minebridge import Minecraft, entity, errors

with Minecraft.create("127.0.0.1", 4711) as mc:
    cow = mc.spawnEntity(30, 80, 30, entity.COW)
    print(cow.uuid)

    try:
        mc.spawnEntity(32, 80, 30, entity.ZOMBIE)
    except errors.PeacefulSpawnError:
        print("This mob cannot spawn because the destination world is Peaceful.")
```

The `entity.` catalog includes living mobs and other entity types. Some require
extra parameters, such as `item=` for a dropped item or `block=` for a falling
block; consult the [entity reference in Russian](../API_V0_2.ru.md).
`entity.LIGHTNING_BOLT` creates real lightning and can cause damage or fire.
Minebridge does not change world difficulty automatically.

## Set world time, weather, and game rules

```python
from minebridge import Minecraft, gamerule, weather

with Minecraft.create("127.0.0.1", 4711) as mc:
    mc.worlds.setTime(1000)
    mc.worlds.setWeather(weather.CLEAR)
    mc.worlds.setGameRule(gamerule.ADVANCE_TIME, False)
    print(mc.worlds.getTime())
    print(mc.worlds.getGameRule(gamerule.ADVANCE_TIME))
```

Time uses Minecraft ticks from 0 to 23,999. These methods affect the selected
world, defaulting to the primary Overworld. To allow time to advance again,
set `gamerule.ADVANCE_TIME` to `True`.

## Wait for completion and diagnose errors

```python
from minebridge import Minecraft, block

with Minecraft.create("127.0.0.1", 4711, logging=True) as mc:
    mc.setBlock(0, 80, 0, block.STONE)
    mc.flush()  # Wait for completion and surface buffered errors here.
```

Block and chat writes are buffered by default. `flush()`, reads, methods that
return server results, and `close()` wait for preceding writes. An acknowledged
operation has completed on the server; that is not a promise that the world has
been saved to disk. A lost connection can leave an operation's outcome unknown,
so the library does not silently retry mutations.

See the [documentation index](../README.md) for the detailed API reference and
the [runnable examples](../../examples) for larger programs.
