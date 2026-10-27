# Customer Data Platform (CDP) on Google Cloud

A reference Customer 360 platform: source systems stream customer interactions in, the
CDP resolves them to one customer profile, and channels and AI agents read that profile
in milliseconds. Built with synthetic telco data, deployed on Google Cloud with Terraform
and Cloud Build.

- Architecture: [docs/architecture/CDP-High-Level-Architecture.md](docs/architecture/CDP-High-Level-Architecture.md)
- Care data contract: [docs/contracts/care-data-contract.md](docs/contracts/care-data-contract.md)

## Status

| Slice | Flow | Status |
| --- | --- | --- |
| 1. Care | Vendor stream (Pub/Sub) → Dataflow → Spanner + BigQuery → GraphQL on Cloud Run | Deployed with Cloud Build |
| 2. Web/App | Ingestion API (Spring Boot) → Pub/Sub → Dataflow | Planned |
| 3+ | Network, Store, Billing, CRM CDC, identity resolution, MCP | Planned |

## What runs where (care slice)

| Component | GCP service | Code |
| --- | --- | --- |
| Mock contact-centre vendor | Cloud Run job `cdp-care-vendor` | `sources/cdp_sources/care/mock_vendor.py` |
| Customer world + Spanner load | Cloud Run job `cdp-seed`, Cloud Storage | `sources/cdp_sources/world/` |
| Vendor stream | Pub/Sub `vendor-care-ctr` | — |
| Care pipeline | Dataflow `care-pipeline` (Flex Template, streaming) | `pipelines/` |
| Current state | Spanner `cdp-instance/cdp` | `contracts/spanner/migrations/` |
| History, dead letters | BigQuery `core.interactions`, `ops.dead_letter` | `contracts/bigquery/` |
| Customer API | Cloud Run service `customer-api` (authenticated) | `serving/customer-api/` |

## Infrastructure and delivery

Infrastructure is declared in Terraform; every change ships through Cloud Build.
Pipelines are started by hand with `gcloud builds submit` (no Git triggers yet), always with an
explicit `--project` and service account.

| Terraform stack | Contents | Applied by | Lifetime |
| --- | --- | --- | --- |
| `foundation` | APIs, Artifact Registry, service accounts and roles, budget | Platform admin (manual) | Permanent |
| `data` | BigQuery datasets/tables, Cloud Storage buckets | `cdp-deployer` (pipeline) | Permanent |
| `runtime` | Spanner, Pub/Sub, Cloud Run service and jobs | `cdp-deployer` (pipeline) | Up while in use |

The Dataflow care pipeline is treated as a release, not infrastructure: the deploy pipeline
starts it from the release's Flex Template, or updates the running job in place
([cicd/deploy_care_job.sh](cicd/deploy_care_job.sh)); teardown cancels or drains it
([cicd/stop_care_job.sh](cicd/stop_care_job.sh)).

| Pipeline | Runs as | Steps |
| --- | --- | --- |
| [cicd/deploy.yaml](cicd/deploy.yaml) | `cdp-deployer` | Tests → build + push images (tag `_TAG`) → Flex Template → apply `data` → apply `runtime` → start/update the care pipeline → end-to-end smoke test |
| [cicd/teardown.yaml](cicd/teardown.yaml) | `cdp-deployer` | Stop the care pipeline → destroy `runtime` (stops hourly billing) |

The smoke test seeds customers, has the mock vendor send one contact for a known customer,
and passes only when that contact is readable through the Customer API.

Environments: one GCP project per environment, configured in `platform/terraform/envs/<env>/`
(`terraform.tfvars` for the stacks, `care-pipeline.env` for the Dataflow job). Only `dev` exists;
`prod` would add `envs/prod/` with its own values and `CARE_ON_STOP=drain`.

## First-time run order

