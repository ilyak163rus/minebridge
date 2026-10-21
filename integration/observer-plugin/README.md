# Local integration observer

This is a test plugin for disposable Paper worlds. It is built as the separate
`:observer` Gradle subproject and is never included in the production bridge JAR.
It has no network listener, player command, production RPC method or background
worker. It depends on the `Minebridge` plugin only for the optional local
`TestControl` service. World snapshots call Paper directly and do not use bridge
block services, RPC results, requested materials, or an expected ACK value.

The orchestrator writes this command to the Paper process console:

```
mbobserve <caseId> <requestId> <action> [arguments]
```

Both IDs must be 32 lowercase hexadecimal characters. `requestId` is unique for
the entire server run; it is not the numeric JSON-RPC request ID. Only a console
sender is accepted. At most 4096 commands, 16 active cases and 16 prepared
positions per case are accepted. Replayed request IDs are ignored before any
operation. Each command publishes a new immutable file:

```
plugins/MinebridgeObserver/results/<requestId>.json
```

The file is UTF-8 JSON with one trailing newline. A private `.tmp` path is
written before the unique final path is published without replacement. This
avoids replacing a file while a Windows reader holds it open. The orchestrator
waits for this file with a finite deadline and checks all correlation fields:

```json
{
  "schemaVersion": 1,
  "caseId": "0123456789abcdef0123456789abcdef",
  "requestId": "fedcba9876543210fedcba9876543210",
  "action": "read",
  "status": "ok",
  "sequence": 8,
  "tick": 260,
  "primaryThread": true,
  "threadId": 33,
  "result": {}
}
```

Errors use `"status":"error"` and a fixed string `error` field instead of
`result`. Exception messages and command arguments are never echoed. `sequence`
is a monotonic observer publication sequence; `tick` is the actual Paper tick.
This counter is independent from production trace event sequences. Every
snapshot is read and every response is published on the Paper main thread.
`threadId` identifies the actual observer command execution thread.

| Action and arguments | Result |
|---|---|
| `worlds` | `worlds`: entries with `name`, `uuid`, `minY`, `maxYExclusive` |
| `setup <worldUUID> <x,y,z>...` | `originals`, post-preparation `snapshots`, and `chunks` |
| `seed <worldUUID> <x> <y> <z> <key>` | Prepare one owned position as AIR, STONE or COBBLESTONE and return an actual snapshot |
| `read <worldUUID> <x> <y> <z>` | One block snapshot; never loads an absent chunk |
| `checkChunk <worldUUID> <chunkX> <chunkZ>` | `world`, chunk coordinates, `loaded`, observer's `ticketHeld` |
| `unload <worldUUID> <chunkX> <chunkZ> <deadlineTicks>` | A chunk snapshot after `loaded=false`; fixed error on deadline |
| `border <worldUUID> <size> <centerX> <centerZ>` | Actual border size and center |
| `restoreBorder <worldUUID>` | Restored border size and center |
| `cleanup` | `restoredBlocks`, `releasedChunks`, `remainingCases` |
| `status` | `controlEnabled`, `sessions` |
| `gateArm <sessionUUID> <rpcId>` | Gate status |
| `track <sessionUUID> <rpcId>` | Correlates a request to this case without gating; gate status |
| `gateRelease <sessionUUID> <rpcId>` | Gate status after release |
| `gateStatus <sessionUUID> <rpcId>` | Gate status, including a disconnected session's cancellation |
| `trace <afterSequence>` | Expanded production events and trace buffer counters |
| `writerPause <sessionUUID>` | Pause only this READY connection's NIO writer; bounded session statistics |
| `writerResume <sessionUUID>` | Resume a writer owned by this case; retained statistics |
| `sessionStats <sessionUUID>` | Retained statistics of a request tracked by this case or its paused writer, including after close |

World UUIDs use canonical lowercase UUID syntax. Position integers are decimal
int32 and Y is checked against the actual world's bounds. X/Z fixture positions
are confined to Minecraft's absolute world limit. `setup` explicitly loads and
holds each position's chunk, including negative coordinates using `floorDiv`.
It saves cloned original `BlockData` before clearing positions to AIR without
physics. `originals` records the data before clearing; `snapshots` records the
independent Paper read after clearing. Positions owned by another case are
rejected. Distinct cases may share a chunk with reference-counted tickets.
The `seed` fixture action accepts only `minecraft:air`, `minecraft:stone`, and
`minecraft:cobblestone` at a position already owned by this case. It uses Paper
directly without physics and preserves the original data for cleanup. The
oracle self-test seeds two distinct block values before reading them so a
constant-AIR or one-position reader cannot pass.

