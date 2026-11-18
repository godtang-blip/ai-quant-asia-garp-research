"""Run official and independent listing discovery without requesting company fundamentals."""
import argparse
from pathlib import Path

from .discovery_review import review_venues
from .discovery_v031 import discover_five_markets
from .v031 import _read_curated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', type=Path, default=Path('data/universe.csv'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    universe, logs = discover_five_markets(_read_curated(args.universe), 'all5_official', per_region=0, security_master=True)
    universe.to_csv(args.output/'11_discovery_universe.csv', index=False)
    logs.to_csv(args.output/'12_discovery_sources_log.csv', index=False)
    venues = review_venues(universe, logs)
    venues.to_csv(args.output/'47_venue_coverage.csv', index=False)
    print(venues[['venue', 'live_status', 'successful_live_sources', 'live_supported_n']].to_string(index=False))


if __name__ == '__main__':
    main()
