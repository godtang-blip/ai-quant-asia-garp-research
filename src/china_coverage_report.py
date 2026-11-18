"""Board-level listing evidence for the China-only discovery artifact."""
import json

import pandas as pd

from .china_vendor_exports import LIVE_SOURCE_IDS, SOURCE_IDS

BOARDS = {
    'SSE_MAIN': (r'(?:600|601|603|605)\d{3}\.SS', {'live_SSE', 'export_SSE'}),
    'SSE_STAR': (r'(?:688|689)\d{3}\.SS', {'live_SSE_STAR', 'export_SSE'}),
    'SZSE_MAIN': (r'(?:000|001|002|003)\d{3}\.SZ', {'live_SZSE', 'live_SZSE_JSON', 'export_SZSE',
                                                      SOURCE_IDS['SZSE'], LIVE_SOURCE_IDS['SZSE']}),
    'SZSE_CHINEXT': (r'(?:300|301)\d{3}\.SZ', {'live_SZSE', 'live_SZSE_JSON', 'export_SZSE',
                                                  SOURCE_IDS['SZSE'], LIVE_SOURCE_IDS['SZSE']}),
    'BSE': (r'(?:4\d|8\d|92)\d{4}\.BJ', {'live_BSE', 'export_BSE', SOURCE_IDS['BSE'], LIVE_SOURCE_IDS['BSE']}),
}


def china_reports(universe, source_log, benchmarks=None):
    china = universe.loc[universe.market.eq('China')].copy()
    china['board'] = 'UNRESOLVED'
    membership = china.listing_source_ids.map(json.loads)
    logs = source_log.set_index('source', verify_integrity=True).to_dict('index')
    refs = benchmarks.set_index(['board', 'source_id'], verify_integrity=True).to_dict('index') if benchmarks is not None else {}
    rows = []
    for board, (pattern, allowed) in BOARDS.items():
        codes = china.ticker.str.fullmatch(pattern)
        providers = allowed | {'baostock_security_master'}
        evidence = codes & membership.map(lambda ids: bool(providers.intersection(ids)))
        china.loc[evidence, 'board'] = board
        for source in sorted(providers):
            log = logs.get(source, {})
            count = int((codes & membership.map(lambda ids: source in ids)).sum())
            reference = refs.get((board, source), {})
            compared = (reference and log.get('source_asof') and
                        log['source_asof'] == reference.get('as_of') and
                        str(reference.get('scope_comparable', '')).lower() == 'true')
            rows.append(dict(
                board=board, source=source, accepted_rows=count,
                status=log.get('status', 'NOT_REQUESTED'), source_url=log.get('source_url', ''),
                observed_utc=log.get('observed_utc', ''), source_asof=log.get('source_asof', ''),
                evidence_classification=log.get('evidence_classification') or log.get('source_kind', ''),
                retrieval_mode=log.get('retrieval_mode', ''), failure_code=log.get('failure_code', ''),
                provider_received=log.get('received', ''), provider_duplicates=log.get('duplicate_rows', ''),
                provider_excluded=log.get('rejected_non_equity', ''),
                completeness_check=log.get('completeness_check', ''),
                benchmark_source=reference.get('url', ''), benchmark_as_of=reference.get('as_of', ''),
                benchmark_rows=reference.get('count', ''),
                same_scope_count_delta=count - int(reference['count']) if compared else '',
            ))
    overlaps = china[['ticker', 'board', 'listing_evidence_class', 'listing_source_ids',
                     'listing_source_names', 'listing_name_disagreement']].copy()
    overlaps['source_count'] = membership.map(lambda ids: len(set(ids) - {'CURATED_LIST'}))
    return pd.DataFrame(rows), overlaps
