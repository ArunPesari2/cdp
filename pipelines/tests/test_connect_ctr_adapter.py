import copy
import json

import pytest

from cdp_common.config import REPO_ROOT

from cdp_beam.adapters.connect_ctr import to_canonical
from cdp_beam.dead_letter import RejectedRecord
from cdp_beam.transforms.parse_validate import validate_contact_ended

SAMPLE = json.loads((REPO_ROOT / "contracts" / "vendor" / "connect" / "ctr.sample.json").read_text())


def test_maps_vendor_record_to_canonical_event():
    event = to_canonical(SAMPLE)

    assert event["event_id"] == SAMPLE["ContactId"]
    assert event["event_type"] == "contact_ended"
    assert event["event_ts"] == "2026-10-18T09:47:29.000Z"
    assert event["identifiers"] == {"phone": "+12065551488"}
    assert event["payload"] == {
        "channel": "call",
        "intent": "billing_question",
        "agent_id": "A-2208",
        "duration_sec": 343,
        "queue": "Billing",
        "summary": "Customer asked about higher bill. Explained one-time activation fee.",
    }
    validate_contact_ended(event)


def test_missing_disconnect_timestamp_is_rejected():
    record = copy.deepcopy(SAMPLE)
    del record["DisconnectTimestamp"]
    with pytest.raises(RejectedRecord) as e:
        to_canonical(record)
    assert e.value.code == "MISSING_FIELD"


@pytest.mark.parametrize("field, value", [
    ("Agent", "agent2208"),             # object expected, string received
    ("Agent", {"Username": 2208}),      # string expected, number received
    ("Channel", ["VOICE"]),             # string expected, list received
    ("Queue", "Billing"),               # optional object, wrong shape
])
def test_wrong_type_is_rejected(field, value):
    record = copy.deepcopy(SAMPLE)
    record[field] = value
    with pytest.raises(RejectedRecord) as e:
        to_canonical(record)
    assert e.value.code == "INVALID_TYPE"


def test_non_object_message_is_rejected():
    with pytest.raises(RejectedRecord) as e:
        to_canonical([1, 2, 3])
    assert e.value.code == "INVALID_TYPE"


def test_missing_queue_is_allowed():
    record = copy.deepcopy(SAMPLE)
    del record["Queue"]
    assert to_canonical(record)["payload"]["queue"] is None


def test_offset_is_converted_to_utc_with_milliseconds():
    record = copy.deepcopy(SAMPLE)
    record["InitiationTimestamp"] = "2026-10-18T15:11:46.1+05:30"
    record["DisconnectTimestamp"] = "2026-10-18T15:17:29+05:30"
    event = to_canonical(record)
    assert event["event_ts"] == "2026-10-18T09:47:29.000Z"
    assert event["payload"]["duration_sec"] == 343  # 342.9 s rounded, not truncated


@pytest.mark.parametrize("initiation, disconnect", [
    ("2026-10-18T09:41:46", "2026-10-18T09:47:29Z"),    # one side has no zone
    ("2026-10-18T09:41:46", "2026-10-18T09:47:29"),     # neither side has a zone
    ("2026-10-18T09:47:29Z", "2026-10-18T09:41:46Z"),   # ends before it starts
    ("yesterday", "2026-10-18T09:47:29Z"),              # not a timestamp
])
def test_bad_timestamps_are_rejected(initiation, disconnect):
    record = copy.deepcopy(SAMPLE)
    record["InitiationTimestamp"], record["DisconnectTimestamp"] = initiation, disconnect
    with pytest.raises(RejectedRecord) as e:
        to_canonical(record)
    assert e.value.code == "INVALID_TIMESTAMP"


def test_unknown_channel_is_rejected():
    record = copy.deepcopy(SAMPLE)
    record["Channel"] = "EMAIL"
    with pytest.raises(RejectedRecord) as e:
        to_canonical(record)
    assert e.value.code == "UNSUPPORTED_CHANNEL"


def test_unknown_intent_fails_validation():
    record = copy.deepcopy(SAMPLE)
    record["Attributes"]["intent"] = "pizza_order"
    with pytest.raises(RejectedRecord) as e:
        validate_contact_ended(to_canonical(record))
    assert e.value.code == "INVALID_VALUE"
