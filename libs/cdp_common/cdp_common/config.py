"""Settings shared by CDP Python components, read from environment variables.

In GCP the variables are set on the Cloud Run job / Dataflow template by Terraform.
"""

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]

# Pub/Sub names used by the care slice (created by platform/terraform/stacks/runtime).
CARE_VENDOR_TOPIC = "vendor-care-ctr"


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Environment variable {name} is not set")
    return value


@dataclass(frozen=True)
class Settings:
    project: str
    spanner_instance: str
    spanner_database: str
    world_uri: str  # e.g. gs://<project>-cdp-world/world/people.parquet

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            project=_require("GCP_PROJECT"),
            spanner_instance=os.environ.get("SPANNER_INSTANCE", "cdp-instance"),
            spanner_database=os.environ.get("SPANNER_DATABASE", "cdp"),
            world_uri=_require("CDP_WORLD_URI"),
        )
