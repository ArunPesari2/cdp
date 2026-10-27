"""Adapter: vendor contact record (Amazon Connect CTR style) -> canonical contact_ended event.

Field mapping (docs/contracts/care-data-contract.md):
  ContactId                         -> event_id
  DisconnectTimestamp               -> event_ts (UTC, milliseconds, e.g. 2026-10-18T09:47:29.000Z)
  CustomerEndpoint.Address          -> identifiers.phone
  Channel VOICE|CHAT                -> payload.channel call|chat
  Attributes.intent                 -> payload.intent
  Agent.Username agentNNNN          -> payload.agent_id A-NNNN
  Disconnect - Initiation (seconds) -> payload.duration_sec (rounded)
  Queue.Name                        -> payload.queue
  Attributes.summary                -> payload.summary

Vendor timestamps must carry an explicit offset (Z or +hh:mm); the time zone is never guessed.
"""

from datetime import datetime, timezone

from cdp_common.events import CONTACT_ENDED

from cdp_beam.dead_letter import RejectedRecord

VENDOR = "connect"
_CHANNELS = {"VOICE": "call", "CHAT": "chat"}


def _lookup(record, *path: str) -> str | None:
    """Walk nested objects to a string field. None if absent or empty; INVALID_TYPE if the shape is wrong."""
    value = record
    for i, key in enumerate(path):
        if not isinstance(value, dict):
            raise RejectedRecord("INVALID_TYPE", f"{'.'.join(path[:i]) or '<root>'} is not an object")
        value = value.get(key)
        if value in (None, ""):
            return None
    if not isinstance(value, str):
        raise RejectedRecord("INVALID_TYPE", f"{'.'.join(path)} is not a string")
    return value


def _required(record, *path: str) -> str:
    value = _lookup(record, *path)
    if value is None:
        raise RejectedRecord("MISSING_FIELD", ".".join(path))
    return value


def _parse_ts(value: str, field: str) -> datetime:
    """ISO-8601 with an explicit offset -> UTC datetime."""
    try:
        ts = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise RejectedRecord("INVALID_TIMESTAMP", f"{field}={value!r}")
    if ts.tzinfo is None:
        raise RejectedRecord("INVALID_TIMESTAMP", f"{field}={value!r} has no time zone")
    return ts.astimezone(timezone.utc)


def _utc_iso(ts: datetime) -> str:
    """Canonical timestamp format: UTC, millisecond precision, Z suffix."""
    return ts.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _agent_id(username: str) -> str:
    return f"A-{username[len('agent'):]}" if username.startswith("agent") else username


def to_canonical(record: dict) -> dict:
    contact_id = _required(record, "ContactId")
    started = _parse_ts(_required(record, "InitiationTimestamp"), "InitiationTimestamp")
    ended = _parse_ts(_required(record, "DisconnectTimestamp"), "DisconnectTimestamp")
    if ended < started:
        raise RejectedRecord("INVALID_TIMESTAMP", "DisconnectTimestamp is before InitiationTimestamp")

    vendor_channel = _required(record, "Channel")
    if vendor_channel not in _CHANNELS:
        raise RejectedRecord("UNSUPPORTED_CHANNEL", vendor_channel)

    return {
        "event_id": contact_id,
        "event_type": CONTACT_ENDED,
        "schema_version": 1,
        "event_ts": _utc_iso(ended),
        "source": "care",
        "vendor": VENDOR,
        "identifiers": {"phone": _required(record, "CustomerEndpoint", "Address")},
        "payload": {
            "channel": _CHANNELS[vendor_channel],
            "intent": _required(record, "Attributes", "intent"),
            "agent_id": _agent_id(_required(record, "Agent", "Username")),
            "duration_sec": round((ended - started).total_seconds()),
            "queue": _lookup(record, "Queue", "Name"),
            "summary": _required(record, "Attributes", "summary"),
        },
    }
