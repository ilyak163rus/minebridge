# Architecture

Minebridge has two runtime components: an installable Python package and a Paper plugin. They communicate over a persistent TCP connection using the versioned [protocol](../protocol/v2/README.md). Minecraft clients do not need a mod.

```text
Python program
  Minecraft facade → domain APIs → TCP transport
                                      │
                                 Paper plugin
                        handshake → request routing
                                      │
                         main-thread Paper operations
                                      │
                         results and event snapshots
```

## Python package

`python/src/minebridge/minecraft.py` exposes the familiar `Minecraft.create`, block methods, `setPos`, `spawnEntity` and `postToChat`. Domain APIs in `api/` handle blocks, players, effects, entities, inventories, events and world settings. Immutable models and static catalogs support IDE completion without a server connection.

The transport handles handshake negotiation, request IDs, ordered responses and error mapping. A receiver thread receives responses and event snapshots; user callbacks run in the thread calling `events.run()`. Alternatively, `events.poll()` returns a live event to the caller without invoking a handler.

Block writes and chat use buffered writes by default. Reads, result-returning operations, `flush()` and `close()` provide completion barriers. Mutations are not automatically retried: a lost acknowledgment may mean an operation already ran. The client reports this through the error's `outcome`.

## Paper plugin

`plugin/src/main/java/dev/minebridge/` contains network/session handling, validation, scheduling and Paper backends. Network threads do not access the world directly. Requests enter bounded queues, and world operations use the server thread. Chunk preparation uses asynchronous loading before mutations are applied.

For regions up to 32,768 blocks with prepared chunks, `setBlocks` uses a single bounded mutation pass. Larger requests use continuations. Normal Paper block states and physics apply. Chunk leases and overlapping-region checks coordinate Minebridge operations; they do not make a build an atomic transaction against other plugins or players.

Paper event listeners capture snapshots for per-session live subscriptions and a bounded in-memory journal. Callbacks and history reads have independent delivery paths. Overflow and history loss are explicit errors; events cannot be synchronously cancelled from Python.

## Identity and worlds

Connections default to the primary Overworld, independent of its directory name. A player's identity for `selector.SELF` is explicitly bound by `player="OnlineNick"` to the online player's UUID. IP addresses and computers do not identify players. Named selectors are resolved when each request runs.

The classroom default is a localhost listener with optional token authentication. Tokens do not encrypt TCP. Deployment details belong in the [setup guide](en/GETTING_STARTED.md).

## Repository map

| Directory | Purpose |
|---|---|
| `python/` | Library, Python tests and package metadata |
| `plugin/` | Paper plugin, Gradle wrapper and Java tests |
| `protocol/` | Wire specifications, schemas and shared validation corpus |
| `catalogs/`, `compat/` | Versioned catalogs and supported legacy block mappings |
| `examples/` | Runnable user programs |
| `integration/` | Disposable-server tests and test-only observer plugin |
| `tools/` | Catalog generation, release tooling and regression runners |
| `docs/` | User guides, reference and technical contracts |

The current public behavior is described in the [API reference](API.md). Detailed contracts under `docs/contracts/` include historical versions; use current API and release notes to determine which rules apply. [Contributing](../CONTRIBUTING.md) explains how to build and test changes.
