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


def parse_reference(raw, venue, today=None):
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    try:
        payload = json.loads(raw)
        envelope = payload if isinstance(payload, dict) else {}
        items = envelope.get('data', payload)
        metadata = items if isinstance(items, dict) else {}
        items = metadata.get('items', items)
        if not isinstance(items, list):
            raise ValueError
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
            code, name, board, status = (item[key] for key in ('symbol', 'name', 'market', 'list_status'))
            exchange = item.get('exchange')
            if not re.fullmatch(r'[0-9]{6}', code) or not name.strip() or status != 'L':
                raise ListingError('SOURCE_CONFLICT', 'Invalid identifier, name or active listing status')
            if code in seen:
                raise ListingError('SOURCE_CONFLICT', 'Duplicate QuantSonar security identifier')
            seen.add(code)
            if (exchange != 'SZSE' if venue == 'SZSE' else exchange not in {None, '', 'BSE'}):
                raise ListingError('SOURCE_CONFLICT', 'QuantSonar exchange field conflicts with requested scope')
            if 'ts_code' in item and item['ts_code'] != code + suffix:
                raise ListingError('SOURCE_CONFLICT', 'QuantSonar suffixed identifier does not match requested scope')
            if board not in MARKETS[venue]:
                raise ListingError('SOURCE_CONFLICT', 'QuantSonar board does not match requested scope')
            label, pattern = MARKETS[venue][board]
            kind = item.get('security_type')
            if not re.fullmatch(pattern, code) or (kind is not None and kind not in {'EQUITY', 'COMMON_EQUITY'}):
                excluded += 1
                continue
            row = _market_row(code + suffix, name.strip(), 'China', URL)
            row['security_type_status'] = 'THIRD_PARTY_EQUITY_REQUIRES_VENDOR_CONFIRMATION'
            rows.append(row)
            counts[label] += 1
        if not all(counts.values()):
            raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'QuantSonar returned no qualifying rows for a required board')
    except (TypeError, ValueError, KeyError, AttributeError) as exc:
        if isinstance(exc, ListingError):
            raise
        raise ListingError('SCHEMA_DRIFT', 'QuantSonar response did not match the guarded reference contract') from None
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
        exc.diagnostics = {'http_status': status}
        raise
    except requests.exceptions.ProxyError:
        raise ListingError('PROXY_FORBIDDEN', 'QuantSonar proxy connection failed') from None
    except requests.exceptions.Timeout:
        raise ListingError('TIMEOUT', 'QuantSonar request timed out') from None
    except requests.exceptions.RequestException:
        raise ListingError('SOURCE_UNAVAILABLE', 'QuantSonar transport failed') from None
    details['response_diagnostics'] = {'http_status': status, 'listing_status': 'L_ON_EACH_ACCEPTED_ROW'}
    return rows, details
