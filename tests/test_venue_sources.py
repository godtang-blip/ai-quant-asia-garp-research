from io import BytesIO
from types import SimpleNamespace
import json

import pandas as pd
import pytest
import requests

from src.discovery_review import candidate_review, review_venues
from src.official_universe import source_krx_list
from src.venue_sources import ListingError, failure_code, fetch_listing, parse_records


def response(body):
    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def raise_for_status(self):
            pass

        def iter_content(self, size):
            yield body

    return SimpleNamespace(get=lambda *args, **kwargs: Reply())


def excel(rows):
    buffer = BytesIO()
    pd.DataFrame(rows).to_excel(buffer, index=False, header=False)
    return buffer.getvalue()


def test_tpex_scope_and_schema():
    raw = json.dumps([{'公司代號':'6488', '公司名稱':'Issuer'}, {'公司代號':'6488', '公司名稱':'Issuer'}]).encode()
    rows, detail = fetch_listing('TPEX', response(raw))
    assert [row['ticker'] for row in rows] == ['6488.TWO']
    assert detail['duplicate_rows'] == 1 and len(detail['source_sha256']) == 64
    with pytest.raises(ListingError, match='code and name'):
        fetch_listing('TPEX', response(b'[{"ticker":"6488"}]'))


def test_hkex_excludes_other_instruments_and_preserves_counters():
    body = excel([
        ['Head', '', '', ''],
        ['Stock Code','Name of Securities','Category','Sub-Category'],
        [700,'Issuer HKD','Equity','Equity Securities (Main Board)'],
        [80700,'Issuer RMB','Equity','Equity Securities (Main Board)'],
        [701,'Issuer class B','Equity','Equity Securities (Main Board)'],
        [1234,'REIT','Equity','Real Estate Investment Trusts'],
        [12345,'Warrant','Derivative Warrants','Equity Warrants'],
        [2800,'ETF','Exchange Traded Products','ETF'],
    ])
    rows, detail = fetch_listing('HKEX', response(body))
    assert [row['ticker'] for row in rows] == ['0700.HK', '80700.HK', '0701.HK']
    assert detail['rejected_non_equity'] == 3
    assert json.loads(detail['excluded_by_category']) == {
        'Equity / Real Estate Investment Trusts': 1,
        'Derivative Warrants / Equity Warrants': 1,
        'Exchange Traded Products / ETF': 1,
    }


def test_szse_and_failure_categories():
    rows, _ = fetch_listing('SZSE', response(excel([['A股代码', 'A股简称'], [1, 'Issuer']])))
    assert rows[0]['ticker'] == '000001.SZ'
    with pytest.raises(ListingError, match='headers'):
        fetch_listing('SZSE', response(excel([['B股代码', 'B股简称'], [1, 'Issuer']])))
    with pytest.raises(ListingError, match='Different company'):
        parse_records('HKEX', [(700,'A',True), ('00700','B',True)])
    assert failure_code(requests.exceptions.ProxyError('CONNECT 403')) == 'PROXY_FORBIDDEN'
    assert failure_code(requests.exceptions.ConnectionError('Connection reset by peer')) == 'CONNECTION_RESET'
    assert failure_code(requests.exceptions.Timeout()) == 'TIMEOUT'


def test_krx_rejects_truncated_page():
    payload = {'response': {'header': {'resultCode': '00'}, 'body': {'totalCount': 2,
        'items': {'item': [{'srtnCd':'005930', 'itmsNm':'Issuer', 'mrktCtg':'KOSPI'}]}}}}
    session = SimpleNamespace(get=lambda *args, **kwargs: SimpleNamespace(ok=True, json=lambda: payload))
    with pytest.raises(ValueError, match='INCOMPLETE_PAGINATION'):
        source_krx_list('fixture', '20261117', session)


def test_matching_count_cannot_establish_completeness():
    universe = pd.DataFrame([dict(ticker='6488.TWO', market='Taiwan', listing_source_ids='["live_TPEX"]')])
    logs = pd.DataFrame([dict(source='live_TPEX', status='OK', source_asof='2026-11-18')])
    benchmark = pd.DataFrame([dict(venue='TPEX', source_id='live_TPEX', count=1,
        as_of='2026-11-18', url='https://www.tpex.org.tw/', scope_comparable=True)])
    row = review_venues(universe, logs, benchmark).set_index('venue').loc['TPEX']
    assert row.same_scope_count_delta == 0 and row.product_status == 'UNRESOLVED_SCOPE_VERIFICATION'


def test_lifecycle_keeps_original_decision_and_score():
    baseline = dict(v031_research_eligible=False, cross_industry_score_100=55, score_coverage=.9,
                    operating_margin=-.01, roe=.01, v031_research_status='REVIEW_REQUIRED',
                    fetch_error='', data_quality_flags='', peer_group='industry')
    ranked = pd.DataFrame([baseline, dict(baseline, fetch_error='timeout'),
                           dict(baseline, v031_research_eligible=True)])
    audit = candidate_review(ranked)
    assert audit.lifecycle.tolist() == ['FUNDAMENTAL_SCREEN_FAILURE','RECOVERABLE_EXCLUSION','RESEARCH_ELIGIBLE']
    pd.testing.assert_frame_equal(audit[ranked.columns], ranked)


