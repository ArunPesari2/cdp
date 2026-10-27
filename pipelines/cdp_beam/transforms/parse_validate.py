"""Parse raw vendor messages, adapt them to the canonical envelope, and validate."""

import json

import apache_beam as beam
from apache_beam.metrics import Metrics

from cdp_common.events import CARE_CHANNELS, CARE_INTENTS, CONTACT_ENDED_PAYLOAD_REQUIRED, ENVELOPE_REQUIRED

from cdp_beam.dead_letter import DEAD_LETTER, RejectedRecord, make_dead_letter


class ParseAndAdapt(beam.DoFn):
    """bytes -> vendor dict -> canonical event. Failures go to the dead-letter output."""

    def __init__(self, adapter, source: str):
        self.adapter, self.source = adapter, source
        self.rejected = Metrics.counter(source, "adapter_rejected")

    def process(self, raw: bytes):
        try:
            record = json.loads(raw)
            yield self.adapter(record)
        except UnicodeDecodeError as e:
            self.rejected.inc()
            yield beam.pvalue.TaggedOutput(DEAD_LETTER, make_dead_letter(self.source, "adapter", "INVALID_ENCODING", str(e), raw))
        except json.JSONDecodeError as e:
            self.rejected.inc()
            yield beam.pvalue.TaggedOutput(DEAD_LETTER, make_dead_letter(self.source, "adapter", "INVALID_JSON", str(e), raw))
        except RejectedRecord as e:
            self.rejected.inc()
            event_id = record.get("ContactId") if isinstance(record, dict) else None
            yield beam.pvalue.TaggedOutput(DEAD_LETTER, make_dead_letter(self.source, "adapter", e.code, e.detail, raw, event_id))


def validate_contact_ended(event: dict) -> None:
    """Check a canonical contact_ended event against the contract; raise RejectedRecord if invalid."""
    for field in ENVELOPE_REQUIRED:
        if event.get(field) in (None, ""):
            raise RejectedRecord("MISSING_FIELD", field)
    payload = event["payload"]
    for field in CONTACT_ENDED_PAYLOAD_REQUIRED:
        if payload.get(field) in (None, ""):
            raise RejectedRecord("MISSING_FIELD", f"payload.{field}")
    if payload["channel"] not in CARE_CHANNELS:
        raise RejectedRecord("INVALID_VALUE", f"channel={payload['channel']}")
    if payload["intent"] not in CARE_INTENTS:
        raise RejectedRecord("INVALID_VALUE", f"intent={payload['intent']}")
    if payload["duration_sec"] < 0:
        raise RejectedRecord("INVALID_VALUE", f"duration_sec={payload['duration_sec']}")
    if not event["identifiers"]:
        raise RejectedRecord("MISSING_FIELD", "identifiers")


class ValidateCanonical(beam.DoFn):
    def __init__(self, validator, source: str):
        self.validator, self.source = validator, source
        self.rejected = Metrics.counter(source, "validation_rejected")

    def process(self, event: dict):
        try:
            self.validator(event)
            yield event
        except RejectedRecord as e:
            self.rejected.inc()
            yield beam.pvalue.TaggedOutput(
                DEAD_LETTER, make_dead_letter(self.source, "validate", e.code, e.detail, event, event.get("event_id")))
