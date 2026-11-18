"""Read-only coverage and candidate review of existing research artifacts."""
import argparse
from pathlib import Path

import pandas as pd

from .china_vendor_exports import LIVE_SOURCE_IDS, SOURCE_IDS
from .listing_exports import VENUES
from .venue_sources import SOURCES

PRIOR_COUNTS = {'Korea': 99, 'Japan': 3686, 'China': 91, 'Hong Kong': 101, 'Taiwan': 1121}
BASE_LIVE = {'KRX_KOSPI':'official_krx_listed_issues', 'KRX_KOSDAQ':'official_krx_listed_issues',
             'JPX':'official_jpx_full_listing', 'TWSE':'official_twse_listed_companies'}


def read(path):
    return pd.read_csv(path, dtype={'ticker': str}, keep_default_na=False)


def review_venues(universe, logs, benchmarks=None):
    import json

    statuses = logs.set_index('source').to_dict('index')
    membership = (universe.listing_source_ids.map(json.loads) if 'listing_source_ids' in universe
                  else pd.Series([[] for _ in range(len(universe))], index=universe.index))
    references = benchmarks.set_index('venue').to_dict('index') if benchmarks is not None else {}
    rows = []
    for venue, (market, _, _, suffix) in VENUES.items():
        live = BASE_LIVE.get(venue, f'live_{venue}' if venue in SOURCES else '')
        alternatives = {'KRX_KOSPI': ('live_KIND_KOSPI',), 'KRX_KOSDAQ': ('live_KIND_KOSDAQ',),
                        'SZSE': ('live_SZSE_JSON',), 'SSE': ('live_SSE_STAR',)}.get(venue, ())
        live_routes = (live, *alternatives)
        successful_live = {route for route in live_routes if statuses.get(route, {}).get('status') == 'OK'}
        sources = [*sorted(successful_live)]
        if statuses.get(f'export_{venue}', {}).get('status') == 'OK':
            sources.append(f'export_{venue}')
        venue_rows = universe.market.eq(market) & universe.ticker.str.endswith(suffix)
        supported = venue_rows & membership.map(lambda ids: bool(set(sources).intersection(ids)))
        live_supported = venue_rows & membership.map(lambda ids: bool(successful_live.intersection(ids)))
        vendor_sources = {'baostock_security_master', *SOURCE_IDS.values(), *LIVE_SOURCE_IDS.values()}
        vendor_supported = venue_rows & membership.map(lambda ids: bool(vendor_sources.intersection(ids)))
        reference = references.get(venue, {})
        reference_source = reference.get('source_id')
        comparable = (reference and reference_source in successful_live and
                      str(reference.get('as_of')) == str(statuses[reference_source].get('source_asof')) and
                      bool(reference.get('as_of')) and str(reference.get('scope_comparable')).lower() == 'true')
        rows.append(dict(venue=venue, market=market, live_source=live,
                         live_status=statuses.get(live, {}).get('status', 'NOT_REQUESTED' if live else 'NO_LIVE_CONNECTOR'),
                         successful_live_sources='|'.join(sorted(successful_live)),
                         live_failure_code=statuses.get(live, {}).get('failure_code', ''),
                         export_status=statuses.get(f'export_{venue}', {}).get('status', 'NOT_REQUESTED'),
                         discovered_n=int(venue_rows.sum()), publisher_supported_n=int(supported.sum()),
                         vendor_supported_n=int(vendor_supported.sum()),
                         vendor_and_official_overlap_n=int((vendor_supported & live_supported).sum()),
                         live_supported_n=int(live_supported.sum()), benchmark_url=reference.get('url', ''),
                         benchmark_n=reference.get('count', ''), benchmark_as_of=reference.get('as_of', ''),
                         same_scope_count_delta=(int((venue_rows & membership.map(lambda ids: reference_source in ids)).sum())
                                                 - int(reference['count'])) if comparable else '',
                         product_status='UNRESOLVED_SCOPE_VERIFICATION'))
    return pd.DataFrame(rows)


