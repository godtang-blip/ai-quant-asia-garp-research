"""Run official and independent listing discovery without requesting company fundamentals."""
import argparse
import os
from pathlib import Path

import pandas as pd

from .china_connectivity import probe_providers
from .china_coverage_report import acquisition_acceptance, china_reports
from .discovery_review import read, review_venues
from .discovery_v031 import discover_five_markets
from .v031 import _read_curated


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', type=Path, default=Path('data/universe.csv'))
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--china-only', action='store_true', help='Run mainland China listings sources only')
    parser.add_argument('--china-benchmarks', type=Path,
                        help='Optional dated, scope-matched official China board CSV')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    provisional = []
    probes = []
    if args.china_only and os.environ.get('GARP_CHINA_PROVIDER_PROBE') == '1':
        probes = probe_providers(os.environ.get('GARP_EASTMONEY_PROBE_ALLOWED') == '1')
        pd.DataFrame(probes).to_csv(args.output/'51_china_provider_probe.csv', index=False)
    universe, logs = discover_five_markets(_read_curated(args.universe), 'all5_official', per_region=0,
                                          security_master=True, china_only=args.china_only,
                                          provisional_inventory=provisional)
    pd.DataFrame(provisional, columns=['ticker', 'source_asof', 'source', 'classification',
                                       'screening_eligible']).to_csv(
        args.output/'48_baostock_provisional_shenzhen.csv', index=False)
    universe.to_csv(args.output/'11_discovery_universe.csv', index=False)
    logs.to_csv(args.output/'12_discovery_sources_log.csv', index=False)
    venues = review_venues(universe, logs)
    if args.china_only:
        venues = venues.loc[venues.market.eq('China')]
    venues.to_csv(args.output/'47_venue_coverage.csv', index=False)
    coverage, overlaps = china_reports(
        universe, logs, read(args.china_benchmarks) if args.china_benchmarks else None)
    coverage.to_csv(args.output/'49_china_board_coverage.csv', index=False)
    overlaps.to_csv(args.output/'50_china_source_overlap.csv', index=False)
    acquisition_acceptance(overlaps, logs, probes).to_csv(
        args.output/'52_china_acquisition_acceptance.csv', index=False)
    print(venues[['venue', 'live_status', 'successful_live_sources', 'live_supported_n']].to_string(index=False))


if __name__ == '__main__':
    main()
