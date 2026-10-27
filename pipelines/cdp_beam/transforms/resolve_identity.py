"""Resolve raw identifiers (phone, ...) to a CDP customer_id via Spanner IdentityMap."""

import apache_beam as beam
from apache_beam.metrics import Metrics

from cdp_beam.dead_letter import DEAD_LETTER, make_dead_letter

# Identifier types tried in order.
LOOKUP_ORDER = ("phone", "email")
_CACHE_LIMIT = 100_000


class SpannerIdentityLookup:
    """Point reads on IdentityMap, with a small per-worker cache."""

    def __init__(self, project: str, instance: str, database: str):
        self.project, self.instance, self.database = project, instance, database
        self._db = None
        self._cache: dict = {}

    def open(self) -> None:
        from google.cloud import spanner
        self._db = spanner.Client(project=self.project).instance(self.instance).database(self.database)

    def find(self, id_type: str, id_value: str) -> str | None:
        key = (id_type, id_value)
        if key in self._cache:
            return self._cache[key]
        from google.cloud.spanner_v1.keyset import KeySet
        with self._db.snapshot() as snapshot:
            rows = list(snapshot.read("IdentityMap", ("customer_id",), KeySet(keys=[[id_type, id_value]])))
        customer_id = rows[0][0] if rows else None
        if customer_id is not None:  # don't cache misses: the customer may be created later
            if len(self._cache) >= _CACHE_LIMIT:
                self._cache.clear()
            self._cache[key] = customer_id
        return customer_id


class ResolveIdentity(beam.DoFn):
    def __init__(self, lookup, source: str):
        self.lookup, self.source = lookup, source
        self.unresolved = Metrics.counter(source, "unknown_identity")

    def setup(self):
        self.lookup.open()

    def process(self, event: dict):
        identifiers = event["identifiers"]
        for id_type in LOOKUP_ORDER:
            if identifiers.get(id_type):
                customer_id = self.lookup.find(id_type, identifiers[id_type])
                if customer_id:
                    yield {**event, "customer_id": customer_id}
                    return
        self.unresolved.inc()
        yield beam.pvalue.TaggedOutput(DEAD_LETTER, make_dead_letter(
            self.source, "resolve_identity", "UNKNOWN_IDENTITY", str(identifiers), event, event["event_id"]))
