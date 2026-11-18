"""Public listing downloads with explicit instrument scope and source diagnostics."""
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import re

import pandas as pd
import requests

from .official_universe import _market_row

TPEX = 'https://www.tpex.org.tw/openapi/v1/mopsfin_t187ap03_O'
HKEX = 'https://www.hkex.com.hk/eng/services/trading/securities/securitieslists/ListOfSecurities.xlsx'
SZSE = 'https://www.szse.cn/api/report/ShowReport?SHOWTYPE=xlsx&CATALOGID=1110&TABKEY=tab1'
SOURCES = {
    'TPEX': ('Taiwan', TPEX, 'TPEx company disclosures; excludes Emerging Stock Board'),
    'HKEX': ('Hong Kong', HKEX, 'HKEX workbook Equity securities classified as Equity Securities (Main Board/GEM); excludes REITs, warrants and funds'),
    'SZSE': ('China', SZSE, 'SZSE A-share listing worksheet; excludes B shares and other instruments'),
}


class ListingError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def parse_records(venue, records):
    market, url, scope = SOURCES[venue]
    seen = {}
    excluded = invalid = duplicates = 0
    for code, name, equity in records:
        if not equity:
            excluded += 1
            continue
        code, name = str(code).strip().removesuffix('.0'), str(name).strip()
        if venue == 'HKEX' and re.fullmatch(r'[0-9]{1,5}', code):
            code = code.lstrip('0').zfill(4)
        if venue == 'SZSE' and re.fullmatch(r'[0-9]{1,6}', code):
            code = code.zfill(6)
        pattern, suffix = {'HKEX': (r'[0-9]{4,5}', '.HK'), 'SZSE': (r'[0-9]{6}', '.SZ'),
                           'TPEX': (r'[0-9]{4}', '.TWO')}[venue]
        if not re.fullmatch(pattern, code) or not int(code) or not name:
            invalid += 1
            continue
        ticker = code + suffix
        if ticker in seen:
            if seen[ticker]['company'] != name:
                raise ListingError('SOURCE_CONFLICT', 'Different company names for one security code')
            duplicates += 1
            continue
        seen[ticker] = _market_row(ticker, name, market, url)
    if not seen:
        raise ListingError('SCHEMA_DRIFT', 'No valid securities within the configured instrument scope')
    return list(seen.values()), dict(received=len(seen)+excluded+invalid+duplicates,
        rejected_non_equity=excluded, rejected_bad_symbol=invalid, duplicate_rows=duplicates,
        source_url=url, scope=scope)


def workbook_records(raw, fields, header_limit=15):
    try:
        sheet = pd.read_excel(BytesIO(raw), header=None, dtype=str, keep_default_na=False, engine='openpyxl')
    except Exception as exc:
        raise ListingError('PARSER_FAILURE', 'Publisher response is not a readable XLSX workbook') from exc
    for index, row in enumerate(sheet.head(header_limit).itertuples(index=False, name=None)):
        headers = [' '.join(value.split()) for value in row]
        if all(headers.count(field) == 1 for field in fields):
            columns = [headers.index(field) for field in fields]
            return sheet.iloc[index+1:, columns].itertuples(index=False, name=None)
    raise ListingError('SCHEMA_DRIFT', 'Expected listing worksheet headers absent')


def fetch_listing(venue, session=requests):
    _, url, _ = SOURCES[venue]
    with session.get(url, timeout=(8, 25), stream=True) as response:
        response.raise_for_status()
        raw = bytearray()
        for chunk in response.iter_content(65536):
            raw.extend(chunk)
            if len(raw) > 16_000_000:
                raise ListingError('PARSER_FAILURE', 'Listing exceeds 16 MB')
    if venue == 'TPEX':
        import json
        try:
            payload = json.loads(raw)
        except ValueError as exc:
            raise ListingError('PARSER_FAILURE', 'Expected JSON company listing') from exc
        if not isinstance(payload, list) or not all(isinstance(row, dict) and '公司代號' in row and
                                                     '公司名稱' in row for row in payload):
            raise ListingError('SCHEMA_DRIFT', 'Expected TPEx company code and name fields')
        records = ((row['公司代號'], row['公司名稱'], True) for row in payload)
    elif venue == 'SZSE':
        records = ((code, name, True) for code, name in workbook_records(raw, ('A股代码','A股简称')))
    else:
        records = ((code, name, kind.casefold() == 'equity' and
                    subtype.casefold() in {'equity securities (main board)', 'equity securities (gem)'})
                   for code, name, kind, subtype in workbook_records(
                       raw, ('Stock Code', 'Name of Securities', 'Category', 'Sub-Category')))
    rows, detail = parse_records(venue, records)
    detail.update(source_sha256=sha256(raw).hexdigest())
    return rows, detail


def failure_code(exc):
    if str(exc).startswith('INCOMPLETE_PAGINATION'):
        return 'INCOMPLETE_PAGINATION'
    if isinstance(exc, ListingError):
        return exc.code
    if 'Tunnel connection failed: 403' in str(exc) or (
        isinstance(exc, requests.exceptions.ProxyError) and '403' in str(exc)
    ):
        return 'PROXY_FORBIDDEN'
    if isinstance(exc, requests.exceptions.Timeout):
        return 'TIMEOUT'
    if isinstance(exc, requests.exceptions.HTTPError) and exc.response is not None:
        return {401:'AUTHENTICATION_FAILED', 403:'FORBIDDEN', 404:'UNAVAILABLE',
                429:'RATE_LIMITED'}.get(exc.response.status_code, 'HTTP_FAILURE')
    return 'SOURCE_UNAVAILABLE'


def observed_utc():
    return datetime.now(timezone.utc).isoformat()
