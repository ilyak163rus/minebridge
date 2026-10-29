# Getting started

Minebridge connects a Python program to a Minecraft Java Edition server. Install
the **Paper plugin on the server** and the **Python package on your computer**.
Minecraft clients do not need a mod.

You need Python **3.11 or newer** and a **Paper 26.2 server running Java 25**.
The tested server is Paper 26.2 build 133; other Minecraft versions have not been
verified. Install matching versions of the plugin and Python package.

## 1. Install the server plugin

1. Download `minebridge-paper-0.3.1.jar` from the
   [v0.3.1 release](https://github.com/ilyak163rus/minebridge/releases/tag/v0.3.1).
2. Stop your Paper server. Copy the JAR into its `plugins` folder, replacing any
   older Minebridge JAR.
3. Start the server. Minebridge creates `plugins/Minebridge/config.yml`.
4. Look for `TCP listener ready on port 4711` in the server console.

For Python running on the **same computer as the server**, the defaults work:

```yaml
listenAddress: '127.0.0.1'
port: 4711
authEnabled: false
token: ''
```

There is no world name to configure. Minebridge selects the primary Overworld
automatically, even if you recreate it with a different folder name.

### Connecting from another computer

Stop the server, set `listenAddress` to the **server computer's numeric LAN IP**,
and restart. For example:

```yaml
listenAddress: '192.168.0.200'
port: 4711
authEnabled: false
token: ''
```

Allow incoming TCP connections to that port in the server computer's firewall.
Use the same address and port in Python. `127.0.0.1` always means the computer
running your program; it cannot reach a server on another computer.

If RaspberryJuice already uses port 4711, give Minebridge another port, such as
4712, in **both** the config and Python. Minebridge and RaspberryJuice use
different protocols.

The default setup is intended for a trusted local environment: anyone who can
connect can change the world. For a shared deployment, restrict network access
and optionally enable `authEnabled: true` with a nonempty `token`; pass that token
to `Minecraft.create(..., token="your-token")`. The connection is plain TCP, so
a token does not provide encrypted transport.

## 2. Install the Python package

Download `minebridge-0.3.1-py3-none-any.whl` from the same release. In the folder
containing the downloaded file, run:

```shell
python -m pip install --upgrade ./minebridge-0.3.1-py3-none-any.whl
```

Using a virtual environment is recommended. The package has no external runtime
dependencies. These instructions install the release file directly; they do not
require a PyPI listing.

Check the installation:

```shell
python -c "import minebridge; print(minebridge.__version__)"
```

In VS Code, install the Python and Pylance extensions and select the interpreter
used for installation with **Python: Select Interpreter**. Completions for
`mc.`, `block.`, `items.`, `entity.`, and the other catalogs work without a server
connection.

## 3. Run your first program

Save this as `build.py` and run `python build.py`. Choose a clear area first:
these coordinates are absolute and the program replaces the blocks there.

```python
from minebridge import Minecraft, block

with Minecraft.create("127.0.0.1", 4711) as mc:
    mc.setBlocks(0, 80, 0, 9, 80, 9, block.COBBLESTONE)
    mc.setBlock(0, 81, 0, block.OAK_LOG.withStates(axis="x"))
    mc.flush()
    print(mc.getBlock(0, 80, 0))        # 4: legacy cobblestone ID
    print(mc.blocks.getBlock(0, 81, 0)) # Modern block key and states
    mc.postToChat("Built with Python!")
```

Replace `127.0.0.1` if your server runs on another computer. Join the Minecraft
server and visit the coordinates to see the result. The server loads needed
chunks automatically; a player does not have to stand near the build.

By default, block writes and chat are buffered for speed. `mc.flush()` waits for
pending writes and reports errors. Reads and methods returning server results
also wait for earlier writes. Leaving the `with` block finishes pending writes
and closes the connection. To wait after every block or chat command, use
`Minecraft.create("127.0.0.1", 4711, writeMode="sync")`.

## 4. Choose a player

Use the player's current online name, with the exact capitalization:

```python
from minebridge import Minecraft, effects, items, selector

with Minecraft.create("127.0.0.1", 4711) as mc:
    player = selector.playerByName("YourNick")
    print(mc.players.giveItem(player, items.EMERALD, 3))
    mc.effects.add(player, effects.SPEED, 30, 2)  # 30 seconds, level 2
```

`selector.ALL_PLAYERS` targets every online player. To use `selector.SELF`, bind
the current player explicitly:

```python
from minebridge import Minecraft, selector

with Minecraft.create("127.0.0.1", 4711, player="YourNick") as mc:
    print(mc.players.getPos(selector.SELF))
```

SELF is chosen by the `player` argument, not by the computer or IP address.
Change the argument when the player's name changes.

## Troubleshooting

| Symptom | What to check |
| --- | --- |
| `ModuleNotFoundError` | Install the wheel with the same Python interpreter that runs your program. |
| Connection refused or timed out | Check the listener message, server IP, port, `listenAddress`, and firewall. |
| RaspberryJuice errors in the server log | Your Python program reached RaspberryJuice's port. Use Minebridge's port. |
| Listener cannot start | The address must belong to the server computer, and the port must be free. |
| `MissingContextError` | Pass `player="YourNick"` when using SELF or a selector requiring an origin. |
| `PlayerNotFoundError` | The specified player must be online under that current name. |
| An item reward appears to do nothing | Inspect `giveItem`'s `given` and `leftovers`; a full inventory cannot receive more items. |
| `PeacefulSpawnError` | That entity cannot spawn at the destination world's Peaceful difficulty. |
| Error appears at `flush()` or when closing | Buffered writes report server errors at the next synchronization point. |

For server-side action logs, connect with `logging=True`. This logs actions from
that connection in the server console and `logs/latest.log`; logging is off by
default.

Continue with [recipes](RECIPES.md), the
[documentation index](../README.md), or [runnable examples](../../examples).
