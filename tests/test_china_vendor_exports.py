from datetime import date

import pytest

from src.china_vendor_exports import load_tushare_export
from src.venue_sources import ListingError


HEADER = 'as_of,ts_code,symbol,name,exchange,market,list_status,list_date,delist_date\n'
AS_OF = date(2026, 11, 18)


def test_shenzhen_requires_both_boards_and_preserves_exchange(tmp_path):
    path = tmp_path/'SZSE.csv'
    path.write_text(HEADER +
        '2026-11-18,000001.SZ,000001,Main,SZSE,主板,L,19910403,\n' +
        '2026-11-18,300001.SZ,300001,ChiNext,SZSE,创业板,L,20091030,\n', encoding='utf-8')
    rows, meta = load_tushare_export(path, 'SZSE', AS_OF)
    assert [row['ticker'] for row in rows] == ['000001.SZ', '300001.SZ']
    assert meta['retrieval_mode'] == 'IMPORTED_VENDOR_SNAPSHOT'
    assert all(row['security_type_status'] == 'THIRD_PARTY_EQUITY_REQUIRES_VENDOR_CONFIRMATION' for row in rows)
    path.write_text(HEADER + path.read_text().splitlines()[1] + '\n', encoding='utf-8')
    with pytest.raises(ListingError, match='requested board'):
        load_tushare_export(path, 'SZSE', AS_OF)


def test_beijing_filters_neeq_only_and_delisted_rows(tmp_path):
    path = tmp_path/'BSE.csv'
    path.write_text(HEADER +
        '2026-11-18,920001.BJ,920001,Listed,BSE,北交所,L,20220101,\n' +
        '2026-11-18,830002.BJ,830002,NEEQ,BSE,新三板,L,20200101,\n' +
        '2026-11-18,920003.BJ,920003,Delisted,BSE,北交所,D,20220101,20261031\n', encoding='utf-8')
    rows, meta = load_tushare_export(path, 'BSE', AS_OF)
    assert [row['ticker'] for row in rows] == ['920001.BJ']
    assert meta['unknown_classification'] == meta['inactive_or_after_cutoff'] == 1


@pytest.mark.parametrize(('row', 'reason'), [
    ('2026-11-01,920001.BJ,920001,Old,BSE,北交所,L,20200101,', 'freshness'),
    ('2026-11-18,920001.BJ,920001,Wrong,SZSE,北交所,L,20200101,', 'different exchange'),
    ('2026-11-18,920001.SZ,920001,Wrong,BSE,北交所,L,20200101,', 'suffix'),
])
def test_rejects_stale_or_mixed_exchange_snapshot(tmp_path, row, reason):
    path = tmp_path/'BSE.csv'
    path.write_text(HEADER + row + '\n', encoding='utf-8')
    with pytest.raises(ListingError, match=reason):
        load_tushare_export(path, 'BSE', AS_OF)


@pytest.mark.parametrize(('venue', 'rows', 'expected'), [
    ('SZSE', [('000001.SZ','000001','Main','SZSE','主板','L','19910403',None),
              ('300001.SZ','300001','ChiNext','SZSE','创业板','L','20091030',None)],
     ['000001.SZ','300001.SZ']),
    ('BSE', [('920001.BJ','920001','Listed','BSE','北交所','L','20220101',None)],
     ['920001.BJ']),
])
def test_tushare_live_request_uses_fixed_tls_endpoint(venue, rows, expected):
    import json
    from types import SimpleNamespace
    from src.china_vendor_exports import fetch_tushare_api

    class Reply:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def iter_content(self, chunk_size):
            yield json.dumps({'code':0, 'data':{
                'fields':['ts_code','symbol','name','exchange','market','list_status','list_date','delist_date'],
                'items':rows,
            }}).encode()

    def post(url, **kwargs):
        assert url == 'https://api.tushare.pro' and kwargs['allow_redirects'] is False
        assert kwargs['json']['params'] == {'exchange':venue, 'list_status':'L'}
        return Reply()

    found, detail = fetch_tushare_api(venue, 'fixture-only', SimpleNamespace(post=post))
    assert [row['ticker'] for row in found] == expected
    assert detail['retrieval_mode'] == 'LIVE_VENDOR_API'
    assert detail['source_asof'] == '' and 'PROVIDER_DATE_AND_TOTAL_UNVERIFIED' in detail['completeness_check']


def test_tushare_does_not_expose_provider_error_body():
    from types import SimpleNamespace
    from src.china_vendor_exports import fetch_tushare_api

    class Reply:
        status_code = 200

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def iter_content(self, chunk_size):
            yield b'{"code":123,"msg":"sentinel-secret"}'

    with pytest.raises(ListingError, match='check token and entitlement') as exc:
        fetch_tushare_api('BSE', 'sentinel-secret', SimpleNamespace(post=lambda *a, **kw: Reply()))
    assert 'sentinel-secret' not in str(exc.value)
