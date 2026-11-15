"""Mock contact-centre vendor.

Publishes contact records in the vendor's own format (modelled on Amazon Connect
CTRs, see contracts/vendor/connect/ctr.sample.json) to the vendor stream, the
way a real platform would. Deliberately injects the faults a real feed has.

Runs as Cloud Run job `cdp-care-vendor`:
  python -m cdp_sources.care.mock_vendor --count 50                                 # one burst of 50
  python -m cdp_sources.care.mock_vendor --count 0 --rate 100                       # 100/s until stopped
  python -m cdp_sources.care.mock_vendor --rate 100 --duration 10m --no-bad-records  # 10 min, clean only

Every contact carries Attributes.sequence_id (1, 2, 3, ... from --start-seq); a resend repeats it.
"""

import argparse
import copy
import json
import random
import signal
import threading
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
    def __init__(self, phones: list[str], seed: int | None, dup_pct: float, unknown_pct: float, invalid_pct: float,
                 start_seq: int = 1):
        self.rng = random.Random(seed)
        self.phones = phones
        self.dup_pct, self.unknown_pct, self.invalid_pct = dup_pct, unknown_pct, invalid_pct
        self.last_record = None
        self.next_seq = start_seq

    def contact_record(self, ended_at: datetime) -> dict:
        rng = self.rng
        intent = rng.choices(list(INTENTS), weights=[v[0] for v in INTENTS.values()])[0]
        _, queue, summaries = INTENTS[intent]
        channel = rng.choices(["VOICE", "CHAT"], weights=[60, 40])[0]
        duration = rng.randint(120, 1500) if channel == "VOICE" else rng.randint(240, 2400)
        phone = UNKNOWN_PHONE if rng.random() < self.unknown_pct else rng.choice(self.phones)
        sequence_id = self.next_seq
        self.next_seq += 1
        return {
            "ContactId": str(uuid.UUID(int=rng.getrandbits(128), version=4)),
            "Channel": channel,
            "InitiationTimestamp": iso(ended_at - timedelta(seconds=duration)),
            "DisconnectTimestamp": iso(ended_at),
            "CustomerEndpoint": {"Address": phone, "Type": "TELEPHONE_NUMBER"},
            "Agent": {"Username": f"agent{rng.randint(2201, 2260)}"},
            "Queue": {"Name": queue},
            # Contact attributes are strings in the vendor format. One number per contact: a resend is a
            # copy of the record, so it repeats the number, and the pipeline's dedupe drops it.
            "Attributes": {"intent": intent, "summary": rng.choice(summaries), "sequence_id": str(sequence_id)},
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


class PubSubSink:
    def __init__(self, project: str):
        from google.cloud import pubsub_v1
        self.publisher = pubsub_v1.PublisherClient()
        self.topic = self.publisher.topic_path(project, CARE_VENDOR_TOPIC)
        self.pending = []
        self.sent = 0

    def send(self, record: dict) -> None:
        self.pending.append(self.publisher.publish(
            self.topic,
            json.dumps(record).encode("utf-8"),
            source="care", vendor="connect", record_type="CTR",
            sequence_id=record["Attributes"]["sequence_id"],
        ))
        self.sent += 1
        if len(self.pending) >= 1000:
            self._reap()

    def _reap(self) -> None:
        """Drop finished publishes so memory stays flat on an endless run.
        result() re-raises a failed publish, so a broken topic or permission stops the job early."""
        still_pending = []
        for f in self.pending:
            if f.done():
                f.result()
            else:
                still_pending.append(f)
        self.pending = still_pending

    def close(self) -> None:
        for f in self.pending:
            f.result(timeout=30)
        print(f"Published {self.sent} records to {CARE_VENDOR_TOPIC}")


def parse_duration(value: str) -> float:
    """'90' or '90s' -> 90, '10m' -> 600, '2h' -> 7200 (seconds)."""
    units = {"s": 1, "m": 60, "h": 3600}
    try:
        if value and value[-1] in units:
            return float(value[:-1]) * units[value[-1]]
        return float(value)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{value!r} is not a duration like 90s, 10m or 2h")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=None,
                        help="Stop after N contacts (resends are extra); 0 = no limit. "
                             "Default 50, or no limit when --duration is given")
    parser.add_argument("--duration", type=parse_duration, default=0,
                        help="Stop after this long, e.g. 90s, 10m, 2h; 0 = no limit. With --count, whichever comes first")
    parser.add_argument("--rate", type=float, default=0, help="Contacts per second; 0 = as fast as possible")
    parser.add_argument("--start-seq", type=int, default=1,
                        help="First sequence_id; continue an earlier run's numbering with its last number + 1")
    parser.add_argument("--bad-records", action=argparse.BooleanOptionalAction, default=True,
                        help="Inject the faults a real feed has (resends, unknown callers, missing fields); "
                             "--no-bad-records sends only clean, unique records")
    parser.add_argument("--seed", type=int, default=None,
                        help="Fix for reproducible output; the same seed resends the same ContactIds")
    parser.add_argument("--pool", type=int, default=0,
                        help="Only use the first N customers, so they get repeat contacts (0 = everyone)")
    parser.add_argument("--phone", help="Send every contact from this caller (used by the deploy smoke test)")
    parser.add_argument("--dup-pct", type=float, default=0.04, help="Share of contacts resent (with --bad-records)")
    parser.add_argument("--unknown-pct", type=float, default=0.02, help="Share from an unknown caller (with --bad-records)")
    parser.add_argument("--invalid-pct", type=float, default=0.02, help="Share missing DisconnectTimestamp (with --bad-records)")
    args = parser.parse_args()
    if args.count is None:
        args.count = 0 if args.duration else 50
    if not args.rate and (args.count == 0 or args.duration):
        parser.error("--rate 0 (as fast as possible) only works with a fixed --count; "
                     "a --duration or --count 0 needs a --rate, or it floods the topic")
    if not args.bad_records:
        args.dup_pct = args.unknown_pct = args.invalid_pct = 0.0

    settings = Settings.from_env()
    if args.phone:
        phones = [args.phone]
    else:
        phones = pq.read_table(settings.world_uri, columns=["phone"]).column("phone").to_pylist()
        if args.pool:
            phones = phones[:args.pool]
    vendor = MockVendor(phones, args.seed, args.dup_pct, args.unknown_pct, args.invalid_pct, args.start_seq)
    sink = PubSubSink(settings.project)
    limits = [f"{args.count} contacts" if args.count else "", f"{args.duration:g}s" if args.duration else ""]
    print(f"Sending at {args.rate or 'max'} contacts/s, bad records {'on' if args.bad_records else 'off'}, "
          f"from sequence_id {args.start_seq}, until {' or '.join(l for l in limits if l) or 'stopped'}")

    # Cancelling a Cloud Run execution sends SIGTERM; finish the current contact and flush instead of dying.
    stopping = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopping.set())

    # Pace against a fixed schedule (start + n/rate), not "sleep after each send", so the time spent
    # building and publishing a record doesn't push the real rate below --rate.
    interval = 1 / args.rate if args.rate else 0
    started = next_at = last_report = time.monotonic()
    deadline = started + args.duration if args.duration else None
    contacts = 0
    try:
        while (not stopping.is_set()
               and (args.count == 0 or contacts < args.count)
               and (deadline is None or time.monotonic() < deadline)):
            for record in vendor.next_records(datetime.now(timezone.utc)):
                sink.send(record)
            contacts += 1
            now = time.monotonic()
            if now - last_report >= 30:
                print(f"{contacts} contacts, {sink.sent} records, {sink.sent / (now - started):.1f} records/s")
                last_report = now
            if interval:
                next_at += interval
                stopping.wait(max(0.0, next_at - time.monotonic()))
    finally:
        sink.close()
    print(f"{contacts} contacts, {sink.sent} records sent (including vendor resends) "
          f"in {time.monotonic() - started:.0f}s; sequence_id {args.start_seq}..{vendor.next_seq - 1}")


if __name__ == "__main__":
    main()