| Order | What | How often |
| --- | --- | --- |
| 0 | Log in with `gcloud`; check `platform/terraform/envs/dev/terraform.tfvars` | Once per machine |
| 1 | Create the Terraform state bucket | Once per project |
| 2 | Apply `platform/terraform/stacks/foundation` | Once per project, and when the foundation changes |
| 3 | Run `cicd/deploy.yaml` (see [Day to day](#day-to-day)) | Every deploy |

The foundation must exist before `deploy.yaml` can run: `deploy.yaml` runs as the `cdp-deployer`
service account and pushes to the `cdp` Artifact Registry repository, and the foundation creates
both. A pipeline cannot create the account it runs as, and should not grant itself permissions,
so the foundation is applied by an admin with their own login.

## One-time setup (platform admin)

```powershell
# 0. Log in (gcloud CLI only)
gcloud auth login

# 1. Terraform state bucket
gcloud storage buckets create gs://learning-dev-2026-07-tfstate --location=us-central1 --uniform-bucket-level-access
gcloud storage buckets update gs://learning-dev-2026-07-tfstate --versioning

# 2. Foundation stack (Terraform calls GCP as you, using a token from your gcloud login)
cd platform/terraform/stacks/foundation
$env:GOOGLE_OAUTH_ACCESS_TOKEN = gcloud auth print-access-token
terraform init -backend-config=bucket=learning-dev-2026-07-tfstate -backend-config=prefix=cdp/dev/foundation
terraform apply -var-file=../../envs/dev/terraform.tfvars
```

### How Terraform authenticates

Terraform does not use the `gcloud auth login` session. Its Google provider looks for
credentials in this order: the provider block's `access_token` (not set here), the
`GOOGLE_OAUTH_ACCESS_TOKEN` environment variable, then Application Default Credentials.

1. `gcloud auth print-access-token` prints a short-lived token for your gcloud account.
2. The token is stored in `GOOGLE_OAUTH_ACCESS_TOKEN` for the current PowerShell window only.
3. On every API call, the provider sends it as an HTTP header:
   `Authorization: Bearer <token>`.
4. GCP validates the token, sees which account it belongs to, and checks that account's IAM
   permissions in the project before acting.

The token expires after about an hour; if an apply fails with an authentication error, run the
`$env:GOOGLE_OAUTH_ACCESS_TOKEN = ...` line again. An alternative is
`gcloud auth application-default login`, which saves a credentials file that Terraform finds on
its own and refreshes automatically. Use one method or the other, not both.

To see the HTTP calls Terraform makes (tokens are hidden in the log):
`$env:TF_LOG = "DEBUG"; terraform plan -var-file=../../envs/dev/terraform.tfvars`

## Day to day

Run from the repository root. Cloud Build uploads the local folder as the build source.

```powershell
$PROJECT = "learning-dev-2026-07"
$REGION  = "us-central1"
$SA      = "projects/$PROJECT/serviceAccounts"

# Deploy: _TAG is the image version and is required
$TAG = "v" + (Get-Date -Format "yyyyMMdd-HHmmss")
gcloud builds submit --project=$PROJECT --region=$REGION --config=cicd/deploy.yaml `
  --service-account="$SA/cdp-deployer@$PROJECT.iam.gserviceaccount.com" --substitutions="_TAG=$TAG"

# Send test contacts from the mock vendor
gcloud run jobs execute cdp-care-vendor --project=$PROJECT --region=$REGION --wait `
  --args="cdp_sources.care.mock_vendor,--count=50"

# Read a customer through the API (only cdp-smoke may call it; impersonate it for a token)
$url   = gcloud run services describe customer-api --project=$PROJECT --region=$REGION --format="value(status.url)"
$token = gcloud auth print-identity-token --impersonate-service-account="cdp-smoke@$PROJECT.iam.gserviceaccount.com" `
  --audiences=$url --include-email
curl.exe -H "Authorization: Bearer $token" -H "Content-Type: application/json" `
  -d '{\"query\":\"{ customer(phone: \\\"+14258928935\\\") { firstName recentInteractions(limit: 5) { eventTs channel intent summary } } }\"}' `
  "$url/graphql"

# Stop hourly billing
gcloud builds submit --project=$PROJECT --region=$REGION --config=cicd/teardown.yaml `
  --service-account="$SA/cdp-deployer@$PROJECT.iam.gserviceaccount.com"
```

## Cost

Approximate, us-central1, smallest settings: Spanner 100 processing units and one Dataflow
worker dominate, roughly ₹25–35 per hour while the runtime stack is up, about ₹0 after
teardown. A ₹2,000/month budget alert (50/80/100%) is part of the foundation stack.

## Tests

Unit tests need no cloud access:

```powershell
python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest pipelines/tests -q
mvn -q test
```
