"""Canonical CDP event definitions (mirrors contracts/events/*.avsc)."""

CONTACT_ENDED = "contact_ended"

CARE_CHANNELS = ("call", "chat")
CARE_INTENTS = (
    "network_issue",
    "billing_question",
    "upgrade_inquiry",
    "plan_change",
    "device_support",
    "cancel_request",
)

ENVELOPE_REQUIRED = ("event_id", "event_type", "schema_version", "event_ts", "source", "identifiers", "payload")
CONTACT_ENDED_PAYLOAD_REQUIRED = ("channel", "intent", "agent_id", "duration_sec", "summary")
