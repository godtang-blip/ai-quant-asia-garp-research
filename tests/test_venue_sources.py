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
        [2800,'ETF','Exchange Traded Products','ETF'],
    ])
    rows, detail = fetch_listing('HKEX', response(body))
    assert [row['ticker'] for row in rows] == ['0700.HK', '80700.HK']
    assert detail['rejected_non_equity'] == 1


def test_szse_and_failure_categories():
    rows, _ = fetch_listing('SZSE', response(excel([['A股代码', 'A股简称'], [1, 'Issuer']])))
    assert rows[0]['ticker'] == '000001.SZ'
    with pytest.raises(ListingError, match='headers'):
        fetch_listing('SZSE', response(excel([['B股代码', 'B股简称'], [1, 'Issuer']])))
    with pytest.raises(ListingError, match='Different company'):
        parse_records('HKEX', [(700,'A',True), ('00700','B',True)])
    assert failure_code(requests.exceptions.ProxyError('CONNECT 403')) == 'PROXY_FORBIDDEN'
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
