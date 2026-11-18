import pandas as pd

from src.china_coverage_report import china_reports


def test_report_distinguishes_board_counts_vendor_status_and_verified_benchmarks():
    universe = pd.DataFrame([
        dict(ticker='600001.SS', market='China', listing_source_ids='["live_SSE"]'),
        dict(ticker='000001.SZ', market='China', listing_source_ids='["tushare_SZSE_api"]'),
        dict(ticker='300001.SZ', market='China', listing_source_ids='["CURATED_LIST"]'),
    ]).assign(listing_evidence_class='', listing_source_names='{}', listing_name_disagreement=False)
    logs = pd.DataFrame([
        dict(source='live_SSE', status='OK', source_asof='2026-11-18'),
        dict(source='tushare_SZSE_api', status='OK', source_asof=''),
        dict(source='live_BSE', status='FAILED_NO_FALLBACK', source_asof=''),
    ])
    refs = pd.DataFrame([
        dict(board='SSE_MAIN', source_id='live_SSE', as_of='2026-11-18', scope_comparable='true', count=2),
        dict(board='SZSE_MAIN', source_id='tushare_SZSE_api', as_of='2026-11-18',
             scope_comparable='true', count=2),
    ])
    counts, overlap = china_reports(universe, logs, refs)
    counts = counts.set_index(['board','source'])
    assert counts.loc[('SSE_MAIN','live_SSE'), 'same_scope_count_delta'] == -1
    assert counts.loc[('SZSE_MAIN','tushare_SZSE_api'), 'same_scope_count_delta'] == ''
    assert counts.loc[('BSE','live_BSE'), 'accepted_rows'] == 0
    assert counts.loc[('BSE','live_BSE'), 'status'] == 'FAILED_NO_FALLBACK'
    assert overlap.set_index('ticker').loc['300001.SZ','board'] == 'UNRESOLVED'


def test_acceptance_counts_deduplicated_input_and_keeps_probe_separate():
    from src.china_coverage_report import acquisition_acceptance

    overlaps = pd.DataFrame([
        dict(board='SZSE_MAIN', listing_source_ids='["tushare_SZSE_api","export_SZSE"]'),
        dict(board='SZSE_MAIN', listing_source_ids='["tushare_SZSE_api"]'),
        dict(board='BSE', listing_source_ids='["export_BSE"]'),
    ])
    logs = pd.DataFrame([
        dict(source='tushare_SZSE_api', status='OK', source_kind='THIRD_PARTY_SECURITY_MASTER',
             retrieval_mode='LIVE_VENDOR_API'),
        dict(source='export_SZSE', status='OK', source_kind='PUBLISHER_EXPORT'),
        dict(source='export_BSE', status='OK', source_kind='PUBLISHER_EXPORT'),
    ]).fillna('')
    probes = [dict(provider='Eastmoney', scope='SZSE_CHINEXT reported selector', status='HTTP_ENDPOINT_REACHED',
                   http_status=200)]
    result = acquisition_acceptance(overlaps, logs, probes).set_index('board')
    assert result.loc['SZSE_MAIN', 'live_accepted_n'] == 2
    assert result.loc['SZSE_MAIN', 'combined_unique_accepted_n'] == 2
    assert result.loc['SZSE_CHINEXT', 'acceptance'] == 'NO_ACCEPTED_LISTINGS'
    assert not result.loc['SZSE_CHINEXT', 'can_enter_normal_financial_fetch']
    assert result.loc['BSE','acceptance'] == 'IMPORTED_ONLY'
    assert result.screening_eligibility.eq('NOT_EVALUATED').all()
