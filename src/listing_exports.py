"""Validate normalized, dated publisher exports without treating them as verified filings."""
from __future__ import annotations

import csv
import datetime as dt
from hashlib import sha256
from io import StringIO
from pathlib import Path
import re
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from .official_universe import JPX_CODE, _market_row

# Keep venue identifiers separate from Yahoo ticker suffixes and issuer identities.
VENUES = {
    'KRX_KOSPI': ('Korea', 'krx.co.kr', r'\d{6}', '.KS'),
    'KRX_KOSDAQ': ('Korea', 'krx.co.kr', r'\d{6}', '.KQ'),
    'JPX': ('Japan', 'jpx.co.jp', JPX_CODE, '.T'),
    'SSE': ('China', 'sse.com.cn', r'\d{6}', '.SS'),
    'SZSE': ('China', 'szse.cn', r'\d{6}', '.SZ'),
    'BSE': ('China', 'bse.cn', r'\d{6}', '.BJ'),
    'HKEX': ('Hong Kong', 'hkex.com.hk', r'\d{1,5}', '.HK'),
    'TWSE': ('Taiwan', 'twse.com.tw', r'\d{4}', '.TW'),
    'TPEX': ('Taiwan', 'tpex.org.tw', r'\d{4}', '.TWO'),
}
FIELDS = {'code', 'company', 'security_type', 'as_of', 'source_url'}
NON_COMMON_TYPES = {'PREFERRED', 'ETF', 'ETN', 'REIT', 'FUND', 'WARRANT', 'BOND', 'OTHER'}


def load_listing_export(path: Path, venue: str, today: dt.date | None = None):
    market, publisher, pattern, suffix = VENUES[venue]
    day_zone = ZoneInfo('Asia/Shanghai') if venue in {'SZSE', 'BSE'} else dt.timezone.utc
    today = today or dt.datetime.now(day_zone).date()
    raw = path.read_bytes()
    reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')), strict=True)
    if set(reader.fieldnames or ()) != FIELDS or len(reader.fieldnames) != len(FIELDS):
        raise ValueError('Expected CSV columns: ' + ', '.join(sorted(FIELDS)))

    listings = {}
    origins = set()
    excluded = 0
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError(f'Line {reader.line_num}: malformed CSV record')
        code, company, kind, as_of, url = (row[key].strip() for key in
                                          ('code', 'company', 'security_type', 'as_of', 'source_url'))
        parsed = urlsplit(url)
        host = parsed.hostname or ''
        if (parsed.scheme != 'https' or parsed.username is not None or
                not (host == publisher or host.endswith('.' + publisher))):
            raise ValueError(f'Line {reader.line_num}: unexpected publisher URL')
        day = dt.date.fromisoformat(as_of)
        if not 0 <= (today - day).days <= 45:
            raise ValueError(f'Line {reader.line_num}: export date is future or over 45 days old')
        origins.add((as_of, url))
        if kind in NON_COMMON_TYPES:
            excluded += 1
            continue
        if kind != 'COMMON_EQUITY' or not re.fullmatch(pattern, code) or not company:
            raise ValueError(f'Line {reader.line_num}: invalid security type, code or company')
        if venue == 'HKEX':
            code = code.lstrip('0').zfill(4)
        ticker = code + suffix
        if ticker in listings:
            raise ValueError(f'Line {reader.line_num}: duplicate security code')
        listings[ticker] = _market_row(ticker, company, market, url)

    if not listings or len(origins) != 1:
        raise ValueError('Export must contain common equity and a single source URL and date')
    as_of, url = origins.pop()
    return list(listings.values()), {
        'received': len(listings) + excluded,
        'rejected_non_equity': excluded,
        'source_url': url,
        'source_asof': as_of,
        'source_sha256': sha256(raw).hexdigest(),
    }
