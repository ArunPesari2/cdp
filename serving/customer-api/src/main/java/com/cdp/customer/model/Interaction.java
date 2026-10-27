package com.cdp.customer.model;

public record Interaction(
        String eventId,
        String eventTs,
        String eventType,
        String channel,
        String intent,
        String agentId,
        Long durationSec,
        String summary,
        String source) {
}
