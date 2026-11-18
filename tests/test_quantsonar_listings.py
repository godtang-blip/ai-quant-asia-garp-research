from datetime import date
import json
from types import SimpleNamespace

import pytest

from src.quantsonar_listings import fetch_quantsonar, parse_reference
from src.venue_sources import ListingError

TODAY = date(2026, 11, 18)
MAIN = dict(symbol='000001.SZ', name='Fixture main', market='主板', list_status='L', exchange='SZSE')
GROWTH = dict(MAIN, symbol='300001.SZ', market='创业板')
BEIJING = dict(symbol='920001.BJ', name='Fixture Beijing', market='北交所', list_status='L')


def load(rows, venue='SZSE', **metadata):
    return parse_reference(json.dumps(dict(data=rows, **metadata)).encode(), venue, TODAY)


def test_required_boards_and_no_synthetic_date():
    rows, detail = load([MAIN, GROWTH, dict(MAIN, symbol='000002.SZ', security_type='ETF')], total=3)
    assert [row['ticker'] for row in rows] == ['000001.SZ', '300001.SZ']
    assert detail['rejected_non_equity'] == 1
    assert detail['source_asof'] == ''
    assert all('REQUIRES_VENDOR_CONFIRMATION' in row['security_type_status'] for row in rows)


def test_bse_preserves_legacy_and_new_codes_without_exchange_assumption():
    rows, _ = load([BEIJING, dict(BEIJING, symbol='830001.BJ', exchange='BSE')], 'BSE')
    assert [row['ticker'] for row in rows] == ['920001.BJ', '830001.BJ']


@pytest.mark.parametrize(('rows','metadata','code'), [
    ([MAIN, GROWTH], {'as_of':'2026-11-01'}, 'INCOMPLETE_OR_STALE_SOURCE'),
    ([MAIN, GROWTH], {'total':3}, 'INCOMPLETE_OR_STALE_SOURCE'),
    ([MAIN], {}, 'INCOMPLETE_OR_STALE_SOURCE'),
    ([MAIN, MAIN], {}, 'SOURCE_CONFLICT'),
    ([MAIN, dict(GROWTH, list_status='D')], {}, 'SOURCE_CONFLICT'),
    ([dict(symbol='000001.SZ')], {}, 'SCHEMA_DRIFT'),
])
def test_rejects_invalid_references(rows, metadata, code):
    with pytest.raises(ListingError) as exc:
        load(rows, **metadata)
    assert exc.value.code == code


def test_provider_error_is_bounded_and_has_no_body_or_key():
    class Response:
        status_code = 403

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

    def get(url, **kwargs):
        assert kwargs['headers'] == {'X-API-Key': 'fixture-secret'}
        assert kwargs['params'] == {'list_status':'L','market':'北交所'}
        assert kwargs['allow_redirects'] is False
        return Response()

    with pytest.raises(ListingError, match='HTTP 403') as exc:
        fetch_quantsonar('BSE', 'fixture-secret', SimpleNamespace(get=get))
    assert exc.value.diagnostics == {'http_status':403, 'validation_stage':'HTTP_OR_READ'}
    assert 'fixture-secret' not in str(exc.value)


def test_schema_diagnostics_hide_raw_values_and_identify_suffix_conflict():
    with pytest.raises(ListingError) as exc:
        load([MAIN, dict(GROWTH, symbol='300001.BJ', secret='sentinel-private')])
    d = exc.value.diagnostics
    assert d['validation_stage'] == 'SYMBOL_SUFFIX'
    assert d['symbol_formats'] == {'suffixed': 2}
    assert d['invalid_counts']['symbol'] == 1
    assert d['returned_rows'] == 2 and d['other_item_fields'] == 1
    assert 'sentinel-private' not in str(d) and '300001.BJ' not in str(d)


def test_bare_symbols_remain_unverified():
    with pytest.raises(ListingError) as exc:
        load([dict(MAIN, symbol='000001'), GROWTH])
    assert exc.value.diagnostics['symbol_formats'] == {'bare': 1, 'suffixed': 1}


def test_explicit_board_names_normalize_without_guessing_from_codes():
    rows, _ = load([dict(MAIN, market='Main Board'), dict(GROWTH, market='ChiNext')])
    assert [row['ticker'] for row in rows] == ['000001.SZ','300001.SZ']
