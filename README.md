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

**Step 0. Log in**

```powershell
gcloud auth login
```

Signs the gcloud CLI in as you. Terraform does not use this session directly (see
[How Terraform authenticates](#how-terraform-authenticates)).

**Step 1. Terraform state bucket**

```powershell
gcloud storage buckets create gs://learning-dev-2026-07-tfstate --location=us-central1 --uniform-bucket-level-access
gcloud storage buckets update gs://learning-dev-2026-07-tfstate --versioning
```

- `create`: bucket for every stack's Terraform state.
- `--uniform-bucket-level-access`: permissions from IAM only, no per-object ACLs.
- `--versioning`: keeps old state versions, so a bad apply or delete can be undone
  (`gcloud storage ls -a` lists them).

**Step 2. Foundation stack**

```powershell
cd platform/terraform/stacks/foundation
$env:GOOGLE_OAUTH_ACCESS_TOKEN = gcloud auth print-access-token
terraform init "-backend-config=bucket=learning-dev-2026-07-tfstate" "-backend-config=prefix=cdp/dev/foundation"
terraform plan "-var-file=../../envs/dev/terraform.tfvars" "-out=foundation.tfplan"
terraform apply "foundation.tfplan"
Remove-Item "foundation.tfplan"
```

- `GOOGLE_OAUTH_ACCESS_TOKEN`: a short-lived token from your gcloud login, so Terraform calls GCP
  as you.
- `terraform init`, in order:
  1. Reads the `terraform {}` block in `main.tf` and checks the Terraform version:
     - `required_version = ">= 1.5"` is compared with the binary you run (`terraform version`).
     - Older: stops with "Unsupported Terraform Core version" before touching backend or providers.
     - Only a minimum: any Terraform 1.5 or newer works.
  2. Fills the empty `backend "gcs" {}` with `bucket` and `prefix` from `-backend-config`
     (backend blocks cannot use variables).
  3. Connects to the bucket with your token and confirms access:
     - State file location (bucket + prefix + workspace `default`):
       `gs://learning-dev-2026-07-tfstate/cdp/dev/foundation/default.tfstate`.
     - Already exists: left as is.
     - Does not exist (first ever init): creates an empty `default.tfstate` in the bucket:
       1. Locks: creates `default.tflock` in the bucket with `"Operation": "init"`.
       2. Creates `default.tfstate` in the bucket with `"serial": 1` and `"resources": []`.
       3. Unlocks: deletes `default.tflock` from the bucket.
  4. Saves the backend settings in `.terraform/terraform.tfstate` (local metadata, not your state):
     - Why: each Terraform command is a separate run that remembers nothing. `plan`/`apply`/`destroy`
       do not take `-backend-config` and the `backend "gcs" {}` block is empty, so they read the
       bucket and prefix from this file to find the real state.
     - Holds only the location (bucket, prefix, a hash of them), no resources. The real state is
       `default.tfstate` in the bucket.
     - The hash lets a later `init` notice a different bucket or prefix and stop with "Backend
       configuration changed" (`-migrate-state` or `-reconfigure`), instead of silently using another state.
     - Safe to delete (`.terraform/` is in `.gitignore`); the next `init` recreates it.
  5. Installs the `hashicorp/google` provider, depending on `.terraform.lock.hcl` (which pins the
     provider version, not the Terraform version):
     - Lock file already exists (this repo, committed in git):
       1. Reads the exact version recorded in it.
       2. Downloads that version into `.terraform/providers/`.
       3. Verifies the download against the checksums in the lock file.
       4. Leaves the lock file unchanged.
     - Lock file does not exist (first ever init of a new stack):
       1. Picks the newest version matching `~> 6.0` in `main.tf`.
       2. Downloads that version into `.terraform/providers/`.
       3. Creates `.terraform.lock.hcl` with that version and its checksums (commit it to git).
  6. Creates no GCP resources. (`init -upgrade` re-picks the newest version and rewrites the lock
     file.)
- `terraform plan "-var-file=../../envs/dev/terraform.tfvars" "-out=foundation.tfplan"`, in order:
  1. Locks the state by creating `gs://learning-dev-2026-07-tfstate/cdp/dev/foundation/default.tflock`:
     - A small JSON file: lock ID, operation, who, when, Terraform version.
     - Created only if absent, so two runs can never both hold the lock.
     - Already there (another run, or a crashed one): fails with `Error acquiring the state lock`.
       Wait, or for a stale lock run `terraform force-unlock <LOCK_ID>`.
     - Works on the first plan too; only the bucket must exist.
  2. Reads the state from the bucket, `gs://learning-dev-2026-07-tfstate/cdp/dev/foundation/default.tfstate` (created by `init`):
     - Loads the resources Terraform already manages.
     - First plan: `"resources": []`, so Terraform manages nothing yet.
  3. Refreshes: asks GCP for the current settings of every resource in the state (nothing to ask
     on the first plan).
  4. Compares that with `main.tf` + `envs/dev/terraform.tfvars` and prints each change:
     `+` create, `~` update, `-/+` replace, `-` destroy (first plan: every resource is `+`).
     Terraform checks GCP only for resources in the state, plus `data` blocks:

     | Case | GCP checked? | Result |
     | --- | --- | --- |
     | In `main.tf` and in state | Yes | No change, `~` update, or `-/+` replace |
     | In `main.tf`, not in state | No | `+ create`; if it already exists in GCP, `apply` fails with "already exists" (fix: `terraform import`) |
     | Not in `main.tf`, in state | Yes | `- destroy` |
     | In neither (created by hand) | No | Invisible to Terraform; never changed |
     | `data` blocks (e.g. `data "google_project" "this"`) | Yes | Always read; never changed |
  5. Saves the exact changes to `foundation.tfplan` (git-ignored).
  6. Deletes `default.tflock`. Nothing changed in GCP, and the state file is not modified.
  7. Review the output; if anything is unexpected, stop here.
- `terraform apply "foundation.tfplan"`, in order:
  1. Reads `foundation.tfplan`:
     - Must be run with the same Terraform and provider versions that made the plan.
     - No `yes` prompt: the plan was already reviewed.
  2. Locks the state by creating `default.tflock` in the bucket (same rules as in `plan`).
  3. Checks the state has not changed since the plan was made:
     - `foundation.tfplan` is a zip holding a copy of the state taken at plan time:

       | File in the zip | Holds |
       | --- | --- |
       | `tfplan` | The planned changes and variable values |
       | `tfstate` | State after refresh, with its `lineage` and `serial` |
       | `tfstate-prev` | State as read from the bucket, before refresh |
       | `tfconfig/` | Copy of the `.tf` files at plan time |
       | `.terraform.lock.hcl` | Provider versions and checksums used |

     - In simple terms: `tfstate-prev` = recorded, `tfstate` = current (real GCP),
       `tfplan` = changes. Future state = `tfstate` + `tfplan`, written by `apply`.
     - Example: a bucket managed by Terraform is deleted by hand in the console, then `plan` runs:

       | File | The bucket |
       | --- | --- |
       | `tfstate-prev` | Listed: the bucket's state still records it |
       | `tfstate` | Not listed: refresh got "404 not found" from GCP |
       | `tfplan` | `+ create`: `main.tf` still wants it |

       The plan prints `has been deleted` (from `tfstate-prev` vs `tfstate`) and `will be created`
       (from `tfplan`). `apply` creates a new, empty bucket; the old files do not come back.

     - `lineage`: random ID set once when the state is created; identifies this state.
     - `serial`: counter, +1 on every state write.
     - Compares `lineage` and `serial` in the plan's `tfstate` with the state in the bucket:
       - Equal: nobody wrote the state since the plan; continue.
       - Different (another apply ran in between): fails with `Saved plan is stale`; re-run `plan`.
     - Does not detect changes made directly in GCP after the plan (the serial does not move), so
       keep the gap between `plan` and `apply` short.
     - The zip holds state and variable values, so it can contain secrets: git- and
       gcloud-ignored; delete it after apply. Inspect with `terraform show foundation.tfplan`.
  4. Makes the changes through the GCP APIs, in dependency order, up to 10 at a time:
     - Wave 1: the 14 APIs (`google_project_service`).
     - Wave 2: service accounts, Artifact Registry, budget (they `depends_on` the APIs).
     - Wave 3: IAM bindings (they reference the service accounts and the repository).
  5. Writes the state to the bucket, `gs://learning-dev-2026-07-tfstate/cdp/dev/foundation/default.tfstate`, as resources finish:
     - About every 20 seconds during the apply, and once more at the end.
     - Each write overwrites the file; bucket versioning keeps every previous version
       (`gcloud storage ls -a` shows them).
     - View it: `gcloud storage ls gs://learning-dev-2026-07-tfstate/cdp/dev/foundation/` or `terraform state list`.
  6. If a resource fails:
     - Resources already created stay and are recorded in the state (no rollback).
     - Fix the cause, then `plan` and `apply` again; only the remaining changes are made.
  7. Deletes `default.tflock` from the bucket.
  8. Prints the stack outputs (`outputs.tf`). `foundation.tfplan` is now used up; delete it.

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
`$env:TF_LOG = "DEBUG"; terraform plan "-var-file=../../envs/dev/terraform.tfvars"`

### Terraform commands (copy-paste)

Run from the repository root in PowerShell. Deploys normally go through `cicd/deploy.yaml`; use these
to inspect a stack, or for the foundation stack, which only an admin applies.

Quote each whole `-flag=value` argument: Windows PowerShell splits an unquoted argument that starts
with `-` at a `.` (`-out=foundation.tfplan` arrives as `-out=foundation` and `.tfplan`), and
Terraform fails with "Too many command line arguments".

**1. Pick the stack and log in (every new PowerShell window)**

```powershell
$PROJECT = "learning-dev-2026-07"
$BUCKET  = "$PROJECT-tfstate"
$STACK   = "foundation"   # foundation | data | runtime
$env:GOOGLE_OAUTH_ACCESS_TOKEN = gcloud auth print-access-token
cd platform/terraform/stacks/$STACK
terraform init "-backend-config=bucket=$BUCKET" "-backend-config=prefix=cdp/dev/$STACK"
```

**2. Plan and apply**

```powershell
# foundation or data
terraform plan "-var-file=../../envs/dev/terraform.tfvars" "-out=$STACK.tfplan"
terraform apply "$STACK.tfplan"
Remove-Item "$STACK.tfplan"

# runtime also needs the image tags (use the _TAG of a deploy that pushed images)
$TAG = "v20261106-120000"
$REG = "us-central1-docker.pkg.dev/$PROJECT/cdp"
terraform plan "-var-file=../../envs/dev/terraform.tfvars" "-out=$STACK.tfplan" `
  "-var=customer_api_image=$REG/customer-api:$TAG" "-var=sources_image=$REG/sources:$TAG"
terraform apply "$STACK.tfplan"
Remove-Item "$STACK.tfplan"
```

**3. Look at the state**

```powershell
terraform state list                                   # every resource Terraform manages
terraform state show google_spanner_instance.cdp       # one resource's recorded attributes
terraform output                                       # the stack outputs
terraform state pull | Select-String '"serial"|"lineage"'          # serial and lineage
gcloud storage ls -a "gs://$BUCKET/cdp/dev/$STACK/"    # every saved version of the state file
```

**4. Fix problems**

```powershell
# "Error acquiring the state lock" after a killed run: the ID is in the error message
terraform force-unlock <LOCK_ID>

# Resource exists in GCP but not in the state ("already exists" on apply)
terraform import google_cloud_run_v2_service.customer_api "projects/$PROJECT/locations/us-central1/services/customer-api"

# Restore an older state version (bypasses the lineage/serial checks; copy the #generation from ls -a)
gcloud storage cp "gs://$BUCKET/cdp/dev/$STACK/default.tfstate#<GENERATION>" "gs://$BUCKET/cdp/dev/$STACK/default.tfstate"
```

**5. Destroy the runtime stack (normally `cicd/teardown.yaml`, which stops the Dataflow job first)**

```powershell
terraform destroy "-var-file=../../envs/dev/terraform.tfvars" `
  "-var=customer_api_image=$REG/customer-api:$TAG" "-var=sources_image=$REG/sources:$TAG"
```

**6. Back to the repository root**

```powershell
cd ../../../..
```

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

# Send test contacts from the mock vendor: one burst of 50
gcloud run jobs execute cdp-care-vendor --project=$PROJECT --region=$REGION --wait `
  --args="cdp_sources.care.mock_vendor,--count=50"

# Or continuous load with the job's default args (100 contacts/s until cancelled; 4-hour cap)
gcloud run jobs execute cdp-care-vendor --project=$PROJECT --region=$REGION
# Or choose rate, run time and faults: 100 contacts/s for 10 minutes, clean records only
#   --duration 90s|10m|2h   --no-bad-records (no resends, unknown callers or missing fields)
#   --start-seq N           continue an earlier run's sequence_id numbering
gcloud run jobs execute cdp-care-vendor --project=$PROJECT --region=$REGION `
  "--args=cdp_sources.care.mock_vendor,--rate=100,--duration=10m,--no-bad-records"
# Stop it (teardown also does this)
gcloud run jobs executions list --job=cdp-care-vendor --project=$PROJECT --region=$REGION --limit=1
gcloud run jobs executions cancel <EXECUTION_NAME> --project=$PROJECT --region=$REGION

# Every contact carries a sequence_id (resends repeat it). Missing numbers in core.interactions
# are in ops.dead_letter; anything in neither table was lost:
#   SELECT s FROM UNNEST(GENERATE_ARRAY(1, <last sequence_id>)) s
#   WHERE s NOT IN (SELECT sequence_id FROM core.interactions WHERE sequence_id IS NOT NULL)
#     AND s NOT IN (SELECT sequence_id FROM ops.dead_letter WHERE sequence_id IS NOT NULL)

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
