"""Validate authorized, dated Tushare Pro stock_basic exports."""
import csv
from datetime import date, datetime
from hashlib import sha256
from io import StringIO
import re
from zoneinfo import ZoneInfo

from .official_universe import _market_row
from .venue_sources import ListingError

SOURCE = 'https://tushare.pro/document/2?doc_id=25'
SOURCE_IDS = {'SZSE': 'tushare_SZSE_snapshot', 'BSE': 'tushare_BSE_snapshot'}
REQUIRED = {'as_of', 'ts_code', 'symbol', 'name', 'exchange', 'market',
            'list_status', 'list_date', 'delist_date'}
MARKETS = {
    'SZSE': {'主板': ('SZSE_MAIN', r'(?:000|001|002|003)\d{3}'),
             '创业板': ('SZSE_CHINEXT', r'(?:300|301)\d{3}')},
    'BSE': {'北交所': ('BSE', r'(?:4\d|8\d|92)\d{4}')},
}


def load_tushare_export(path, venue, today=None):
    import json

    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    with path.open('rb') as stream:
        raw = stream.read(8_000_001)
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
