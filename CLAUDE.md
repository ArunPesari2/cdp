# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A reference Customer 360 / CDP on Google Cloud with synthetic telco data. Sources stream
interactions in, Dataflow resolves them to one customer, Spanner holds current state, BigQuery
holds history, and a GraphQL API (later an MCP server) serves the profile. Only slice 1 (care) is
built; web/app, network, store, billing, CRM CDC, identity resolution and MCP are planned.
See [README.md](README.md), [docs/architecture/CDP-High-Level-Architecture.md](docs/architecture/CDP-High-Level-Architecture.md)
and [docs/contracts/care-data-contract.md](docs/contracts/care-data-contract.md).

Language split: Java 21 + Spring Boot 3.5 for APIs; Python 3.11 for pipelines, mock sources and (future) MCP.

## Commands

Dev shell is Windows PowerShell; the cicd scripts are bash/sh run inside Cloud Build containers.

```powershell
# One venv for all Python packages (editable installs of libs/cdp_common, sources, pipelines)
python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt

# Python tests (DirectRunner, no cloud access)
.venv\Scripts\python -m pytest pipelines/tests -q
.venv\Scripts\python -m pytest pipelines/tests/test_care_pipeline.py::test_good_duplicate_unknown_and_invalid_records -q

# Java tests (root pom.xml is the parent; modules: serving/customer-api)
mvn -q test
mvn -q -pl serving/customer-api test -Dtest=CustomerControllerTest
```

Deploy and teardown are Cloud Build pipelines started by hand from the repo root, always with an
explicit `--project` and `--service-account` (cdp-deployer); `_TAG` is required. Exact commands are
in the README "Day to day" section. `deploy.yaml` runs the Python and Java tests first, so a failing
test blocks the deploy. Teardown (`cicd/teardown.yaml`) first cancels or drains the Dataflow job
(`cicd/stop_care_job.sh`, mode from `CARE_ON_STOP` in `care-pipeline.env`), then destroys the
`runtime` stack to stop hourly billing. No linter or formatter is configured.

## Architecture

**Code layout by role**
- `libs/cdp_common` — settings from env vars (`Settings.from_env`), canonical event constants, `REPO_ROOT`.
- `sources/cdp_sources` — mock source systems run as Cloud Run jobs (`python -m <module>`, see `sources/Dockerfile`): `world/` generates the synthetic customer world to GCS and loads Spanner; `care/mock_vendor.py` publishes vendor CTRs to Pub/Sub.
- `pipelines/cdp_beam` — reusable Beam library: `adapters/` (vendor format → canonical event), `transforms/` (parse/validate, dedupe, resolve identity, to rows), `io/` (Spanner/BigQuery sinks), `dead_letter.py`.
- `pipelines/cdp_pipelines/<slice>/main.py` — one Dataflow job per slice, composed from `cdp_beam`. `build()` is kept separate from `run()` so tests can run the graph on the DirectRunner with a fake identity lookup.
- `serving/customer-api` — Spring Boot GraphQL (`schema.graphqls`) reading Spanner through a `CustomerRepository` interface; tests use `@GraphQlTest` with a mocked repository.
- `contracts/` — the single source of truth for schemas: vendor samples, canonical Avro events, BigQuery table JSON, Spanner migrations. Terraform reads these directly (`data` stack loads `contracts/bigquery`, `runtime` stack applies `contracts/spanner/migrations/*.sql` in order), and tests read the vendor sample via `REPO_ROOT`.

**Care data flow**: Pub/Sub `vendor-care-ctr` → ParseAndAdapt → Validate → Dedupe by `event_id` → ResolveIdentity (Spanner `IdentityMap` lookup by phone) → upsert Spanner `Interaction` + append BigQuery `core.interactions`. Every stage emits failures on the `dead_letter` tagged output (via `RejectedRecord` with an error code), flattened into BigQuery `ops.dead_letter`. Adding a new source means a new adapter plus a new `cdp_pipelines/<slice>`, reusing the transforms.

**Conventions that matter**
- Spanner migrations are append-only: add `000N_*.sql`, never edit an applied one.
- `libs/cdp_common/cdp_common/events.py` mirrors `contracts/events/*.avsc`; change both together, and update the data contract doc.
- Spanner writes are upserts so at-least-once delivery and replays are safe; timestamps without an explicit offset are rejected, never guessed.

**Infra and delivery**
- Terraform stacks in `platform/terraform/stacks/`: `foundation` (APIs, Artifact Registry, service accounts/IAM, budget — applied manually by an admin), `data` (BigQuery, GCS — permanent), `runtime` (Spanner, Pub/Sub, Cloud Run — destroyed when idle). Per-env values in `platform/terraform/envs/<env>/` (`terraform.tfvars`, `care-pipeline.env`); only `dev` exists.
- `cicd/tf.sh <stack> <plan|apply|destroy|output>` wraps init/backend config; `output` writes `.deploy/<stack>-outputs.json`, which `deploy_care_job.sh` reads so resource names are never retyped.
- The Dataflow job is a release, not Terraform-managed: `cicd/deploy.yaml` builds a Flex Template per `_TAG` and `cicd/deploy_care_job.sh` starts it or `--update`s the running job. `pipelines/Dockerfile` assembles `cdp_common + cdp_beam + cdp_pipelines` into one tree packaged for workers by `pipelines/dataflow/setup.py` — a new Python package used by a pipeline must be added to both.
- All Docker builds use the repo root as context. `.gcloudignore` controls what Cloud Build uploads.
- The deploy ends with `cicd/smoke_test.sh`: seed, send one contact for a known customer, read it back through the authenticated Customer API (only `cdp-smoke` may invoke it).

## Working with this user

Walkthroughs/reviews: explain one file or block per reply, check understanding, and move on only when confirmed.