def test_tpex_openapi_english_fields_are_company_rows_with_provenance():
    raw = json.dumps([
        {'SecuritiesCompanyCode': '6488', 'CompanyName': 'GlobalWafers Co., Ltd.',
         'CompanyAbbreviation': 'GlobalWafers', 'SecuritiesIndustryCode': '24'},
        {'SecuritiesCompanyCode': '006201', 'CompanyName': 'Test fund',
         'CompanyAbbreviation': 'Fund', 'SecuritiesIndustryCode': ''},
        {'SecuritiesCompanyCode': '1234', 'CompanyName': None, 'CompanyAbbreviation': None},
    ]).encode()
    rows, detail = fetch_listing('TPEX', response(raw))
    assert len(rows) == 1
    row = rows[0]
    assert (row['ticker'], row['company']) == ('6488.TWO', 'GlobalWafers Co., Ltd.')
    assert row['security_type_status'] == 'OFFICIAL_ISSUER_LIST_TYPE_CHECK_VENDOR'
    assert row['discovery_source'] == detail['source_url']
    assert detail['rejected_bad_symbol'] == 2
    from hashlib import sha256
    assert detail['source_sha256'] == sha256(raw).hexdigest()


def test_tpex_schema_error_exposes_keys_not_values():
    with pytest.raises(ListingError, match='observed keys: changed_field') as exc:
        fetch_listing('TPEX', response(b'[{"changed_field":"do-not-log"}]'))
    assert 'do-not-log' not in str(exc.value)


@pytest.mark.parametrize(('venue', 'code', 'suffix'), [
    ('KIND_KOSPI', '5930', '005930.KS'), ('KIND_KOSDAQ', '247540', '247540.KQ'),
])
def test_kind_download_keeps_market_suffix_and_unverified_type(venue, code, suffix):
    raw = (f'<meta charset="utf-8"><table><tr><th>회사명</th><th>종목코드</th></tr>'
           f'<tr><td>Issuer</td><td>{code}</td></tr></table>').encode()
    rows, info = fetch_listing(venue, response(raw))
    assert rows[0]['ticker'] == suffix
    assert rows[0]['security_type_status'] == 'OFFICIAL_ISSUER_LIST_TYPE_CHECK_VENDOR'
    assert 'kind.krx.co.kr' in info['source_url']
    with pytest.raises(ListingError, match='KIND'):
        fetch_listing(venue, response(b'<html>Unknown layout</html>'))


@pytest.mark.parametrize(('venue', 'payload', 'ticker'), [
    ('SSE', {'pageHelp': {'pageCount': 1, 'total': 1,
        'data': [{'A_STOCK_CODE': '600000', 'COMPANY_ABBR': 'Fixture'}]}}, '600000.SS'),
    ('SSE_STAR', {'pageHelp': {'pageCount': 1, 'total': 1,
        'data': [{'A_STOCK_CODE': '688001', 'COMPANY_ABBR': 'Fixture'}]}}, '688001.SS'),
    ('SZSE_JSON', [{'metadata': {'pagecount': 1, 'recordcount': 1},
        'data': [{'agdm': '000001', 'agjc': 'Fixture'}]}], '000001.SZ'),
    ('BSE', [{'totalPages': 1, 'totalElements': 1,
        'content': [{'xxzqdm': '920001', 'xxzqjc': 'Fixture'}]}], '920001.BJ'),
])
def test_paginated_exchange_payloads(venue, payload, ticker):
    raw = json.dumps(payload).encode()
    if venue == 'BSE':
        raw = b'callback(' + raw + b');'
    session = response(raw)
    session.post = session.get
    rows, detail = fetch_listing(venue, session)
    assert rows[0]['ticker'] == ticker and detail['received'] == 1


def test_incomplete_sse_pagination_never_returns_partial_result(monkeypatch):
    monkeypatch.setattr('src.regional_listings.time.sleep', lambda _: None)
    payload = {'pageHelp': {'pageCount': 2, 'total': 2,
        'data': [{'A_STOCK_CODE': '600000', 'COMPANY_ABBR': 'Fixture'}]}}
    with pytest.raises(ListingError) as exc:
        fetch_listing('SSE', response(json.dumps(payload).encode()))
    assert exc.value.code == 'INCOMPLETE_PAGINATION'


