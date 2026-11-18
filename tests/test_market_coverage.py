from datetime import date
from io import BytesIO
import json
from types import SimpleNamespace

import pandas as pd
import pytest

from src import discovery_v031 as discovery, official_universe, v031, v051
from src.listing_exports import load_listing_export


def write_export(path, *rows):
    path.write_text('code,company,security_type,as_of,source_url\n' + '\n'.join(rows), encoding='utf-8')


def test_jpx_falls_through_to_japanese_workbook():
    workbook = BytesIO()
    pd.DataFrame([
        ['東京証券取引所 上場銘柄一覧', None, None],
        ['コード', '銘柄名', '市場・商品区分'],
        ['130A', 'Example', 'グロース（内国株式）'],
        ['2500', 'Foreign', 'プライム（外国株式）'],
        ['1489', 'ETF', 'ETF・ETN'],
    ]).to_excel(workbook, header=False, index=False)

    def get(url, **kwargs):
        content = workbook.getvalue() if url == official_universe.JPX_JAPANESE_XLS else b'<html>'
        return SimpleNamespace(content=content, raise_for_status=lambda: None)

    rows = official_universe.source_jpx_list(SimpleNamespace(get=get))
    assert [row['ticker'] for row in rows] == ['130A.T']
    assert rows[0]['discovery_source'] == official_universe.JPX_JAPANESE_XLS


def test_jpx_dispatches_legacy_workbook_to_xlrd(monkeypatch):
    def read_excel(data, **options):
        assert data.read().startswith(bytes.fromhex('d0cf11e0a1b11ae1'))
        assert options == {'header': None, 'dtype': str, 'engine': 'xlrd'}
        return pd.DataFrame([['Code', 'Name (English)', 'Section/Products'],
                             ['130A', 'Example', 'Growth (Domestic Stocks)']])

    monkeypatch.setattr(official_universe.pd, 'read_excel', read_excel)
    session = SimpleNamespace(get=lambda *a, **kw: SimpleNamespace(
        content=bytes.fromhex('d0cf11e0a1b11ae1'), raise_for_status=lambda: None))
    assert official_universe.source_jpx_list(session)[0]['ticker'] == '130A.T'


@pytest.mark.parametrize(('venue', 'hostname', 'code', 'ticker'), [
    ('KRX_KOSDAQ', 'kind.krx.co.kr', '247540', '247540.KQ'),
    ('SSE', 'www.sse.com.cn', '600000', '600000.SS'),
    ('SZSE', 'www.szse.cn', '000001', '000001.SZ'),
    ('BSE', 'www.bse.cn', '920001', '920001.BJ'),
    ('HKEX', 'www.hkex.com.hk', '00700', '0700.HK'),
    ('TPEX', 'www.tpex.org.tw', '6488', '6488.TWO'),
])
def test_publisher_export_normalization(tmp_path, venue, hostname, code, ticker):
    path = tmp_path / f'{venue}.csv'
    url = f'https://{hostname}/list'
    write_export(path, f'{code},Fixture,COMMON_EQUITY,2026-11-01,{url}',
                 f'1234,Excluded,ETF,2026-11-01,{url}')
    rows, detail = load_listing_export(path, venue, date(2026, 11, 18))
    assert [row['ticker'] for row in rows] == [ticker]
    assert detail['source_url'] == url and len(detail['source_sha256']) == 64
    assert detail['rejected_non_equity'] == 1


@pytest.mark.parametrize('row', [
    '00700,Fixture,COMMON_EQUITY,2026-11-01,https://hkex.com.hk.example.com/list',
    '00700,Fixture,COMMON_EQUITY,2026-02-01,https://hkex.com.hk/list',
    '00700,Fixture,AMBIGUOUS,2026-11-01,https://hkex.com.hk/list',
    '00700,Fixture,COMMON_EQUITY,2026-11-19,https://hkex.com.hk/list',
])
def test_export_rejects_untrusted_inputs(tmp_path, row):
    path = tmp_path / 'HKEX.csv'
    write_export(path, row)
    with pytest.raises(ValueError):
        load_listing_export(path, 'HKEX', date(2026, 11, 18))


def _universe_with_counts(counts):
    return pd.DataFrame([(market, f'{market}-{i}') for market, count in counts.items()
                         for i in range(count)], columns=['market', 'ticker'])


def test_fetch_budget_protects_all_five_markets_from_archived_imbalance():
    universe = _universe_with_counts({
        'Korea': 99, 'Japan': 310, 'China': 91, 'Hong Kong': 101, 'Taiwan': 1121,
    })
    sample = discovery.select_market_coverage_aware(universe, 150)
    counts = sample.market.value_counts()
    assert len(sample) == sample.ticker.nunique() == 150
    assert len(counts) == 5 and counts.min() >= 15
    assert 30 < counts['Taiwan'] < 98  # Above equal shares, below the old proportional allocation.
    shuffled = universe.sample(frac=1, random_state=11)
    assert discovery.select_market_coverage_aware(shuffled, 150).ticker.tolist() == sample.ticker.tolist()


