"""Exercise the listing-to-financial pipeline with provider responses mocked."""

from datetime import datetime
import json
import sys
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pandas as pd

from src import discovery_v031 as discovery
from src import v051

HEADER = 'as_of,ts_code,symbol,name,exchange,market,list_status,list_date,delist_date\n'


def test_imported_shenzhen_and_beijing_reach_unchanged_financial_gates(tmp_path, monkeypatch):
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()
    imports = tmp_path / 'imports'
    imports.mkdir()
    (imports / 'SZSE.csv').write_text(
        HEADER
        + f'{today},000001.SZ,000001,Main fixture,SZSE,主板,L,19910403,\n'
        + f'{today},300001.SZ,300001,ChiNext fixture,SZSE,创业板,L,20091030,\n',
        encoding='utf-8',
    )
    (imports / 'BSE.csv').write_text(
        HEADER
        + f'{today},920002.BJ,920002,Beijing equity fixture,BSE,北交所,L,20240101,\n'
        + f'{today},920003.BJ,920003,Beijing fund-type fixture,BSE,北交所,L,20240101,\n'
        + f'{today},920004.BJ,920004,Beijing unavailable fixture,BSE,北交所,L,20240101,\n'
        + f'{today},920005.BJ,920005,Beijing weak fixture,BSE,北交所,L,20240101,\n'
        + f'{today},830002.BJ,830002,NEEQ only fixture,BSE,新三板,L,20200101,\n',
        encoding='utf-8',
    )
    universe = tmp_path / 'universe.csv'
    universe.write_text(
        'ticker,company,market,peer_group,industry_thesis\n'
        '600519.SS,Shanghai fixture,China,chip_components,fixture\n'
    )
    monkeypatch.setenv('GARP_TUSHARE_EXPORT_DIR', str(imports))
    for key in ('PUBLIC_DATA_API_KEY', 'DART_API_KEY', 'GARP_ENABLE_BAOSTOCK',
                'TUSHARE_TOKEN', 'GARP_LISTING_EXPORT_DIR'):
        monkeypatch.delenv(key, raising=False)
    for adapter in ('source_nikkei225', 'source_jpx_list', 'source_twse_list'):
        monkeypatch.setattr(discovery, adapter, lambda: [])
    monkeypatch.setattr(discovery, 'fetch_listing', lambda venue: ([], {}))

    requested = []
    equity = dict(quoteType='EQUITY', revenueGrowth=.25, earningsGrowth=.26, operatingMargins=.2,
                  returnOnEquity=.18, forwardPE=22, priceToSalesTrailing12Months=2.5,
                  debtToEquity=40, **{'52WeekChange': .15}, currency='CNY', financialCurrency='CNY',
                  industry='semiconductors')

    def ticker(symbol):
        requested.append(symbol)
        response = {
            '920005.BJ': dict(equity, operatingMargins=-.2),
            '920003.BJ': dict(equity, quoteType='ETF'),
            '920004.BJ': {},
        }.get(symbol, equity)
        return SimpleNamespace(get_info=lambda: response)

    monkeypatch.setitem(sys.modules, 'yfinance', SimpleNamespace(Ticker=ticker))
    outputs = tmp_path / 'outputs'
    v051.run(universe, outputs, max_symbols=0, per_region=0, delay_seconds=0,
             discover_mode='all5_official', fx_mode='off', evidence_mode='off')

    assert set(requested) == {'600519.SS', '000001.SZ', '300001.SZ',
                              '920002.BJ', '920003.BJ', '920004.BJ', '920005.BJ'}
    discovered = pd.read_csv(outputs / '11_discovery_universe.csv').set_index('ticker')
    assert json.loads(discovered.loc['000001.SZ', 'listing_source_ids']) == ['tushare_SZSE_snapshot']
    assert json.loads(discovered.loc['920002.BJ', 'listing_source_ids']) == ['tushare_BSE_snapshot']
    assert discovered.loc['920002.BJ', 'listing_evidence_class'] == 'THIRD_PARTY_SECURITY_MASTER'
    assert discovered.loc['920002.BJ', 'security_type_status'] == 'THIRD_PARTY_EQUITY_REQUIRES_VENDOR_CONFIRMATION'
    sources = pd.read_csv(outputs / '12_discovery_sources_log.csv').set_index('source')
    for source in ('tushare_SZSE_snapshot', 'tushare_BSE_snapshot'):
        assert sources.loc[source, 'source_asof'] == today
        assert sources.loc[source, 'retrieval_mode'] == 'IMPORTED_VENDOR_SNAPSHOT'
    ranked = pd.read_csv(outputs / '01_all_research_candidates.csv').set_index('ticker')
    assert ranked.loc['300001.SZ', 'v031_research_status'] == 'PROVISIONAL_NEW_DISCOVERY'
    assert ranked.loc['920002.BJ', 'security_type_status'] == 'VERIFIED_EQUITY_VENDOR'
    assert ranked.loc['920002.BJ', 'v031_research_status'] == 'PROVISIONAL_NEW_DISCOVERY'
    assert ranked.loc['920005.BJ', 'v031_research_status'] == 'REVIEW_REQUIRED'
    assert ranked.loc['920003.BJ', 'v031_research_status'] == 'REJECT_NON_EQUITY_INSTRUMENT'
    assert ranked.loc['920004.BJ', 'v031_research_status'] == 'SECURITY_TYPE_REQUIRES_VERIFICATION'
    assert 'No fundamentals from vendor' in ranked.loc['920004.BJ', 'fetch_error']
    assert not ranked['v031_memo_ready'].any()
    stages = pd.read_csv(outputs / '32_research_stage_gate.csv').set_index('ticker')
    assert not stages['memo_ready'].any()


def test_bounded_finance_probe_does_not_expose_vendor_response(monkeypatch):
    import subprocess
    from src import china_finance_probe as probe
    from src import v031
    from src.quality_v051 import FINANCIAL_FIELDS

    def blocked(symbol):
        exc = ConnectionError('CONNECT tunnel failed, response 403: PROXY_INTERNAL_ERROR')
        exc.response = SimpleNamespace(status_code=0)
        raise exc

    monkeypatch.setattr(v031, '_fetch_vendor', blocked)
    result = probe.lookup('920002.BJ')
    assert result['status'] == 'PROXY_CONNECTION_FAILED'
    assert 'PROXY_INTERNAL_ERROR' not in str(result)

    monkeypatch.setattr(v031, '_fetch_vendor', lambda symbol: {
        **dict.fromkeys(FINANCIAL_FIELDS, float('nan')), 'revenue_growth': .25,
        'vendor_quote_type': 'EQUITY',
    })
    result = probe.lookup('000001.SZ')
    assert result['status'] == 'EQUITY_WITH_FINANCIAL_OBSERVATIONS'
    assert result['financial_fields_present'] == 'revenue_growth'
    assert '.25' not in str(result)

    def exceeds_budget(cmd, **kwargs):
        assert kwargs['timeout'] == 15
        raise subprocess.TimeoutExpired(cmd, kwargs['timeout'])

    monkeypatch.setattr(probe.subprocess, 'run', exceeds_budget)
    assert probe.probe_symbol('BSE', '920002.BJ')['status'] == 'PROBE_TIMEOUT'
