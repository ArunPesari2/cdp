"""Build storage rows from a resolved canonical event."""

from datetime import datetime, timezone

INTERACTION_SPANNER_COLUMNS = (
    "customer_id", "event_ts", "event_id", "event_type", "channel", "intent",
    "agent_id", "duration_sec", "summary", "source",
)


def _ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def interaction_spanner_row(event: dict) -> dict:
    p = event["payload"]
    return {
        "customer_id": event["customer_id"],
        "event_ts": _ts(event["event_ts"]),
        "event_id": event["event_id"],
        "event_type": event["event_type"],
        "channel": p.get("channel"),
        "intent": p.get("intent"),
        "agent_id": p.get("agent_id"),
        "duration_sec": p.get("duration_sec"),
        "summary": p.get("summary"),
        "source": event["source"],
    }


def interaction_bigquery_row(event: dict) -> dict:
    p = event["payload"]
    return {
        "event_id": event["event_id"],
        "customer_id": event["customer_id"],
        "event_ts": _ts(event["event_ts"]).isoformat(),
        "event_type": event["event_type"],
        "source": event["source"],
        "vendor": event.get("vendor"),
        "channel": p.get("channel"),
        "intent": p.get("intent"),
        "agent_id": p.get("agent_id"),
        "duration_sec": p.get("duration_sec"),
        "queue": p.get("queue"),
        "summary": p.get("summary"),
        "processed_ts": datetime.now(timezone.utc).isoformat(),
    }
