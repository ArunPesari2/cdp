"""Load the world's people into Spanner Customer + IdentityMap.

Stand-in for the CRM CDC flow (Flow A) until the mock CRM exists. customer_id
is derived deterministically from person_id, so re-running is idempotent.

  python -m cdp_sources.world.bootstrap_spanner
"""

import uuid

import pyarrow.parquet as pq
from google.cloud import spanner

from cdp_common.config import Settings

CUSTOMER_NAMESPACE = uuid.UUID("5f0c1d2e-3a4b-4c5d-8e6f-7a8b9c0d1e2f")
BATCH_SIZE = 500


def customer_id_for(person_id: str) -> str:
    return str(uuid.uuid5(CUSTOMER_NAMESPACE, person_id))


def load(settings: Settings) -> None:
    people = pq.read_table(settings.world_uri).to_pylist()
    database = (
        spanner.Client(project=settings.project)
        .instance(settings.spanner_instance)
        .database(settings.spanner_database)
    )

    for start in range(0, len(people), BATCH_SIZE):
        chunk = people[start:start + BATCH_SIZE]
        customers, identities = [], []
        for p in chunk:
            cid = customer_id_for(p["person_id"])
            customers.append((cid, p["first_name"], p["last_name"], p["email"], p["phone"],
                              p["status"], spanner.COMMIT_TIMESTAMP, spanner.COMMIT_TIMESTAMP))
            identities.append(("phone", p["phone"], cid, spanner.COMMIT_TIMESTAMP))
            identities.append(("email", p["email"], cid, spanner.COMMIT_TIMESTAMP))

        with database.batch() as batch:
            batch.insert_or_update(
                "Customer",
                columns=("customer_id", "first_name", "last_name", "email", "phone",
                         "status", "created_at", "updated_at"),
                values=customers,
            )
            batch.insert_or_update(
                "IdentityMap",
                columns=("id_type", "id_value", "customer_id", "created_at"),
                values=identities,
            )

    print(f"Loaded {len(people)} customers and {2 * len(people)} identities into Spanner")


def main() -> None:
    load(Settings.from_env())


if __name__ == "__main__":
    main()
