"""Runs the care pipeline logic on the DirectRunner with an in-memory identity lookup."""

import copy
import json

import apache_beam as beam
from apache_beam.testing.test_pipeline import TestPipeline
from apache_beam.testing.util import assert_that, equal_to

from cdp_common.config import REPO_ROOT

from cdp_pipelines.care.main import build

SAMPLE = json.loads((REPO_ROOT / "contracts" / "vendor" / "connect" / "ctr.sample.json").read_text())
KNOWN_PHONE, CUSTOMER_ID = "+12065551488", "cust-1"


class FakeLookup:
    def open(self):
        pass

    def find(self, id_type, id_value):
        return CUSTOMER_ID if (id_type, id_value) == ("phone", KNOWN_PHONE) else None


def record(contact_id, **changes):
    r = copy.deepcopy(SAMPLE)
    r["ContactId"] = contact_id
    for key, value in changes.items():
        if value is None:
            del r[key]
        else:
            r[key] = value
    return json.dumps(r).encode()


def test_good_duplicate_unknown_and_invalid_records():
    raw = [
        record("c-1"),
        record("c-2"),
        record("c-2"),                                                    # vendor resend
        record("c-3", CustomerEndpoint={"Address": "+19995550000"}),      # unknown phone
        record("c-4", DisconnectTimestamp=None),                          # missing field
        record("c-5", Agent="agent2208"),                                 # wrong shape
        b"{not json",                                                     # corrupt message
        b'{"ContactId": "c-6\xff"}',                                     # not UTF-8
    ]

    with TestPipeline() as p:
        events, dead_letters = build(p | beam.Create(raw), FakeLookup())

        assert_that(
            events | "Ids" >> beam.Map(lambda e: (e["event_id"], e["customer_id"])),
            equal_to([("c-1", CUSTOMER_ID), ("c-2", CUSTOMER_ID)]),
            label="saved")
        assert_that(
            dead_letters | "Codes" >> beam.Map(lambda d: (d["stage"], d["error_code"])),
            equal_to([("resolve_identity", "UNKNOWN_IDENTITY"),
                      ("adapter", "MISSING_FIELD"),
                      ("adapter", "INVALID_TYPE"),
                      ("adapter", "INVALID_JSON"),
                      ("adapter", "INVALID_ENCODING")]),
            label="dead_letters")
