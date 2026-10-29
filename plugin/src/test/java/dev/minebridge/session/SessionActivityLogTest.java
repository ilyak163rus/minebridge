package dev.minebridge.session;

import dev.minebridge.protocol.Request;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import static org.junit.jupiter.api.Assertions.*;

class SessionActivityLogTest {
    @Test void logEscapesControlCharactersBoundsPayloadsAndNeverPerformsIoAtPublicationBoundary() {
        SessionActivityLog log = new SessionActivityLog();
        Session session = new Session(4, 4, () -> {});
        session.enableActivityLog(log);
        Request request = new Request(2L, "chat.post", Map.of("message", "hello\nFAKE\r\u001b" + "x".repeat(10000)));
        session.logRequest(request);
        session.sendResult(request, Map.of("applied", true));
        List<String> lines = new ArrayList<>();
        log.drain(line -> {
            assertFalse(Thread.holdsLock(session));
            assertFalse(line.contains("\n"));
            assertFalse(line.contains("\r"));
            assertTrue(line.length() < 2100);
            lines.add(line);
        });
        assertEquals(2, lines.size());
        assertTrue(lines.getFirst().contains("\\u000aFAKE\\u000d\\u001b"));
        assertTrue(session.isOpen());
        assertDoesNotThrow(() -> log.drain(line -> { throw new IllegalStateException(); }));
    }

    @Test void overflowIsExplicitAndDefaultSessionsDoNotLog() {
        SessionActivityLog log = new SessionActivityLog();
        Session session = new Session(4, 4, () -> {});
        Request request = new Request(2L, "chat.post", Map.of("message", "hello"));
        session.logRequest(request);
        List<String> lines = new ArrayList<>();
        log.drain(lines::add);
        assertTrue(lines.isEmpty());
        session.enableActivityLog(log);
        for (int i = 0; i < 4100; i++) session.logRequest(request);
        log.drain(lines::add);
        assertEquals(4097, lines.size());
        assertTrue(lines.getLast().contains("omitted=4"));
        log.drain(lines::add);
        assertEquals(4097, lines.size());
    }
}
