package dev.minebridge.transport;

import dev.minebridge.protocol.JsonRpcCodec;
import dev.minebridge.protocol.Request;
import dev.minebridge.session.Session;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.HashMap;
import java.util.Map;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Test-only consumer; it never ships in the plugin and performs no game operation. */
public final class TransportHarness {
    private TransportHarness() { }

    public static void main(String[] args) throws Exception {
        TcpServer server = new TcpServer("127.0.0.1", 0, TransportLimits.defaults());
        AtomicBoolean stop = new AtomicBoolean();
        Map<UUID, Long> lastIds = new HashMap<>();
        int handled = 0;
        try {
            server.start();
            int port = server.ready().get(3, TimeUnit.SECONDS).getPort();
            Thread console = new Thread(() -> {
                try {
                    new BufferedReader(new InputStreamReader(System.in, StandardCharsets.UTF_8)).readLine();
                } catch (Exception ignored) {
                    // EOF/closed stdin also ends this test-only harness.
                } finally {
                    stop.set(true);
                }
            }, "minebridge-test-console");
            console.setDaemon(true);
            console.start();
            System.out.println("{\"port\":" + port + "}");
            System.out.flush();
            while (!stop.get()) {
                for (Session session : server.sessions()) {
                    // Trusted test seam, not a production authentication path.
                    session.markReady();
                    Request request = session.pollRequest();
                    if (request == null) continue;
                    long previous = lastIds.getOrDefault(session.id(), 0L);
                    if (request.id() <= previous) throw new AssertionError("IDs did not increase");
                    lastIds.put(session.id(), request.id());
                    if (!session.sendFrame(JsonRpcCodec.errorFrame(request.id(), "METHOD_NOT_FOUND", "not-applied"))) {
                        throw new AssertionError("Test response was not queued");
                    }
                    handled++;
                }
                Thread.sleep(2);
            }
        } finally {
            server.close();
            if (!server.awaitTermination(Duration.ofSeconds(3))) throw new AssertionError("Reactor did not stop");
        }
        System.out.println("{\"handled\":" + handled + ",\"respondingSessions\":" + lastIds.size()
                + ",\"terminated\":true}");
    }
}
