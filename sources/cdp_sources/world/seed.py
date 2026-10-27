"""Generate the customer world into Cloud Storage and load it into Spanner (Cloud Run job `cdp-seed`).

  python -m cdp_sources.world.seed --count 10000
"""

import argparse

from cdp_common.config import Settings

from cdp_sources.world.bootstrap_spanner import load
from cdp_sources.world.generator import write_world


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=10_000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    settings = Settings.from_env()
    write_world(args.count, args.seed, settings.world_uri)
    load(settings)


if __name__ == "__main__":
    main()
