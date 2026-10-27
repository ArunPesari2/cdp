"""Append rows to an existing BigQuery table (tables are created by Terraform from contracts/bigquery)."""

import apache_beam as beam


class WriteBigQuery(beam.PTransform):
    """table like 'core.interactions'."""

    def __init__(self, project: str, table: str):
        super().__init__()
        self.project, self.table = project, table

    def expand(self, rows):
        dataset, name = self.table.split(".")
        return rows | beam.io.WriteToBigQuery(
            table=f"{self.project}:{dataset}.{name}",
            create_disposition=beam.io.BigQueryDisposition.CREATE_NEVER,
            write_disposition=beam.io.BigQueryDisposition.WRITE_APPEND,
            method=beam.io.WriteToBigQuery.Method.STREAMING_INSERTS,
        )
