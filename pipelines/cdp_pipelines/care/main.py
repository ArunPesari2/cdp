"""Care pipeline: vendor contact records -> Spanner Interaction + BigQuery core.interactions.

Runs on Dataflow as a Flex Template (pipelines/Dockerfile); launched by the deploy pipeline
(cicd/deploy_care_job.sh), which passes the subscription and Spanner names as template parameters.
"""

import argparse
import logging

import apache_beam as beam
from apache_beam.options.pipeline_options import GoogleCloudOptions, PipelineOptions, StandardOptions

from cdp_beam.adapters import connect_ctr
from cdp_beam.dead_letter import DEAD_LETTER
from cdp_beam.io.bigquery_sink import WriteBigQuery
from cdp_beam.io.spanner_sink import WriteToSpanner
from cdp_beam.transforms.dedupe import DedupeByEventId
from cdp_beam.transforms.parse_validate import ParseAndAdapt, ValidateCanonical, validate_contact_ended
from cdp_beam.transforms.resolve_identity import ResolveIdentity, SpannerIdentityLookup
from cdp_beam.transforms.to_rows import (
    INTERACTION_SPANNER_COLUMNS,
    interaction_bigquery_row,
    interaction_spanner_row,
)

SOURCE = "care"


def build(raw, lookup):
    """raw vendor messages (bytes) -> (resolved canonical events, dead-letter records)."""
    adapted = raw | "ParseAndAdapt" >> beam.ParDo(
        ParseAndAdapt(connect_ctr.to_canonical, SOURCE)).with_outputs(DEAD_LETTER, main="ok")
    validated = adapted.ok | "Validate" >> beam.ParDo(
        ValidateCanonical(validate_contact_ended, SOURCE)).with_outputs(DEAD_LETTER, main="ok")
    unique = validated.ok | "Dedupe" >> DedupeByEventId()
    resolved = unique | "ResolveIdentity" >> beam.ParDo(
        ResolveIdentity(lookup, SOURCE)).with_outputs(DEAD_LETTER, main="ok")

    dead_letters = (
        (adapted[DEAD_LETTER], validated[DEAD_LETTER], resolved[DEAD_LETTER])
        | "CollectDeadLetters" >> beam.Flatten()
    )
    return resolved.ok, dead_letters


def run(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--subscription", required=True)
    parser.add_argument("--spanner_instance", required=True)
    parser.add_argument("--spanner_database", required=True)
    args, beam_args = parser.parse_known_args(argv)

    options = PipelineOptions(beam_args)
    options.view_as(StandardOptions).streaming = True
    project = options.view_as(GoogleCloudOptions).project

    with beam.Pipeline(options=options) as p:
        raw = p | "ReadVendorStream" >> beam.io.ReadFromPubSub(
            subscription=f"projects/{project}/subscriptions/{args.subscription}")

        lookup = SpannerIdentityLookup(project, args.spanner_instance, args.spanner_database)
        events, dead_letters = build(raw, lookup)

        (events
         | "ToSpannerRow" >> beam.Map(interaction_spanner_row)
         | "WriteSpanner" >> beam.ParDo(WriteToSpanner(
             project, args.spanner_instance, args.spanner_database,
             "Interaction", INTERACTION_SPANNER_COLUMNS, commit_ts_columns=("processed_at",))))
        (events
         | "ToBigQueryRow" >> beam.Map(interaction_bigquery_row)
         | "WriteInteractions" >> WriteBigQuery(project, "core.interactions"))
        dead_letters | "WriteDeadLetters" >> WriteBigQuery(project, "ops.dead_letter")


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    run()
