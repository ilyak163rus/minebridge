# Moving from mcpi and RaspberryJuice

Minebridge keeps familiar building methods while adding typed catalogs, block states, players, events and inventories. It uses its own Paper plugin and protocol.

## What stays familiar

```python
from minebridge import Minecraft, block

with Minecraft.create("localhost", 4711) as mc:
    mc.setBlock(0, 80, 0, 4)
    mc.setBlocks(1, 80, 0, 10, 80, 10, block.COBBLESTONE)
    mc.postToChat("Hello from Python!")
    print(mc.getBlock(0, 80, 0))  # 4
```

`Minecraft.create(ip, port)`, `mc.getPlayerEntityId("OnlineNick")`, `setBlock` and `setBlocks` retain their names. `from minebridge.minecraft import Minecraft` is also supported. Import block constants with `from minebridge import block`.

## Differences to know

| Topic | Minebridge |
|---|---|
| Server plugin | Install Minebridge, not RaspberryJuice. Give the two plugins different TCP ports if both are installed. |
| Block coordinates | Absolute world coordinates. The main Overworld is selected automatically; no world folder name is required. |
| Numeric block IDs | A supported legacy subset, not every historical ID/data combination. Prefer `block.*` or modern names for new code. Unsupported mappings raise an error. |
| Modern block reads | `mc.blocks.getBlock(x, y, z)` returns `BlockSpec` with `.key` and `.states`. `mc.getBlock` returns a legacy number when one is available. |
| Region reads | `mc.getBlocks(...)` maps `(x, y, z)` coordinates to legacy IDs; `mc.blocks.getBlocks(...)` maps them to `BlockSpec`. |
| Command completion | Block writes and chat are buffered by default. `mc.flush()` waits and reports failures; leaving a `with` block also waits. Use `writeMode="sync"` to wait for each write. |
| Player identity | `selector.SELF` requires `Minecraft.create(ip, port, player="CurrentNick")`. It is not inferred from the computer or IP address. |
| Position | Use `mc.players.getPos(target)` and `mc.setPos(target, x, y, z)`. |
| Events | `mc.events.pollChatPosts()` reads chat history. Subscribe callbacks with `mc.events.subscribe(...)`, then call `mc.events.run()`. |

Minebridge is not a drop-in replacement for the entire mcpi API. Start with a small build, then move player and event code to the [current API](API.md).

[Install Minebridge](en/GETTING_STARTED.md) · [Examples](../examples/README.md)