def test_fetch_budget_uses_available_names_and_redistributes_unused_floor():
    universe = _universe_with_counts({'Taiwan': 300, 'Japan': 30, 'Korea': 2, 'China': 1})
    sample = discovery.select_market_coverage_aware(universe, 50)
    assert len(sample) == 50
    assert sample.market.value_counts().to_dict() == {'Taiwan': 39, 'Japan': 8, 'Korea': 2, 'China': 1}
    scarce_sample = discovery.select_market_coverage_aware(universe, 2)
    assert set(scarce_sample.market) == {'China', 'Korea'}
    assert len(discovery.select_market_coverage_aware(universe, 0)) == len(universe)


def test_five_market_coverage_and_fundamentals_audited_separately(tmp_path, monkeypatch):
    today = date.today().isoformat()
    exports = {
        'KRX_KOSPI': ('005930', 'https://kind.krx.co.kr/list'),
        'JPX': ('130A', 'https://www.jpx.co.jp/list'),
        'SSE': ('600000', 'https://www.sse.com.cn/list'),
        'HKEX': ('00700', 'https://www.hkex.com.hk/list'),
        'TPEX': ('6488', 'https://www.tpex.org.tw/list'),
    }
    for venue, (code, url) in exports.items():
        write_export(tmp_path / f'{venue}.csv', f'{code},Fixture,COMMON_EQUITY,{today},{url}')

    def unavailable(*args):
        raise ValueError('fixture: source unavailable')

    def taiwan():
        return official_universe.parse_twse_list([{'Code': '2330', 'CompanyName': 'TSMC'}])

    def vendor(ticker):
        if ticker.endswith('.SS'):
            raise ValueError('fixture: missing financial data')
        return {'vendor_quote_type': 'EQUITY', 'revenue_growth': .12, 'operating_margin': .1, 'roe': .1}

    monkeypatch.delenv('PUBLIC_DATA_API_KEY', raising=False)
    monkeypatch.delenv('GARP_LISTING_EXPORT_DIR', raising=False)
    monkeypatch.setattr(discovery, 'source_jpx_list', unavailable)
    monkeypatch.setattr(discovery, 'source_nikkei225', unavailable)
    monkeypatch.setattr(discovery, 'source_twse_list', taiwan)
    monkeypatch.setattr(discovery, 'source_region', unavailable)
    monkeypatch.setattr(v031, '_fetch_vendor', vendor)
    universe = tmp_path / 'universe.csv'
    universe.write_text('ticker,company,market,peer_group,industry_thesis\n0700.HK,Tencent,Hong Kong,unclassified,Fixture\n')
    baseline = tmp_path / 'baseline'
    v051.run(universe, baseline, max_symbols=0, delay_seconds=0, fx_mode='off', evidence_mode='off')
    before = pd.read_csv(baseline / '38_market_coverage_audit.csv').set_index('market')
    assert before.discovered_universe_n.sum() == 2
    assert before.listing_backed_tickers_n.sum() == 1

    monkeypatch.setenv('GARP_LISTING_EXPORT_DIR', str(tmp_path))
    output = tmp_path / 'outputs'
    result = v051.run(universe, output, max_symbols=0, delay_seconds=0, fx_mode='off', evidence_mode='off')
    coverage = pd.read_csv(output / '38_market_coverage_audit.csv').set_index('market')
    assert coverage.listing_backed_tickers_n.to_dict() == {
        'Korea': 1, 'Japan': 1, 'China': 1, 'Hong Kong': 1, 'Taiwan': 2,
    }
    assert coverage.discovered_universe_n.sum() == 6
    assert coverage.financial_observations_n.sum() == 5
    assert coverage.loc['China', 'financial_observations_n'] == 0
    assert coverage.screening_eligible_n.sum() == 0
    assert result['v051_market_evidence_quality']['full_five_market_census_verified'] is False
    discovered = pd.read_csv(output / '11_discovery_universe.csv').set_index('ticker')
    assert json.loads(discovered.loc['0700.HK', 'listing_source_ids']) == ['CURATED_LIST', 'export_HKEX']
    comparison = pd.read_csv(output / '45_coverage_comparison.csv').set_index('market')
    assert comparison.loc['Taiwan', 'archive_analyzed_share_pct'] == 65.1
    assert comparison.loc['Taiwan', 'discovered_universe_n'] == 2

    capped = tmp_path / 'capped'
    v051.run(universe, capped, max_symbols=5, delay_seconds=0, fx_mode='off', evidence_mode='off')
    capped_audit = pd.read_csv(capped / '38_market_coverage_audit.csv')
    assert capped_audit.selected_for_vendor_fetch_n.tolist() == [1] * 5
    assert capped_audit.market_fetch_floor_target_n.tolist() == [1] * 5
    assert capped_audit.market_fetch_floor_shortfall_n.tolist() == [0] * 5

    monkeypatch.setattr(v031, '_fetch_vendor', unavailable)
    output = tmp_path / 'failed'
    with pytest.raises(v031.FundamentalsUnavailable):
        v051.run(universe, output, max_symbols=0, delay_seconds=0, fx_mode='off', evidence_mode='off')
    comparison = pd.read_csv(output / '45_coverage_comparison.csv')
    assert set(comparison.current_run_status) == {'ALL_FINANCIAL_FETCHES_FAILED'}
    assert comparison.financial_observations_n.sum() == 0
    assert not (output / '44_v051_run_manifest.json').exists()
