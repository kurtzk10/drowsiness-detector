package com.drowsiness.alert;

public class Event {
    public static final String TYPE_DROWSY = "drowsy";
    public static final String TYPE_YAWNING = "yawning";
    public static final String TYPE_NOT_LOOKING = "not_looking";

    private final String type;
    private final long timestamp;
    private long endTimestamp;

    public Event(String type, long timestamp) {
        this.type = type;
        this.timestamp = timestamp;
        this.endTimestamp = 0;
    }

    public String getType() { return type; }
    public long getTimestamp() { return timestamp; }
    public long getEndTimestamp() { return endTimestamp; }
    public void setEndTimestamp(long end) { this.endTimestamp = end; }

    public long getDurationMs() {
        if (endTimestamp == 0) return 0;
        return endTimestamp - timestamp;
    }

    public String getFormattedTime() {
        java.text.SimpleDateFormat sdf = new java.text.SimpleDateFormat("HH:mm:ss", java.util.Locale.US);
        return sdf.format(new java.util.Date(timestamp));
    }

    public String getFormattedDuration() {
        long ms = getDurationMs();
        if (ms == 0) return "";
        long sec = ms / 1000;
        if (sec < 60) return sec + "s";
        return (sec / 60) + "m " + (sec % 60) + "s";
    }
}
