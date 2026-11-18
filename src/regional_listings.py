"""Exchange-owned listing routes for Korea and mainland China."""
from hashlib import sha256
from io import BytesIO
import json
import re
import time

import pandas as pd

KIND = 'https://kind.krx.co.kr/corpgeneral/corpList.do'
SSE = 'https://query.sse.com.cn/sseQuery/commonQuery.do'
SSE_PAGE = 'https://www.sse.com.cn/assortment/stock/list/share/'
SZSE_REPORT = 'https://www.szse.cn/api/report/ShowReport'
BSE = 'https://www.bse.cn/nqxxController/nqxxCnzq.do'
BSE_PAGE = 'https://www.bse.cn/nq/listedcompany.html'

ROUTES = {
    'KIND_KOSPI': ('Korea', KIND + '?method=download&marketType=stockMkt',
                   'KIND KOSPI listed companies; vendor instrument check required'),
    'KIND_KOSDAQ': ('Korea', KIND + '?method=download&marketType=kosdaqMkt',
                    'KIND KOSDAQ listed companies; vendor instrument check required'),
    'SSE': ('China', SSE, 'SSE Main Board A-share listing query; B shares excluded'),
    'SSE_STAR': ('China', SSE, 'SSE STAR Market A-share listing query'),
    'SZSE_JSON': ('China', SZSE_REPORT, 'SZSE published A-share report, JSON representation'),
    'BSE': ('China', BSE, 'BSE listed securities table; excludes NEEQ-only listings'),
}
SYMBOLS = {'KIND_KOSPI': (r'\d{6}', '.KS'), 'KIND_KOSDAQ': (r'\d{6}', '.KQ'),
           'SSE': (r'(?:600|601|603|605)\d{3}', '.SS'), 'SSE_STAR': (r'68\d{4}', '.SS'), 'SZSE_JSON': (r'[03]\d{5}', '.SZ'),
           'BSE': (r'(?:4\d|8\d|92)\d{4}', '.BJ')}


def download(session, method, url, **kwargs):
    with getattr(session, method)(url, timeout=(8, 20), stream=True, **kwargs) as reply:
        reply.raise_for_status()
        content = bytearray()
        for chunk in reply.iter_content(65536):
            content.extend(chunk)
            if len(content) > 12_000_000:
                from .venue_sources import ListingError

                raise ListingError('PARSER_FAILURE', 'Listing response exceeds 12 MB')
        return bytes(content)


def kind_records(body):
    frames = pd.read_html(BytesIO(body), converters={'종목코드': str}, match='종목코드', flavor='lxml')
    matches = [frame for frame in frames if {'회사명', '종목코드'}.issubset(frame.columns)]
    if len(matches) != 1:
        raise ValueError('Expected one KIND company and stock code table')
    return [(str(code).zfill(6), name, True) for code, name in
            matches[0][['종목코드', '회사명']].itertuples(index=False, name=None) if pd.notna(name)]


def json_document(raw):
    text = raw.decode('utf-8-sig').strip()
    # The BSE browser route can wrap its JSON in a callback.
    wrapped = re.fullmatch(r'[A-Za-z_$][\w.$]*\((.*)\)\s*;?', text, re.S)
    return json.loads(wrapped[1] if wrapped else text)


def sse_metadata(payload, page):
    """Log allowlisted key names and integer metadata, never response rows."""
    known_keys = {'result', 'pageHelp', 'data', 'pageCount', 'total', 'pageNo',
                  'pageSize', 'beginPage', 'endPage', 'cacheSize', 'success', 'error'}
    root = payload if isinstance(payload, dict) else {}
    value = root.get('pageHelp')
    meta = value if isinstance(value, dict) else {}
    records = root.get('result', meta.get('data'))
    fields = (set(root) | set(meta)) - known_keys
    return {
        'requested_page': page,
        'response_fields': sorted(set(root) & known_keys),
        'pagination_fields': sorted(set(meta) & known_keys),
        'other_field_count': len(fields),
        'row_container': 'result' if 'result' in root else 'pageHelp.data',
        'returned_rows': len(records) if isinstance(records, list) else None,
        'reported_page_count': safe_integer(meta.get('pageCount')),
        'reported_total_rows': safe_integer(meta.get('total')),
        'reported_page': safe_integer(meta.get('pageNo')),
        'reported_page_size': safe_integer(meta.get('pageSize')),
    }


def safe_integer(value):
    if type(value) is int and 0 <= value <= 1_000_000:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,6}', value):
        return int(value)
    return None


def sse_page(venue, session, page):
    from .venue_sources import ListingError

    raw = download(session, 'get', SSE, headers={'Referer': SSE_PAGE}, params={
        'sqlId': 'COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L',
        'STOCK_TYPE': '8' if venue == 'SSE_STAR' else '1',
        'COMPANY_STATUS': '2,4,5,7,8', 'type': 'inParams',
        'REG_PROVINCE': '', 'CSRC_CODE': '', 'STOCK_CODE': '',
        'isPagination': 'true', 'pageHelp.cacheSize': 1, 'pageHelp.pageSize': 10000,
        'pageHelp.pageNo': page, 'pageHelp.beginPage': page, 'pageHelp.endPage': page,
    })
    try:
        payload = json_document(raw)
    except (UnicodeError, ValueError) as exc:
        error = ListingError('SCHEMA_DRIFT', 'SSE did not return JSON')
        error.diagnostics = {'requested_page': page, 'reason': 'NON_JSON'}
        raise error from exc
    diagnostics = sse_metadata(payload, page)
    meta = payload.get('pageHelp') if isinstance(payload, dict) else None
    if not isinstance(meta, dict):
        error = ListingError('INCOMPLETE_PAGINATION', 'SSE pagination metadata is absent')
        error.diagnostics = dict(diagnostics, reason='MISSING_PAGE_METADATA')
        raise error
    items = payload.get('result', meta.get('data'))
    return raw, items, diagnostics['reported_page_count'], diagnostics['reported_total_rows'], diagnostics


