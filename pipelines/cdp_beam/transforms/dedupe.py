"""Drop events whose event_id was already seen within the dedupe window."""

import time

import apache_beam as beam
from apache_beam.metrics import Metrics
from apache_beam.transforms.combiners import CountCombineFn
from apache_beam.transforms.timeutil import TimeDomain
from apache_beam.transforms.userstate import CombiningValueStateSpec, TimerSpec, on_timer

DEFAULT_WINDOW_SECONDS = 24 * 3600


class _DedupeFn(beam.DoFn):
    SEEN = CombiningValueStateSpec("seen", combine_fn=CountCombineFn())
    EXPIRY = TimerSpec("expiry", TimeDomain.REAL_TIME)

    def __init__(self, window_seconds: int):
        self.window_seconds = window_seconds
        self.duplicates = Metrics.counter("dedupe", "duplicates_dropped")

    def process(self, element, seen=beam.DoFn.StateParam(SEEN), expiry=beam.DoFn.TimerParam(EXPIRY)):
        _, event = element
        if seen.read():
            self.duplicates.inc()
            return
        seen.add(1)
        expiry.set(time.time() + self.window_seconds)
        yield event

    @on_timer(EXPIRY)
    def expire(self, seen=beam.DoFn.StateParam(SEEN)):
        seen.clear()


class DedupeByEventId(beam.PTransform):
    def __init__(self, window_seconds: int = DEFAULT_WINDOW_SECONDS):
        super().__init__()
        self.window_seconds = window_seconds

    def expand(self, events):
        return (
            events
            | "KeyByEventId" >> beam.Map(lambda e: (e["event_id"], e))
            | "DropSeen" >> beam.ParDo(_DedupeFn(self.window_seconds))
        )
