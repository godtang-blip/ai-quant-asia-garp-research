"""Validate authorized, dated Tushare Pro stock_basic exports."""
import csv
from datetime import date, datetime
from hashlib import sha256
from io import StringIO
import json
from time import monotonic
import re
from zoneinfo import ZoneInfo

from .official_universe import _market_row
from .venue_sources import ListingError

SOURCE = 'https://tushare.pro/document/2?doc_id=25'
API = 'https://api.tushare.pro'
LIVE_SOURCE_IDS = {'SZSE': 'tushare_SZSE_api', 'BSE': 'tushare_BSE_api'}
SOURCE_IDS = {'SZSE': 'tushare_SZSE_snapshot', 'BSE': 'tushare_BSE_snapshot'}
REQUIRED = {'as_of', 'ts_code', 'symbol', 'name', 'exchange', 'market',
            'list_status', 'list_date', 'delist_date'}
MARKETS = {
    'SZSE': {'主板': ('SZSE_MAIN', r'(?:000|001|002|003)\d{3}'),
             '创业板': ('SZSE_CHINEXT', r'(?:300|301)\d{3}')},
    'BSE': {'北交所': ('BSE', r'(?:4\d|8\d|92)\d{4}')},
}


def load_tushare_export(path, venue, today=None):
    with path.open('rb') as stream:
        raw = stream.read(8_000_001)
    return parse_tushare_export(raw, venue, today)


def parse_tushare_export(raw, venue, today=None):
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if len(raw) > 8_000_000:
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Tushare snapshot exceeds import limit')
    reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')), strict=True)
    if not REQUIRED.issubset(reader.fieldnames or ()) or len(set(reader.fieldnames)) != len(reader.fieldnames):
        raise ListingError('SCHEMA_DRIFT', 'Tushare snapshot is missing required columns')
    rows, dates, seen = [], set(), set()
    counts = {label: 0 for label, _ in MARKETS[venue].values()}
    excluded = inactive = unknown = received = 0
    suffix = '.SZ' if venue == 'SZSE' else '.BJ'
    for row in reader:
        received += 1
        if None in row or any(value is None for value in row.values()):
            raise ListingError('SCHEMA_DRIFT', 'Tushare snapshot has malformed CSV rows')
        fields = {key: row[key].strip() for key in REQUIRED}
        as_of = date.fromisoformat(fields['as_of'])
        dates.add(as_of)
        if not 0 <= (today - as_of).days <= 7:
            raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Tushare snapshot exceeds seven-day freshness window')
        if fields['exchange'] != venue:
            raise ListingError('SOURCE_CONFLICT', 'Tushare snapshot contains a different exchange')
        code = fields['symbol']
        if fields['ts_code'] != code + suffix or not re.fullmatch(r'[0-9]{6}', code):
            raise ListingError('SOURCE_CONFLICT', 'Tushare symbol and exchange suffix do not agree')
        if code in seen:
            raise ListingError('SOURCE_CONFLICT', 'Tushare snapshot contains duplicate security codes')
        seen.add(code)
        if fields['list_status'] in {'D', 'P'} or fields['delist_date']:
            inactive += 1
            continue
        board = MARKETS[venue].get(fields['market'])
        if fields['list_status'] != 'L' or board is None or not fields['name']:
            unknown += 1
            continue
        label, pattern = board
        if not re.fullmatch(pattern, code):
            excluded += 1
            continue
        listed = fields['list_date']
        if not re.fullmatch(r'[0-9]{8}', listed) or date.fromisoformat(listed) > as_of:
            unknown += 1
            continue
        record = _market_row(code + suffix, fields['name'], 'China', SOURCE)
        record['security_type_status'] = 'THIRD_PARTY_EQUITY_REQUIRES_VENDOR_CONFIRMATION'
        rows.append(record)
        counts[label] += 1
    if len(dates) != 1 or not all(counts.values()):
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Tushare snapshot lacks a coherent date or requested board')
    return rows, dict(received=received, rejected_non_equity=excluded,
                      unknown_classification=unknown, inactive_or_after_cutoff=inactive, source_asof=dates.pop().isoformat(),
                      scope=', '.join(counts), scope_counts=json.dumps(counts), source_url=SOURCE,
                      source_sha256=sha256(raw).hexdigest(), retrieval_mode='IMPORTED_VENDOR_SNAPSHOT',
                      completeness_check='DATE_EXCHANGE_AND_BOARD_CHECKS; PROVIDER_TOTAL_UNVERIFIED')


def fetch_tushare_api(venue, token, session=None):
    """Opt-in, entitled HTTPS access. Never include response text in exceptions."""
    import requests

    session = session or requests
    fields = sorted(REQUIRED - {'as_of'})
    try:
        with session.post(API, json={'api_name': 'stock_basic', 'token': token,
                                    'params': {'exchange': venue, 'list_status': 'L'},
                                    'fields': ','.join(fields)},
                          timeout=(5, 12), allow_redirects=False, stream=True) as response:
            if response.status_code != 200:
                code = {401: 'AUTHENTICATION_FAILED', 403: 'FORBIDDEN',
                        429: 'RATE_LIMITED'}.get(response.status_code, 'HTTP_FAILURE')
                raise ListingError(code, f'Tushare HTTPS status {response.status_code}')
            started = monotonic()
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                raw.extend(chunk)
                if len(raw) > 8_000_000:
                    raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Tushare response exceeds byte limit')
                if monotonic() - started > 18:
                    raise ListingError('TIMEOUT', 'Tushare body read deadline exceeded')
    except requests.exceptions.Timeout:
        raise ListingError('TIMEOUT', 'Tushare HTTPS request timed out') from None
    except requests.exceptions.ProxyError:
        raise ListingError('PROXY_FORBIDDEN', 'Tushare HTTPS proxy connection failed') from None
    except requests.exceptions.RequestException:
        raise ListingError('SOURCE_UNAVAILABLE', 'Tushare HTTPS connection failed') from None

    try:
        body = json.loads(raw)
        if body['code'] != 0:
            # Provider messages are untrusted and can echo request parameters.
            raise ListingError('PROVIDER_REQUEST_REJECTED', 'Tushare rejected stock_basic; check token and entitlement')
        data = body['data']
        headers, items = data['fields'], data['items']
        if (not isinstance(headers, list) or len(headers) != len(set(headers))
                or not set(fields).issubset(headers) or not isinstance(items, list)):
            raise ValueError
        # No provider total is available. A result touching the advertised ceiling is unsafe.
        if not items or len(items) >= 6000:
            raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Tushare result is empty or reaches the stock_basic row ceiling')
        today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
        buffer = StringIO()
        writer = csv.DictWriter(buffer, ['as_of', *fields])
        writer.writeheader()
        for item in items:
            if not isinstance(item, list) or len(item) != len(headers) or any(
                    val is not None and not isinstance(val, str) for val in item):
                raise ValueError
            row = dict(zip(headers, item))
            writer.writerow({'as_of': str(today), **{key: row[key] for key in fields}})
        rows, details = parse_tushare_export(buffer.getvalue().encode(), venue, today)
    except ListingError:
        raise
    except (KeyError, TypeError, ValueError):
        raise ListingError('SCHEMA_DRIFT', 'Tushare stock_basic response schema is invalid') from None
    details.update(source_url=API, source_asof='', source_sha256=sha256(raw).hexdigest(),
                   retrieval_mode='LIVE_VENDOR_API',
                   completeness_check='BOARDS_AND_ROW_CEILING_CHECKED; PROVIDER_DATE_AND_TOTAL_UNVERIFIED')
    return rows, details
