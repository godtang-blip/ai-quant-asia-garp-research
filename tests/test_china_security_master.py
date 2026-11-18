from datetime import date, datetime
import json
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src import discovery_v031 as discovery
from src.china_security_master import fetch_baostock, validated_rows
from src.discovery_review import review_venues
from src.venue_sources import ListingError


def row(code, **kwargs):
    return dict(code=code, code_name='Sample ' + code, ipoDate='2000-01-01',
                outDate='', type='1', status='1') | kwargs


def inventory(as_of='2026-11-17'):
    master = [row('sh.600001'), row('sh.688001'), row('sz.000001'), row('sz.300001'),
              row('sh.900001'), row('sh.510001', type='5'), row('sz.002001', status='0'),
              row('sz.000002', type=''), row('bj.920001', type='')]
    return {'provider':'BaoStock', 'as_of':as_of, 'master':master,
            'snapshot':[{'code': record['code']} for record in master if record['status'] == '1']}


def test_validates_source_exchange_and_scope():
    rows, detail = validated_rows(inventory(), date(2026, 11, 18))
    assert {item['ticker'] for item in rows} == {'600001.SS','688001.SS','000001.SZ','300001.SZ'}
    assert json.loads(detail['scope_counts']) == {'SSE_MAIN':1, 'SSE_STAR':1, 'SZSE_MAIN':1,
                                                  'SZSE_CHINEXT':1, 'BSE':0}
    assert detail['rejected_non_equity'] == 2 and detail['inactive_or_after_cutoff'] == 1
    assert detail['unknown_classification'] == 2
    assert all(item['security_type_status'] == 'THIRD_PARTY_EQUITY_REQUIRES_VENDOR_CONFIRMATION'
               for item in rows)


@pytest.mark.parametrize('side', ['master','snapshot'])
def test_rejects_inventory_missing_from_either_side(side):
    data = inventory()
    data[side].pop(1)
    with pytest.raises(ListingError) as exc:
        validated_rows(data, date(2026, 11, 18))
    assert exc.value.code == 'INCOMPLETE_OR_STALE_SOURCE'


def test_stale_inventory_rejected():
    with pytest.raises(ListingError, match='stale'):
        validated_rows(inventory('2026-10-01'), date(2026, 11, 18))


def test_local_snapshot_is_labeled_imported(tmp_path, monkeypatch):
    snapshot = tmp_path/'snapshot.json'
    snapshot.write_text(json.dumps(inventory(str(datetime.now(ZoneInfo('Asia/Shanghai')).date()))))
    monkeypatch.setenv('GARP_BAOSTOCK_SNAPSHOT', str(snapshot))
    _, detail = fetch_baostock()
    assert detail['retrieval_mode'] == 'IMPORTED_VENDOR_SNAPSHOT'
    assert len(detail['source_sha256']) == 64


def test_official_failure_does_not_suppress_vendor_and_never_counts_as_official(monkeypatch):
    for name in ('source_nikkei225','source_jpx_list','source_twse_list'):
        monkeypatch.setattr(discovery, name, lambda: [])
    for key in ('PUBLIC_DATA_API_KEY','DART_API_KEY','GARP_LISTING_EXPORT_DIR'):
        monkeypatch.delenv(key, raising=False)

    def denied(venue):
        raise ListingError('FORBIDDEN', 'test refusal')

    monkeypatch.setattr(discovery, 'fetch_listing', denied)
    monkeypatch.setattr(discovery, 'fetch_baostock', lambda: validated_rows(inventory(), date(2026, 11, 18)))
    base = pd.DataFrame([dict(ticker='005930.KS', market='Korea')])
    universe, logs = discovery.discover_five_markets(base, 'all5_official', 0, security_master=True)
    assert len(universe) == 5
    venue = review_venues(universe, logs).set_index('venue').loc['SSE']
    assert venue.live_supported_n == 0 and venue.vendor_supported_n == 2
    assert universe.set_index('ticker').loc['600001.SS', 'listing_evidence_class'] == 'THIRD_PARTY_SECURITY_MASTER'


def test_tcp_preflight_failure_avoids_sdk_attempt(monkeypatch):
    from types import SimpleNamespace
    from src import china_security_master as master

    monkeypatch.delenv('GARP_BAOSTOCK_SNAPSHOT', raising=False)
    calls = []

    def run(cmd, **kwargs):
        calls.append(cmd)
        assert kwargs['timeout'] == 8
        return SimpleNamespace(returncode=1, stdout='DNS_ERROR\n')

    monkeypatch.setattr(master.subprocess, 'run', run)
    with pytest.raises(ListingError) as exc:
        master.fetch_baostock()
    assert exc.value.code == 'TCP_DNS_FAILURE'
    assert len(calls) == 1 and calls[0][-1] == '--tcp-probe'