def candidate_review(ranked, stages=None):
    result = ranked.copy()
    eligible = result.v031_research_eligible.astype(str).str.lower().isin(['true', '1'])
    score = pd.to_numeric(result.cross_industry_score_100, errors='coerce')
    coverage = pd.to_numeric(result.score_coverage, errors='coerce')
    margin = pd.to_numeric(result.operating_margin, errors='coerce')
    roe = pd.to_numeric(result.roe, errors='coerce')
    invalid = result.v031_research_status.eq('REJECT_NON_EQUITY_INSTRUMENT')
    missing = result.fetch_error.ne('') | score.isna() | coverage.lt(.70) | margin.isna() | roe.isna()
    conflicts = result.data_quality_flags.ne('')
    category = result.peer_group.eq('unclassified')
    unresolved_type = result.v031_research_status.eq('SECURITY_TYPE_REQUIRES_VERIFICATION')
    masks = {'MISSING_OR_INSUFFICIENT_DATA': missing,
             'SOURCE_OR_DATA_QUALITY_REVIEW': conflicts,
             'UNRESOLVED_INDUSTRY': category, 'SECURITY_TYPE_REVIEW': unresolved_type}
    result['review_reasons'] = ['|'.join(key for key, mask in masks.items() if mask.iloc[i])
                                for i in range(len(result))]
    result['lifecycle'] = 'FUNDAMENTAL_SCREEN_FAILURE'
    result.loc[result.review_reasons.ne(''), 'lifecycle'] = 'RECOVERABLE_EXCLUSION'
    result.loc[invalid, 'lifecycle'] = 'INVALID_SECURITY'
    result.loc[eligible, 'lifecycle'] = 'RESEARCH_ELIGIBLE'
    if stages is not None and 'research_stage' in stages:
        result['existing_research_stage'] = result.ticker.map(stages.set_index('ticker').research_stage)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--benchmarks', type=Path)
    parser.add_argument('--reassessed-artifacts', type=Path, help='Output of the unchanged screen on corrected inputs')
    args = parser.parse_args()
    src, out = args.artifacts, args.output
    out.mkdir(parents=True, exist_ok=False)
    universe, logs = (read(src/name) for name in ('11_discovery_universe.csv', '12_discovery_sources_log.csv'))
    venues = review_venues(universe, logs, read(args.benchmarks) if args.benchmarks else None)
    venues.to_csv(out/'venue_coverage.csv', index=False)
    if not (src/'38_market_coverage_audit.csv').exists():
        return
    market = read(src/'38_market_coverage_audit.csv')
    market['reported_prior_analyzed_n'] = market.market.map(PRIOR_COUNTS)
    market.to_csv(out/'market_comparison.csv', index=False)
    if not (src/'01_all_research_candidates.csv').exists():
        return
    original = read(src/'01_all_research_candidates.csv')
    stages = src/'32_research_stage_gate.csv'
    audit = candidate_review(original, read(stages) if stages.exists() else None)
    if 'existing_research_stage' in audit:
        audit['pending_primary_filing_verification'] = audit.existing_research_stage.eq('SCREENED')
    audit.to_csv(out/'candidate_lifecycle.csv', index=False)
    for label in ('RECOVERABLE_EXCLUSION', 'FUNDAMENTAL_SCREEN_FAILURE', 'RESEARCH_ELIGIBLE'):
        audit[audit.lifecycle.eq(label)].to_csv(out/f'{label.lower()}.csv', index=False)
    audit[audit.market.eq('Korea') & audit.lifecycle.isin(['RESEARCH_ELIGIBLE', 'RECOVERABLE_EXCLUSION'])].to_csv(
        out/'korea_investigation_queue.csv', index=False)
    targets = pd.DataFrame({'ticker':['035420.KS','267260.KS']})
    targets.merge(audit, how='left', on='ticker').fillna({'lifecycle':'NOT_IN_INPUT_ARTIFACT'}).to_csv(
        out/'named_korea_review.csv', index=False)
    if args.reassessed_artifacts:
        newer = candidate_review(read(args.reassessed_artifacts/'01_all_research_candidates.csv'))
        fields = ['ticker', 'v031_research_eligible', 'cross_industry_score_100', 'lifecycle', 'review_reasons']
        audit[fields].merge(newer[fields], on='ticker', how='outer', suffixes=('_before', '_after'),
                            indicator=True, validate='one_to_one').to_csv(out/'reassessment.csv', index=False)


if __name__ == '__main__':
    main()
