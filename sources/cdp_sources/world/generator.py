"""Generate the ground-truth world of customers (people + phone numbers).

Writes people.parquet to CDP_WORLD_URI (a gs:// path). Seeded, so the same
count and seed always produce the same people. The fixed demo customers
(cdp_sources.demo_stories) are added after the random ones.
Run through cdp_sources.world.seed.
"""

import random

import pyarrow as pa
import pyarrow.parquet as pq
from faker import Faker

from cdp_sources.demo_stories import DEMO_CUSTOMERS

AREA_CODES = ["206", "253", "360", "425", "509", "212", "312", "415", "503", "617",
              "702", "713", "720", "786", "808", "857", "901", "913", "949", "972"]
EMAIL_DOMAINS = ["gmail.com", "yahoo.com", "outlook.com", "icloud.com", "hotmail.com"]


def generate_people(count: int, seed: int) -> list[dict]:
    rng = random.Random(seed)
    fake = Faker("en_US")
    fake.seed_instance(seed)

    demo_people = [c["person"] for c in DEMO_CUSTOMERS]
    # Start the "taken" sets with the demo numbers and addresses, so no random person gets one.
    people = []
    phones = {p["phone"] for p in demo_people}
    emails = {p["email"] for p in demo_people}
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
    # Appended last, so the random people (and their person_ids) are the same as before.
    return people + [dict(p) for p in demo_people]


def write_world(count: int, seed: int, uri: str) -> None:
    people = generate_people(count, seed)
    pq.write_table(pa.Table.from_pylist(people), uri)
    print(f"Wrote {len(people)} people to {uri}")
