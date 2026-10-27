"""Mock contact-centre vendor.

Publishes contact records in the vendor's own format (modelled on Amazon Connect
CTRs, see contracts/vendor/connect/ctr.sample.json) to the vendor stream, the
way a real platform would. Deliberately injects the faults a real feed has.

Runs as Cloud Run job `cdp-care-vendor`:
  python -m cdp_sources.care.mock_vendor --count 50                  # publish to the vendor topic
  python -m cdp_sources.care.mock_vendor --count 5 --sink stdout     # print records (job logs)
"""

import argparse
import copy
import json
import random
import time
import uuid
from datetime import datetime, timedelta, timezone

import pyarrow.parquet as pq

from cdp_common.config import CARE_VENDOR_TOPIC, Settings

INTENTS = {
    # intent: (weight, queue, summaries)
    "network_issue": (30, "Technical Support", [
        "Customer reports dropped calls at home for 3 days. Advised network reset; opened ticket.",
        "Slow data in downtown area. Confirmed known tower maintenance; ETA 24 hours.",
        "No service after travel. Re-provisioned SIM; service restored.",
    ]),
    "billing_question": (25, "Billing", [
        "Customer asked about higher bill. Explained one-time activation fee.",
        "Disputed roaming charge. Applied courtesy credit of $15.",
        "Requested paperless billing. Enabled e-bill.",
    ]),
    "upgrade_inquiry": (15, "Sales", [
        "Asked about iPhone upgrade eligibility. Eligible now; sent offer by SMS.",
        "Interested in trade-in value for current device. Quoted $220.",
    ]),
    "plan_change": (10, "Sales", [
        "Moved from 2-line to 3-line family plan. Effective next cycle.",
        "Downgraded to lower data plan to reduce cost.",
    ]),
    "device_support": (15, "Technical Support", [
        "Phone not charging. Walked through troubleshooting; recommended store visit.",
        "Voicemail not working. Reset voicemail password.",
    ]),
    "cancel_request": (5, "Retention", [
        "Customer wants to cancel due to coverage. Offered retention discount; customer will think.",
        "Moving abroad; requested cancellation. Scheduled for end of cycle.",
    ]),
}
UNKNOWN_PHONE = "+19995550000"


def iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


class MockVendor:
    def __init__(self, phones: list[str], seed: int | None, dup_pct: float, unknown_pct: float, invalid_pct: float):
        self.rng = random.Random(seed)
        self.phones = phones
        self.dup_pct, self.unknown_pct, self.invalid_pct = dup_pct, unknown_pct, invalid_pct
        self.last_record = None

    def contact_record(self, ended_at: datetime) -> dict:
        rng = self.rng
        intent = rng.choices(list(INTENTS), weights=[v[0] for v in INTENTS.values()])[0]
        _, queue, summaries = INTENTS[intent]
        channel = rng.choices(["VOICE", "CHAT"], weights=[60, 40])[0]
        duration = rng.randint(120, 1500) if channel == "VOICE" else rng.randint(240, 2400)
        phone = UNKNOWN_PHONE if rng.random() < self.unknown_pct else rng.choice(self.phones)
        return {
            "ContactId": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            "Channel": channel,
            "InitiationTimestamp": iso(ended_at - timedelta(seconds=duration)),
            "DisconnectTimestamp": iso(ended_at),
            "CustomerEndpoint": {"Address": phone, "Type": "TELEPHONE_NUMBER"},
            "Agent": {"Username": f"agent{rng.randint(2201, 2260)}"},
            "Queue": {"Name": queue},
            "Attributes": {"intent": intent, "summary": rng.choice(summaries)},
        }

    def next_records(self, ended_at: datetime) -> list[dict]:
        """One new contact, plus a resend of the previous one now and then (vendor retry)."""
        record = self.contact_record(ended_at)
        if self.rng.random() < self.invalid_pct:
            del record["DisconnectTimestamp"]
        records = [record]
        if self.last_record is not None and self.rng.random() < self.dup_pct:
            records.append(copy.deepcopy(self.last_record))
        self.last_record = record
        return records


class StdoutSink:
    def send(self, record: dict) -> None:
        print(json.dumps(record))

    def close(self) -> None:
        pass


class PubSubSink:
    def __init__(self, project: str):
        from google.cloud import pubsub_v1
        self.publisher = pubsub_v1.PublisherClient()
        self.topic = self.publisher.topic_path(project, CARE_VENDOR_TOPIC)
        self.futures = []

    def send(self, record: dict) -> None:
        self.futures.append(self.publisher.publish(
            self.topic,
            json.dumps(record).encode("utf-8"),
            source="care", vendor="connect", record_type="CTR",
        ))

    def close(self) -> None:
        for f in self.futures:
            f.result(timeout=30)
        print(f"Published {len(self.futures)} records to {CARE_VENDOR_TOPIC}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=50, help="Number of contacts (resends are extra)")
    parser.add_argument("--rate", type=float, default=0, help="Contacts per second; 0 = as fast as possible")
    parser.add_argument("--sink", choices=["pubsub", "stdout"], default="pubsub")
    parser.add_argument("--seed", type=int, default=None,
                        help="Fix for reproducible output; the same seed resends the same ContactIds")
    parser.add_argument("--pool", type=int, default=0,
                        help="Only use the first N customers, so they get repeat contacts (0 = everyone)")
    parser.add_argument("--phone", help="Send every contact from this caller (used by the deploy smoke test)")
    parser.add_argument("--dup-pct", type=float, default=0.04)
    parser.add_argument("--unknown-pct", type=float, default=0.02)
    parser.add_argument("--invalid-pct", type=float, default=0.02)
    args = parser.parse_args()

    settings = Settings.from_env()
    if args.phone:
        phones = [args.phone]
    else:
        phones = pq.read_table(settings.world_uri, columns=["phone"]).column("phone").to_pylist()
        if args.pool:
            phones = phones[:args.pool]
    vendor = MockVendor(phones, args.seed, args.dup_pct, args.unknown_pct, args.invalid_pct)
    sink = PubSubSink(settings.project) if args.sink == "pubsub" else StdoutSink()

    sent = 0
    try:
        for _ in range(args.count):
            for record in vendor.next_records(datetime.now(timezone.utc)):
                sink.send(record)
                sent += 1
            if args.rate:
                time.sleep(1 / args.rate)
    finally:
        sink.close()
    print(f"{args.count} contacts, {sent} records sent (including vendor resends)")


if __name__ == "__main__":
    main()
