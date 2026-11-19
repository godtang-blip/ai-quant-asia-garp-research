from datetime import date
from decimal import Decimal
from hashlib import sha256
import json

import pandas as pd
import pytest

from src.filing_evidence import reconcile
from src.v06 import FinancialBudget


CUTOFF = date(2026, 11, 1)
LISTINGS = [
    ('005930.KS', 'Korea', 'KRX', 'opendart.fss.or.kr'),
    ('8035.T', 'Japan', 'JPX', 'disclosure2.edinet-fsa.go.jp'),
    ('600001.SS', 'China', 'SSE_MAIN', 'sse.com.cn'),
    ('688001.SS', 'China', 'SSE_STAR', 'sse.com.cn'),
    ('000001.SZ', 'China', 'SZSE_MAIN', 'szse.cn'),
    ('300001.SZ', 'China', 'SZSE_CHINEXT', 'szse.cn'),
    ('920001.BJ', 'China', 'BSE', 'bse.cn'),
    ('0981.HK', 'Hong Kong', 'HKEX', 'hkexnews.hk'),
    ('2330.TW', 'Taiwan', 'TWSE', 'mops.twse.com.tw'),
    ('6488.TWO', 'Taiwan', 'TPEX', 'mops.twse.com.tw'),
]


@pytest.fixture(params=LISTINGS, ids=[row[2] for row in LISTINGS])
def primary(request, tmp_path):
    ticker, market, venue, host = request.param
    source = b'synthetic source fixture: consolidated FY revenue was 2 million'
    digest = sha256(source).hexdigest()
    (tmp_path / digest).write_bytes(source)
    return dict(ticker=ticker, market=market, venue=venue, issuer_id=ticker,
                issuer_name='Synthetic issuer', metric='revenue', definition='TOTAL_REVENUE',
                statement='INCOME', period_start='2025-01-01', period_end='2025-12-31',
                publication_date='2026-03-01', period_kind='FY', scope='CONSOLIDATED',
                currency='USD', unit='CURRENCY', value='2', scale='1000000',
                source_url=f'https://{host}/synthetic-fixture', source_locator='fixture line 1',
                source_sha256=digest, provider_version='fixture', parser_version='fixture')


def test_market_scaled_reconciliation(primary, tmp_path):
    vendor = dict(primary, value='1980000', scale='1')
    row, = reconcile([primary], [vendor], tmp_path, CUTOFF)
    assert row['status'] == 'MACHINE_RECONCILED'
    assert Decimal(row['relative_difference']) == Decimal('0.01')
    assert row['value'] == '2'


def test_incompatible_context_and_discrepancy(primary, tmp_path):
    for patch in ({'scope': 'SEPARATE'}, {'period_kind': 'YTD'}, {'currency': 'CNY'}):
        row, = reconcile([primary], [dict(primary, **patch)], tmp_path, CUTOFF)
        assert row['status'] == 'UNVERIFIED'
    row, = reconcile([primary], [dict(primary, value='-2')], tmp_path, CUTOFF)
    assert row['status'] == 'BLOCKED'
    assert row['reason'] == 'NUMERICAL_DISCREPANCY'


def test_checksum_and_lookahead(primary, tmp_path):
    row, = reconcile([dict(primary, publication_date='2026-11-02')], [primary], tmp_path, CUTOFF)
    assert row['reason'] == 'INVALID_OR_FUTURE_PERIOD'
    (tmp_path / primary['source_sha256']).write_bytes(b'modified')
    row, = reconcile([primary], [primary], tmp_path, CUTOFF)
    assert row['reason'] == 'SOURCE_CHECKSUM_MISMATCH'


def test_checkpoint_resumes_with_no_duplicate_fetch(tmp_path):
    path = tmp_path / 'checkpoint.sqlite'
    calls = []

    def fetch(ticker):
        calls.append(ticker)
        return {'value': 42}

    run = FinancialBudget(path, CUTOFF, 1, 0, fetch)
    assert run('A') == {'value': 42}
    with pytest.raises(RuntimeError, match='BUDGET_EXHAUSTED'):
        run('B')
    run.connection.close()
    resumed = FinancialBudget(path, CUTOFF, 1, 0, fetch)
    try:
        assert resumed('A') == {'value': 42}
        assert resumed('B') == {'value': 42}
    finally:
        resumed.connection.close()
    assert calls == ['A', 'B']


def test_five_market_cli_snapshot(monkeypatch, tmp_path):
    from src.v06 import main

    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    tickers = ['005930.KS', '8035.T', '002371.SZ', '0981.HK', '2330.TW']
    snapshot = tmp_path / 'vendor.csv'
    pd.DataFrame([{'ticker': ticker, 'vendor_quote_type': 'EQUITY',
                   'financial_currency': 'USD', 'currency': 'USD',
                   'operating_margin': .20, 'roe': .15, 'revenue_growth': .12,
                   'earnings_growth': .13} for ticker in tickers]).to_csv(snapshot, index=False)
    output = tmp_path / 'outputs'
    monkeypatch.setattr('sys.argv', ['v06', '--discover-mode', 'off', '--output', str(output),
                                    '--snapshot-csv', str(snapshot), '--max-symbols', '5',
                                    '--asof-date', CUTOFF.isoformat()])
    main()
    manifest = json.loads((output / '67_v06_run_manifest.json').read_text())
    assert all(row['financial_fetch_succeeded'] == 1 for row in manifest['coverage'])
    assert manifest['vendor_requests'] == 0
    assert manifest['trade_orders'] == 'NONE'
    assert manifest['shortlisted'] == 0
    assert '검토를 완료한 후보가 없습니다' in (output / '66_candidate_briefs.md').read_text()
