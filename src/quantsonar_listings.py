"""Opt-in QuantSonar stock reference source with conservative schema validation."""
from datetime import date, datetime
from hashlib import sha256
import json
import re
from time import monotonic
from zoneinfo import ZoneInfo

import requests

from .china_vendor_exports import MARKETS
from .official_universe import _market_row
from .venue_sources import ListingError

URL = 'https://quantsonar.com/v1/reference/stocks'
SOURCE_IDS = {'SZSE': 'quantsonar_SZSE', 'BSE': 'quantsonar_BSE'}


FIELDS = {'symbol', 'name', 'market', 'list_status', 'exchange', 'ts_code',
          'security_type', 'list_date', 'delist_date'}
ENVELOPE_FIELDS = {'data', 'items', 'total', 'as_of', 'code', 'message', 'success'}
TICKER = re.compile(r'([0-9]{6})(\.[A-Z]{2})')
MARKET_LABELS = {
    '主板': '主板', 'main board': '主板',
    '创业板': '创业板', 'chinext': '创业板',
    '北交所': '北交所', 'beijing stock exchange': '北交所',
    '科创板': '科创板', 'star market': '科创板',
}


def text(value):
    return value.strip() if isinstance(value, str) else ''


def response_shape(payload, items, venue):
    from collections import Counter

    keys = set().union(*(row.keys() for row in items if isinstance(row, dict)))
    top = set(payload) if isinstance(payload, dict) else set()
    suffix = '.SZ' if venue == 'SZSE' else '.BJ'
    formats, markets, statuses, invalid = Counter(), Counter(), Counter(), Counter()
    for row in items:
        if not isinstance(row, dict):
            invalid['record'] += 1
            continue
        symbol = text(row.get('symbol'))
        board = MARKET_LABELS.get(text(row.get('market')).casefold())
        status = text(row.get('list_status'))
        exchange = text(row.get('exchange')).upper()
        formats['suffixed' if TICKER.fullmatch(symbol) else
                'bare' if re.fullmatch(r'[0-9]{6}', symbol) else 'invalid'] += 1
        markets[board or ('OTHER' if row.get('market') else 'MISSING')] += 1
        statuses[status if status in {'L', 'D', 'P'} else ('OTHER' if status else 'MISSING')] += 1
        for field, valid in {
            'symbol': bool(TICKER.fullmatch(symbol)) and symbol.endswith(suffix),
            'name': bool(text(row.get('name'))),
            'market': board in MARKETS[venue],
            'list_status': status == 'L',
            'exchange': exchange in ({'SZSE', 'SZ'} if venue == 'SZSE' else {'', 'BSE', 'BJ'}),
            'ts_code': 'ts_code' not in row or row['ts_code'] == symbol,
            'security_type': row.get('security_type') in (None, 'EQUITY', 'COMMON_EQUITY'),
            'delist_date': not row.get('delist_date'),
        }.items():
            invalid[field] += int(not valid)
    return dict(top_level_fields=sorted(top & ENVELOPE_FIELDS), other_top_level_fields=len(top - ENVELOPE_FIELDS),
                item_fields=sorted(keys & FIELDS), other_item_fields=len(keys - FIELDS), returned_rows=len(items),
                symbol_formats=dict(formats), market_counts=dict(markets), listing_status_counts=dict(statuses),
                invalid_counts=dict(invalid),
                null_or_missing_counts={key: sum(not isinstance(row, dict) or row.get(key) in (None, '')
                                                 for row in items) for key in sorted(FIELDS)})