A block snapshot contains:

```
world, x, y, z, key, properties, blockData
```

`world` is the Paper world's actual UUID. `key` and the alphabetically sorted
`properties` map are parsed from Paper's actual full `BlockData#getAsString()`;
`blockData` retains that full string. This is a direct world observation, not a
copy of the desired block or a bridge return value.

`unload` is allowed only for a chunk owned exclusively by this case. It first
restores original fixture blocks in that chunk, removes its own ticket, asks
Paper to unload, and polls `isChunkLoaded` once per tick for 1–400 ticks. It never
sleeps or waits on the game thread. A still-loaded chunk produces
`UNLOAD_TIMEOUT`, never a false success. Setup/loading and final cleanup are
explicit fixture operations; ordinary reads and checks never load a chunk.

The observer saves the border center and size only when changing them. Border
ownership cannot overlap between cases. Cleanup restores original block data
and any changed border, cancels this case's unload polling, and releases only
this observer's tickets. A cleanup after an unload may explicitly load the
fixture chunk to restore its blocks. The world remains disposable: block
entities, scheduled ticks, terrain generation and disk rollback are not an
oracle offered by this fixture. Use stable AIR/STONE/COBBLESTONE positions as
specified by the integration test plan. Disable also restores every active
case and removes this plugin's remaining tickets.

Local test control exists only when the bridge's explicit JVM integration switch
is enabled. Without it, `status` reports `controlEnabled=false`; gate/trace/writer
commands return `CONTROL_DISABLED`. World reads still work. A session status
contains `sessionId`, `ready`, `open`, `queuedRequests`, `outputFrames`, plus
payload-free diagnostics `writerPaused`, `requestHighWater`, `outputHighWater`,
`receivedFrames`, and `partialFrameBytes`. `receivedFrames` counts complete
frames returned by the reactor's decoder, including hello; `partialFrameBytes`
is its currently observed incomplete payload length. Queue high-water marks
never exceed their actual capacities and survive connection close. A gate
status contains `caseId`, `sessionId`, numeric `requestId`, `state`,
`sessionOpen`, and `queuedRequests`. State is `ARMED`, `GATED`, `RELEASED`, or
`CANCELLED`; `track` uses `RELEASED`.

The T10 writer pause is a local deterministic backpressure fixture. It removes
OP_WRITE interest and prevents the reactor from writing this connection, while
input, other sessions and game ticks continue normally. It never waits or does
socket IO on the game thread. Pause does not alter the production five-second
write deadline, output capacity or RPC profile. The orchestrator pauses before
sending target requests and explicitly observes each queue size. This exercises
the production bounded-output/deadline policies without assuming a portable OS
socket-buffer size; it is not a throughput measurement of a physical LAN peer.
Only a case that owns the paused writer may resume it. Cleanup and service
shutdown remove pauses; closed connections retain only bounded diagnostic state
until that case is cleared. No writer command exists in production JSON-RPC,
and no new plugin configuration key enables one.

`trace` returns `events`, `latestSequence`, `oldestSequence`, `droppedEvents`,
`evictedEvents`. Event fields are `sequence`, `phase`, `sessionId`, `requestId`,
`applySequence`, `threadId`, `primaryThread`, `caseId`, `worldName`, `worldUuid`,
`x`, `y`, `z`, `errorCode`, and `outcome`; unpopulated metadata is JSON null.
The trace is diagnostic evidence about the bridge's execution points. Its
thread flags do not replace the independent world snapshot, and the observer's
main-thread flag does not prove the setter's execution thread.

Cleanup calls `TestControl.clearCase` before restoring world data. Active gates
or queued/active tracked request IDs produce `CASE_BUSY`, preventing those delayed
requests from writing after fixture restoration. Other request IDs and future
requests on a released session are outside that guard. The orchestrator must
await all its calls, or close the clients and observe cancellation, before cleanup.
