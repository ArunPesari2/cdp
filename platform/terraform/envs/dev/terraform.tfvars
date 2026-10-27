# dev environment: one GCP project per environment.
project_id         = "learning-dev-2026-07"
region             = "us-central1"
env                = "dev"
bq_location        = "US"
billing_account_id = "XXXXXX-XXXXXX-XXXXXX"
monthly_budget     = 2000 # INR

labels = {
  app = "cdp"
  env = "dev"
}

