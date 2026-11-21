"""The fixed demo stories pass through the care pipeline intact, and stay separate from random data."""

import json
from datetime import date, datetime, timezone

import apache_beam as beam
from apache_beam.testing.test_pipeline import TestPipeline
from apache_beam.testing.util import assert_that, equal_to

from cdp_common.events import CARE_INTENTS

from cdp_pipelines.care.main import build
from cdp_sources.care.mock_vendor import MockVendor
from cdp_sources.demo_stories import DEMO_CUSTOMERS, DEMO_EMAIL_DOMAIN, DEMO_PHONES
from cdp_sources.world.generator import generate_people

TODAY = date(2026, 11, 21)


class DemoLookup:
    """Knows only the demo customers, keyed by phone (stands in for SpannerIdentityLookup)."""

    def open(self):
        pass

    def find(self, id_type, id_value):
        return f"cust-{id_value}" if id_type == "phone" and id_value in DEMO_PHONES else None


def test_every_story_contact_is_saved_in_order_for_its_customer():
    records = MockVendor([], seed=1, dup_pct=0, unknown_pct=0, invalid_pct=0).story_records(DEMO_CUSTOMERS, TODAY)
    expected = sorted(
        (f"cust-{c['person']['phone']}", s["intent"], s["summary"])
        for c in DEMO_CUSTOMERS for s in c["contacts"])

    with TestPipeline() as p:
        events, dead_letters = build(p | beam.Create([json.dumps(r).encode() for r in records]), DemoLookup())

        assert_that(
            events | beam.Map(lambda e: (e["customer_id"], e["payload"]["intent"], e["payload"]["summary"])),
            equal_to(expected), label="saved")
        assert_that(dead_letters, equal_to([]), label="no_dead_letters")


def test_story_dates_are_in_the_past_and_ids_repeat_on_the_same_day():
    vendor = MockVendor([], seed=1, dup_pct=0, unknown_pct=0, invalid_pct=0)
    first = vendor.story_records(DEMO_CUSTOMERS, TODAY)
    again = vendor.story_records(DEMO_CUSTOMERS, TODAY)

    ended = [r["DisconnectTimestamp"] for r in first]
    assert ended == sorted(ended)
    assert all(datetime.fromisoformat(t) < datetime(2026, 11, 21, tzinfo=timezone.utc) for t in ended)
    assert [r["ContactId"] for r in first] == [r["ContactId"] for r in again]
    assert all(s["intent"] in CARE_INTENTS for c in DEMO_CUSTOMERS for s in c["contacts"])


def test_world_has_each_demo_customer_once_with_unique_phones():
    people = generate_people(500, seed=42)
    demo = [p for p in people if p["email"].endswith("@" + DEMO_EMAIL_DOMAIN)]

    assert {p["phone"] for p in demo} == DEMO_PHONES
    assert len(demo) == len(DEMO_CUSTOMERS)
    assert len({p["phone"] for p in people}) == len(people)