def china_page(venue, session, page):
    if venue == 'SZSE_JSON':
        raw = download(session, 'get', SZSE_REPORT, params={
            'SHOWTYPE': 'JSON', 'CATALOGID': '1110', 'TABKEY': 'tab1', 'PAGENO': page,
        })
        data, = json_document(raw)
        meta = data['metadata']
        return raw, data['data'], int(meta['pagecount']), int(meta['recordcount']), 'agdm', 'agjc'
    raw = download(session, 'post', BSE, headers={'Referer': BSE_PAGE}, data={
        'page': page - 1, 'typejb': 'T', 'xxfcbj[]': '2',
    })
    data, = json_document(raw)
    return raw, data['content'], int(data['totalPages']), int(data['totalElements']), 'xxzqdm', 'xxzqjc'


def fetch_regional(venue, session):
    from .venue_sources import ListingError, parse_records

    _, url, _ = ROUTES[venue]
    digest = sha256()
    if venue.startswith('KIND_'):
        raw = download(session, 'get', url)
        digest.update(raw)
        try:
            records = kind_records(raw)
        except (ValueError, TypeError) as exc:
            raise ListingError('SCHEMA_DRIFT', 'Expected KIND listed-company table') from exc
    else:
        records = []
        seen = set()
        expected = None
        diagnostics = None
        first_diagnostics = None
        sse = venue in {'SSE', 'SSE_STAR'}

        def reject(code, reason, message):
            error = ListingError(code, message)
            if diagnostics is not None:
                error.diagnostics = dict(diagnostics, reason=reason, previously_received=len(records))
            raise error
        for page in range(1, 101):
            if page > 1:
                time.sleep(.25)
            if sse:
                raw, items, total_pages, total_rows, diagnostics = sse_page(venue, session, page)
                code, name = 'A_STOCK_CODE', 'COMPANY_ABBR'
                if first_diagnostics is None:
                    first_diagnostics = diagnostics
                if diagnostics['reported_page'] not in {None, page}:
                    reject('INCOMPLETE_PAGINATION', 'PAGE_NUMBER_MISMATCH', 'SSE echoed a different page number')
            else:
                try:
                    raw, items, total_pages, total_rows, code, name = china_page(venue, session, page)
                except (ValueError, KeyError, TypeError) as exc:
                    raise ListingError('SCHEMA_DRIFT', f'{venue} listing response has unexpected fields') from exc
            if not isinstance(items, list):
                reject('SCHEMA_DRIFT', 'MISSING_RESULT_ROWS', f'{venue} did not return an array of listing rows')
            try:
                page_records = [(row[code], row[name], True) for row in items]
            except (KeyError, TypeError) as exc:
                error = ListingError('SCHEMA_DRIFT', f'{venue} listing rows have unexpected fields')
                if diagnostics is not None:
                    error.diagnostics = dict(diagnostics, reason='MISSING_ROW_FIELDS')
                raise error from exc
            if not 1 <= (total_pages or 0) <= 100 or not total_rows:
                reject('INCOMPLETE_PAGINATION', 'INVALID_TOTALS', f'{venue} returned empty or invalid totals')
            if not items:
                reject('INCOMPLETE_PAGINATION', 'EMPTY_PAGE', f'{venue} returned an empty listing page')
            if expected is None:
                expected = (total_pages, total_rows)
            elif expected != (total_pages, total_rows):
                reject('INCOMPLETE_PAGINATION', 'CHANGED_TOTALS', f'{venue} reported different totals across pages')
            codes = {str(row[0]).strip() for row in page_records}
            if len(codes) != len(items) or seen & codes:
                reject('INCOMPLETE_PAGINATION', 'REPEATED_IDENTITIES', f'{venue} returned repeated listing codes')
            if len(records) + len(items) > total_rows:
                reject('INCOMPLETE_PAGINATION', 'ROWS_EXCEED_PUBLISHER_TOTAL', f'{venue} exceeded its reported total')
            digest.update(raw)
            seen.update(codes)
            records.extend(page_records)
            if page == total_pages:
                if len(records) != total_rows:
                    reject('INCOMPLETE_PAGINATION', 'FINAL_COUNT_MISMATCH',
                           f'{venue} listing row count does not match publisher total')
                break
    try:
        rows, detail = parse_records(venue, records)
    except ListingError as exc:
        if venue in {'SSE', 'SSE_STAR'}:
            exc.diagnostics = dict(diagnostics, reason='NO_VALID_BOARD_ROWS')
        raise
    if venue in {'SSE', 'SSE_STAR'}:
        if detail['rejected_bad_symbol'] or detail['duplicate_rows']:
            reject('INCOMPLETE_PAGINATION', 'INVALID_BOARD_OR_SYMBOL',
                   f'{venue} returned codes outside the requested board or invalid listing records')
        detail['response_diagnostics'] = {'first': first_diagnostics, 'last': diagnostics}
    detail['source_sha256'] = digest.hexdigest()
    if venue in {'SSE', 'SSE_STAR', 'SZSE_JSON', 'BSE'}:
        detail['completeness_check'] = 'PUBLISHER_PAGE_TOTALS_RECONCILED; NO_EXCHANGE_SCOPE_BENCHMARK'
    return rows, detail
