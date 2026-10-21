package dev.minebridge.observer;

import java.util.Map;

/** Tiny snapshot serializer, independent of the production RPC codec. */
final class SnapshotJson {
    private SnapshotJson() { }

    static String encode(Object value) {
        StringBuilder result = new StringBuilder();
        append(result, value);
        return result.append('\n').toString();
    }

    private static void append(StringBuilder out, Object value) {
        if (value == null) { out.append("null"); return; }
        if (value instanceof String text) { quote(out, text); return; }
        if (value instanceof Boolean || value instanceof Integer || value instanceof Long) {
            out.append(value); return;
        }
        if (value instanceof Double number && Double.isFinite(number)) { out.append(number); return; }
        if (value instanceof Map<?, ?> entries) {
            out.append('{');
            boolean first = true;
            for (var entry : entries.entrySet()) {
                if (!(entry.getKey() instanceof String key)) throw new IllegalArgumentException();
                if (!first) out.append(',');
                first = false;
                quote(out, key); out.append(':'); append(out, entry.getValue());
            }
            out.append('}'); return;
        }
        if (value instanceof Iterable<?> values) {
            out.append('[');
            boolean first = true;
            for (Object item : values) {
                if (!first) out.append(',');
                first = false; append(out, item);
            }
            out.append(']'); return;
        }
        throw new IllegalArgumentException("Unsupported snapshot value");
    }

    private static void quote(StringBuilder out, String value) {
        out.append('"');
        for (int i = 0; i < value.length(); i++) {
            char ch = value.charAt(i);
            switch (ch) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (ch < 0x20 || Character.isSurrogate(ch)) {
                        out.append("\\u");
                        String hex = Integer.toHexString(ch);
                        out.append("0".repeat(4 - hex.length())).append(hex);
                    } else out.append(ch);
                }
            }
        }
        out.append('"');
    }
}
