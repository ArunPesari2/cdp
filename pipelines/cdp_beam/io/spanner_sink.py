"""Idempotent Spanner writes: insert_or_update in batches, keyed by the table's primary key."""

import apache_beam as beam
from apache_beam.metrics import Metrics


class WriteToSpanner(beam.DoFn):
    def __init__(self, project: str, instance: str, database: str, table: str,
                 columns: tuple, commit_ts_columns: tuple = (), batch_size: int = 500):
        self.project, self.instance, self.database = project, instance, database
        self.table, self.columns, self.commit_ts_columns = table, columns, commit_ts_columns
        self.batch_size = batch_size
        self.written = Metrics.counter("spanner", f"{table}_rows_written")

    def setup(self):
        from google.cloud import spanner
        self._spanner = spanner
        self._db = spanner.Client(project=self.project).instance(self.instance).database(self.database)

    def start_bundle(self):
        self._buffer = []

    def process(self, row: dict):
        commit_ts = (self._spanner.COMMIT_TIMESTAMP,) * len(self.commit_ts_columns)
        self._buffer.append(tuple(row.get(c) for c in self.columns) + commit_ts)
        if len(self._buffer) >= self.batch_size:
            self._flush()

    def finish_bundle(self):
        self._flush()

    def _flush(self):
        if not self._buffer:
            return
        with self._db.batch() as batch:
            batch.insert_or_update(self.table, columns=self.columns + self.commit_ts_columns, values=self._buffer)
        self.written.inc(len(self._buffer))
        self._buffer = []
