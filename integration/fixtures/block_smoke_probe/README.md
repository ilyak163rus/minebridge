This is an explicitly built, separate T06 local smoke fixture. It does not depend
on Minebridge classes and has no socket listener. Only the server console can
invoke `mbblockprobe`; the Python harness writes commands to Paper's stdin.
Each command publishes one immutable `results/<correlation>.tsv` file. The harness
reads and removes it after closing its handle. No published result is replaced,
so polling cannot block publication through Windows file sharing rules.

The fixture writes loaded-world metadata, prepares and pins three specified test
chunks, reads actual block data independently of the bridge, reports chunk load
state, and temporarily adjusts the world border. It records the original test
blocks and border and restores them during normal disable. Only fixture setup
loads/generates chunks; `read` first checks loaded status. All work uses Paper's
main thread. No token is passed to this fixture.

Chunk generation and plugin tickets can retain loaded neighbors. The real-Paper
loaded-only case therefore uses a distant negative chunk and checks its actual
loaded status before and after the rejected request. It does not assume an
adjacent chunk is unloaded. The precise floorDiv-versus-truncation distinction
is verified by the BlockService unit tests.

The production JAR must exclude this fixture. Run `blockSmokeProbeJar` explicitly.
This smoke does not replace the complete T08 observer, execution trace or gate
needed for later ordering/failure proofs.
