package dev.minebridge.protocol;

import java.util.Objects;
import java.util.regex.Pattern;

/** Preserves the JSON number spelling without rounding or allocating huge integers. */
public record JsonNumber(String text) {
    private static final Pattern NUMBER = Pattern.compile("-?(?:0|[1-9][0-9]*)(?:\\.[0-9]+)?(?:[eE][+-]?[0-9]+)?");

    public JsonNumber {
        Objects.requireNonNull(text, "text");
        if (!NUMBER.matcher(text).matches()) throw new IllegalArgumentException("Invalid JSON number");
    }

    @Override public String toString() { return "JsonNumber[redacted]"; }
}
