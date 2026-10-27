"""Generate the ground-truth world of customers (people + phone numbers).

Writes people.parquet to CDP_WORLD_URI (a gs:// path). Seeded, so the same
--count and --seed always produce the same people.

  python -m cdp_sources.world.generator --count 10000
"""

import argparse
import random

import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker

from cdp_common.config import Settings

AREA_CODES = ["206", "253", "360", "425", "509", "212", "312", "415", "503", "617",
              "702", "713", "720", "786", "808", "857", "901", "913", "949", "972"]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "hotmail.com"]


def generate_people(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)

    people, phones, emails = [], set(), set()
    for i in range(1, count + 1):
        first, last = fake.first_name(), fake.last_name()

        phone = None
        while phone is None or phone in phones:
            phone = f"+1{rng.choice(AREA_CODES)}{rng.randint(200, 999)}{rng.randint(0, 9999):04d}"
        phones.add(phone)

        email = None
        while email is None or email in emails:
            email = f"{first.lower()}.{last.lower()}{rng.randint(1, 9999)}@{rng.choice(EMAIL_DOMAINS)}"
        emails.add(email)

        people.append({
            "person_id": f"P-{i:07d}",
            "first_name": first,
            "last_name": last,
            "email": email,
            "phone": phone,
            "status": rng.choices(["active", "suspended"], weights=[97, 3])[0],
        })
    return people


def write_world(count: int, seed: int, uri: str) -> None:
    people = generate_people(count, seed)
    pq.write_table(pa.Table.from_pylist(people), uri)
    print(f"Wrote {len(people)} people to {uri}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    write_world(args.count, args.seed, Settings.from_env().world_uri)


if __name__ == "__main__":
    main()