def test_stalled_worker_surfaces_only_allowlisted_stage(monkeypatch):
    from types import SimpleNamespace
    from src import china_security_master as master

    monkeypatch.delenv('GARP_BAOSTOCK_SNAPSHOT', raising=False)
    monkeypatch.setattr(master, 'tcp_preflight', lambda: None)
    monkeypatch.setattr(master.subprocess, 'run', lambda *a, **kw: SimpleNamespace(
        returncode=3, stderr=b'BAOSTOCK_STAGE:login\nBAOSTOCK_STAGE:dated_inventory\nsecret SDK detail'))
    with pytest.raises(ListingError, match='dated_inventory') as exc:
        master.fetch_baostock()
    assert exc.value.code == 'TIMEOUT' and 'secret' not in str(exc.value)


@pytest.mark.parametrize(('phase', 'expected_rows'), [('master_query', 0), ('master_rows', 1)])
def test_inventory_first_and_separate_master_phase_metrics(monkeypatch, phase, expected_rows):
    import sys
    from datetime import timedelta
    from types import SimpleNamespace
    from src import china_security_master as master

    calls = []
    yesterday = str(datetime.now(ZoneInfo('Asia/Shanghai')).date() - timedelta(days=1))

    def rows(fields, records, stall=False):
        class Result:
            error_code = '0'

            def __init__(self):
                self.fields = fields
                self._records = iter(records)

            def next(self):
                self.current = next(self._records, None)
                if self.current is None and stall:
                    raise master.StageTimeout
                return self.current is not None

            def get_row_data(self):
                return self.current

        return Result()

    def query():
        calls.append('master')
        if phase == 'master_query':
            raise master.StageTimeout
        return rows(['code'], [['sz.000001']], stall=True)

    def dated(as_of):
        calls.append('inventory')
        assert as_of == yesterday
        return rows(['code'], [['sz.000001'], ['sz.300001'], ['sz.159001'], ['bj.920001']])

    monkeypatch.setitem(sys.modules, 'baostock', SimpleNamespace(
        login=lambda: SimpleNamespace(error_code='0'),
        query_trade_dates=lambda **kw: rows(['calendar_date', 'is_trading_day'], [[yesterday, '1']]),
        query_all_stock=dated, query_stock_basic=query))
    bundle = master.collect(allow_provisional=True)
    assert calls == ['inventory', 'master']
    assert bundle['master_failure_stage'] == phase and bundle['master_failure'] == 'TIMEOUT'
    assert 'master' not in bundle
    assert bundle['sdk_metrics']['dated_inventory']['rows'] == 4
    assert bundle['sdk_metrics'].get('master_rows', {}).get('rows', 0) == expected_rows
    assert 'duration_seconds' in bundle['sdk_metrics'][phase]
    provisional = master.provisional_shenzhen(bundle)
    assert [entry['ticker'] for entry in provisional] == ['000001.SZ', '300001.SZ']
    assert all(entry['screening_eligible'] is False for entry in provisional)


def test_china_only_provisional_rows_never_enter_discovery(monkeypatch):
    for key in ('DART_API_KEY','PUBLIC_DATA_API_KEY','GARP_TUSHARE_EXPORT_DIR','GARP_LISTING_EXPORT_DIR'):
        monkeypatch.delenv(key, raising=False)

    def listing(venue):
        assert venue in {'SSE','SSE_STAR','SZSE','SZSE_JSON','BSE'}
        return [], {}

    def vendor(*args):
        pytest.fail('A non-China route was called')

    monkeypatch.setattr(discovery, 'fetch_listing', listing)
    monkeypatch.setattr(discovery, 'source_jpx_list', vendor)
    monkeypatch.setattr(discovery, 'source_twse_list', vendor)
    monkeypatch.setattr(discovery, 'source_nikkei225', vendor)
    candidate = {'ticker':'000001.SZ', 'classification':'UNVERIFIED_INVENTORY_CANDIDATE',
                 'screening_eligible':False}
    monkeypatch.setattr(discovery, 'fetch_baostock', lambda: ([], dict(
        provisional_rows=[candidate], failure_stage='master_query', failure_code='TIMEOUT',
        sdk_metrics={'master_query': {'duration_seconds': 12}})))
    sink = []
    base = pd.DataFrame([dict(ticker='005930.KS', market='Korea'), dict(ticker='600000.SS', market='China')])
    universe, logs = discovery.discover_five_markets(base, 'all5_official', 0, security_master=True,
                                                    china_only=True, provisional_inventory=sink)
    assert universe.ticker.tolist() == ['600000.SS'] and sink == [candidate]
    audit = logs.set_index('source').loc['baostock_security_master']
    assert audit.status == 'PROVISIONAL_INVENTORY_ONLY'
    assert audit.accepted_pattern == 0 and audit.evidence_classification == 'UNVERIFIED_CANDIDATE'
    assert audit.failure_stage == 'master_query'
