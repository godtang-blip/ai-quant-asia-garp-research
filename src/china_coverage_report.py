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


def acquisition_acceptance(overlaps, source_log, probes):
    """Report only accepted route-backed rows as eligible for a downstream data fetch."""
    logs = source_log.set_index('source', verify_integrity=True).to_dict('index')
    rows = []
    for board, exchange in (('SZSE_MAIN', 'SZSE'), ('SZSE_CHINEXT', 'SZSE'), ('BSE', 'BSE')):
        board_rows = overlaps.loc[overlaps.board.eq(board)]
        live_count = imported_count = 0
        supporting = set()
        for refs in board_rows.listing_source_ids.map(json.loads):
            live, imported = set(), set()
            for source in refs:
                log = logs.get(source, {})
                if log.get('status') != 'OK':
                    continue
                if log.get('source_kind') == 'LIVE_LISTING' or log.get('retrieval_mode') in {
                    'LIVE_VENDOR_API', 'LIVE_VENDOR_SDK',
                }:
                    live.add(source)
                elif log.get('source_kind') == 'PUBLISHER_EXPORT' or log.get('retrieval_mode') == 'IMPORTED_VENDOR_SNAPSHOT':
                    imported.add(source)
            live_count += bool(live)
            imported_count += bool(imported)
            supporting.update(live | imported)
        tushare = logs.get(LIVE_SOURCE_IDS[exchange], {})
        if live_count:
            remaining = 'Validate dated scope and security type independently'
        elif imported_count:
            remaining = 'Live retrieval unverified; obtain dated scope evidence'
        elif tushare.get('status') == 'NOT_CONFIGURED_AUTH_REQUIRED':
            remaining = 'Entitled Tushare token or authorized dated SZSE/BSE file'
        else:
            remaining = 'Resolve provider access or supply authorized dated SZSE/BSE file'
        probe = next((row for row in probes if row['provider'] == 'Eastmoney'
                      and row['scope'].startswith(board + ' ')), {})
        rows.append(dict(board=board, live_accepted_n=live_count, imported_accepted_n=imported_count,
                         combined_unique_accepted_n=len(board_rows), accepted_sources='|'.join(sorted(supporting)),
                         acceptance=('LIVE_LISTINGS_RETRIEVED' if live_count else
                                     'IMPORTED_ONLY' if imported_count else 'NO_ACCEPTED_LISTINGS'),
                         can_enter_normal_financial_fetch=bool(live_count or imported_count),
                         screening_eligibility='NOT_EVALUATED',
                         normal_run_requirement=(
                             'Enable enable_tushare_research with validated token if using its live route'
                             if LIVE_SOURCE_IDS[exchange] in supporting else
                             'Keep accepted listing source configured in all5_official' if supporting else
                             'No accepted listings available from this run'
                         ),
                         tushare_status=tushare.get('status', 'NOT_REQUESTED'),
                         tushare_failure=tushare.get('failure_code', ''),
                         eastmoney_probe_status=probe.get('status', 'NOT_REQUESTED'),
                         eastmoney_http_status=probe.get('http_status', ''),
                         external_requirement=remaining))
    return pd.DataFrame(rows)