def parse_reference(raw, venue, today=None):
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    stage = 'JSON'
    shape = {}
    try:
        payload = json.loads(raw)
        stage = 'ENVELOPE'
        envelope = payload if isinstance(payload, dict) else {}
        items = envelope.get('data', payload)
        metadata = items if isinstance(items, dict) else {}
        items = metadata.get('items', items)
        shape = response_shape(payload, items if isinstance(items, list) else [], venue)
        if not isinstance(items, list):
            raise ValueError
        stage = 'PROVIDER_TOTAL_OR_DATE'
        total = metadata.get('total', envelope.get('total'))
        as_of = metadata.get('as_of', envelope.get('as_of'))
        if as_of is not None:
            as_of = date.fromisoformat(as_of)
            if not 0 <= (today - as_of).days <= 7:
                raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'QuantSonar reported an invalid effective date')
        if (not items or len(items) >= 6000 or
                (total is not None and (type(total) is not int or total != len(items)))):
            raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Empty response, row ceiling reached, or total mismatch')
        suffix = '.SZ' if venue == 'SZSE' else '.BJ'
        counts = dict.fromkeys((label for label, _ in MARKETS[venue].values()), 0)
        rows, seen, excluded = [], set(), 0
        for item in items:
            stage = 'RECORD_FIELDS'
            symbol, name, board, status = (item[key] for key in ('symbol', 'name', 'market', 'list_status'))
            stage = 'SYMBOL_SUFFIX'
            match = TICKER.fullmatch(text(symbol))
            if not match or match[2] != suffix:
                raise ListingError('SOURCE_CONFLICT', 'Expected the requested exchange suffix in QuantSonar symbol')
            code = match[1]
            stage = 'COMPANY_NAME'
            if not text(name):
                raise ListingError('SOURCE_CONFLICT', 'Missing QuantSonar company name')
            stage = 'LISTING_STATUS'
            if status != 'L' or item.get('delist_date'):
                raise ListingError('SOURCE_CONFLICT', 'QuantSonar row does not assert active listing')
            stage = 'DUPLICATE_IDENTIFIER'
            if code in seen:
                raise ListingError('SOURCE_CONFLICT', 'Duplicate QuantSonar security identifier')
            seen.add(code)
            stage = 'EXCHANGE_MEMBERSHIP'
            exchange = item.get('exchange')
            if exchange is not None and not isinstance(exchange, str):
                raise ValueError
            if text(exchange).upper() not in ({'SZSE', 'SZ'} if venue == 'SZSE' else {'', 'BSE', 'BJ'}):
                raise ListingError('SOURCE_CONFLICT', 'QuantSonar exchange field conflicts with requested scope')
            if 'ts_code' in item and item['ts_code'] != symbol:
                raise ListingError('SOURCE_CONFLICT', 'QuantSonar suffixed identifier does not match requested scope')
            stage = 'BOARD_CLASSIFICATION'
            board = MARKET_LABELS.get(text(board).casefold())
            if board not in MARKETS[venue]:
                raise ListingError('SOURCE_CONFLICT', 'QuantSonar board does not match requested scope')
            label, pattern = MARKETS[venue][board]
            kind = item.get('security_type')
            if not re.fullmatch(pattern, code) or (kind is not None and kind not in {'EQUITY', 'COMMON_EQUITY'}):
                excluded += 1
                continue
            row = _market_row(symbol.strip(), name.strip(), 'China', URL)
            row['security_type_status'] = 'THIRD_PARTY_EQUITY_REQUIRES_VENDOR_CONFIRMATION'
            rows.append(row)
            counts[label] += 1
        stage = 'REQUIRED_BOARD_COVERAGE'
        if not all(counts.values()):
            raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'QuantSonar returned no qualifying rows for a required board')
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        failure = exc if isinstance(exc, ListingError) else ListingError(
            'SCHEMA_DRIFT', 'QuantSonar response did not match the guarded reference contract')
        failure.diagnostics = dict(shape, validation_stage=stage)
        raise failure from None
    return rows, dict(received=len(items), rejected_non_equity=excluded,
                      scope=', '.join(counts), scope_counts=json.dumps(counts), source_url=URL,
                      source_asof=str(as_of) if as_of else '', source_sha256=sha256(raw).hexdigest(),
                      retrieval_mode='LIVE_VENDOR_API',
                      completeness_check=('PROVIDER_TOTAL_RECONCILED' if total is not None else
                                          'BELOW_ROW_CEILING; PROVIDER_TOTAL_UNVERIFIED') +
                      ('; PROVIDER_DATE_REPORTED' if as_of else '; PROVIDER_DATE_UNVERIFIED'))


def fetch_quantsonar(venue, key, session=requests):
    params = {'list_status': 'L', **({'exchange': 'SZSE'} if venue == 'SZSE' else {'market': '北交所'})}
    status = None
    try:
        with session.get(URL, params=params, headers={'X-API-Key': key}, timeout=(5, 12),
                         allow_redirects=False, stream=True) as reply:
            status = reply.status_code
            if status != 200:
                code = {401:'AUTHENTICATION_FAILED',403:'FORBIDDEN',429:'RATE_LIMITED'}.get(status,'HTTP_FAILURE')
                raise ListingError(code, f'QuantSonar HTTP {status}')
            raw = bytearray()
            start = monotonic()
            for chunk in reply.iter_content(65536):
                raw.extend(chunk)
                if len(raw) > 8_000_000 or monotonic() - start > 18:
                    raise ListingError('RESPONSE_LIMIT', 'QuantSonar response exceeded read bounds')
        rows, details = parse_reference(raw, venue)
    except ListingError as exc:
        exc.diagnostics = {'validation_stage': 'HTTP_OR_READ', **getattr(exc, 'diagnostics', {}),
                           'http_status': status}
        raise
    except requests.exceptions.ProxyError:
        raise ListingError('PROXY_FORBIDDEN', 'QuantSonar proxy connection failed') from None
    except requests.exceptions.Timeout:
        raise ListingError('TIMEOUT', 'QuantSonar request timed out') from None
    except requests.exceptions.RequestException:
        raise ListingError('SOURCE_UNAVAILABLE', 'QuantSonar transport failed') from None
    details['response_diagnostics'] = {'http_status': status, 'listing_status': 'L_ON_EACH_ACCEPTED_ROW'}
    return rows, details