def test_dart_crosschecks_but_never_creates_listings(monkeypatch):
    from src import discovery_v031 as discovery

    monkeypatch.delenv('PUBLIC_DATA_API_KEY', raising=False)
    monkeypatch.setenv('DART_API_KEY', 'test')
    monkeypatch.setattr(discovery, 'dart_stock_code_map', lambda key: {
        '005930': {'corp_code':'00000001', 'corp_name':'Existing'},
        '999999': {'corp_code':'00000002', 'corp_name':'DART-only'},
    })
    monkeypatch.setattr(discovery, 'source_nikkei225', lambda: [])
    monkeypatch.setattr(discovery, 'source_jpx_list', lambda: [])
    monkeypatch.setattr(discovery, 'source_twse_list', lambda: [])
    monkeypatch.setattr(discovery, 'fetch_listing', lambda venue: ([], {}))
    frame, log = discovery.discover_five_markets(pd.DataFrame([
        dict(ticker='005930.KS', market='Korea')]), 'all5_official', 0)
    assert frame.ticker.tolist() == ['005930.KS']
    assert frame.dart_corp_code.tolist() == ['00000001']
    assert json.loads(frame.listing_source_ids.iloc[0]) == ['CURATED_LIST']
    assert log.set_index('source').loc['opendart_issuer_crosscheck', 'identity_matches'] == 1


def test_kind_live_count_is_independent_of_krx_api_status():
    universe = pd.DataFrame([dict(ticker='005930.KS', market='Korea',
                                  listing_source_ids='["live_KIND_KOSPI"]')])
    logs = pd.DataFrame([dict(source='live_KIND_KOSPI', status='OK'),
                         dict(source='official_krx_listed_issues', status='NOT_CONFIGURED_AUTH_REQUIRED')])
    row = review_venues(universe, logs).set_index('venue').loc['KRX_KOSPI']
    assert row.live_supported_n == 1 and row.successful_live_sources == 'live_KIND_KOSPI'
    assert row.product_status == 'UNRESOLVED_SCOPE_VERIFICATION'


@pytest.mark.parametrize(('failure', 'expected'), [
    (requests.ConnectionError('Connection reset by peer'), True),
    (requests.exceptions.ProxyError('CONNECT 403'), False),
])
def test_szse_json_route_respects_workbook_access_denial(monkeypatch, failure, expected):
    from src import discovery_v031 as discovery

    for name in ('source_nikkei225', 'source_jpx_list', 'source_twse_list'):
        monkeypatch.setattr(discovery, name, lambda: [])
    for key in ('PUBLIC_DATA_API_KEY', 'DART_API_KEY', 'GARP_LISTING_EXPORT_DIR'):
        monkeypatch.delenv(key, raising=False)
    calls = []

    def fetch(venue):
        calls.append(venue)
        if venue == 'SZSE':
            raise failure
        return [], {}

    monkeypatch.setattr(discovery, 'fetch_listing', fetch)
    monkeypatch.setattr(discovery, 'source_region', lambda *args: pytest.fail('Yahoo discovery called'))
    discovery.discover_five_markets(pd.DataFrame([dict(ticker='005930.KS', market='Korea')]),
                                    'all5_official', 0)
    assert ('SZSE_JSON' in calls) is expected


def test_sse_result_container_and_requested_board(monkeypatch):
    monkeypatch.setattr('src.regional_listings.time.sleep', lambda _: None)
    calls = []

    def get(url, **kwargs):
        params = kwargs['params']
        calls.append(params)
        page = params['pageHelp.pageNo']
        payload = {'pageHelp': {'pageCount': '2', 'total': '2', 'pageNo': page,
                                'pageSize': 1},
                   'result': [{'A_STOCK_CODE': f'68800{page}', 'COMPANY_ABBR': 'Fixture'}]}
        return response(json.dumps(payload).encode()).get()

    rows, metadata = fetch_listing('SSE_STAR', SimpleNamespace(get=get))
    assert [row['ticker'] for row in rows] == ['688001.SS', '688002.SS']
    assert calls[0]['STOCK_TYPE'] == '8' and 'stockType' not in calls[0]
    assert calls[0]['COMPANY_STATUS'] == '2,4,5,7,8'
    assert calls[0]['type'] == 'inParams' and calls[0]['pageHelp.cacheSize'] == 1
    assert metadata['response_diagnostics']['first']['row_container'] == 'result'
    assert metadata['response_diagnostics']['last']['reported_page'] == 2


@pytest.mark.parametrize(('meta', 'records', 'reason'), [
    ({'pageCount': 1, 'total': 1, 'pageNo': 2}, [], 'PAGE_NUMBER_MISMATCH'),
    ({'pageCount': 1, 'total': 1}, [], 'EMPTY_PAGE'),
    ({'pageCount': 1, 'total': 2}, [{'A_STOCK_CODE':'600001','COMPANY_ABBR':'Do not log'}],
     'FINAL_COUNT_MISMATCH'),
    ({}, [], 'INVALID_TOTALS'),
])
def test_sse_errors_log_only_safe_metadata(meta, records, reason):
    raw = json.dumps({'pageHelp': meta, 'result': records, 'unknown_secret': 'private value'}).encode()
    with pytest.raises(ListingError) as exc:
        fetch_listing('SSE', response(raw))
    assert exc.value.code == 'INCOMPLETE_PAGINATION'
    assert exc.value.diagnostics['reason'] == reason
    assert exc.value.diagnostics['requested_page'] == 1
    assert exc.value.diagnostics['returned_rows'] == len(records)
    diagnostics = json.dumps(exc.value.diagnostics)
    assert 'Do not log' not in diagnostics and 'private value' not in diagnostics and 'unknown_secret' not in diagnostics
