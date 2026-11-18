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
           'SSE': (r'6\d{5}', '.SS'), 'SSE_STAR': (r'68\d{4}', '.SS'), 'SZSE_JSON': (r'[03]\d{5}', '.SZ'),
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


def china_page(venue, session, page):
    if venue in {'SSE', 'SSE_STAR'}:
        raw = download(session, 'get', SSE, headers={'Referer': SSE_PAGE}, params={
            'sqlId': 'COMMON_SSE_CP_GPJCTPZ_GPLB_GP_L', 'stockType': '8' if venue == 'SSE_STAR' else '1',
            'isPagination': 'true', 'pageHelp.pageSize': 100, 'pageHelp.pageNo': page,
            'pageHelp.beginPage': page, 'pageHelp.endPage': page,
        })
        data = json_document(raw)
        meta = data['pageHelp']
        return raw, meta['data'], int(meta['pageCount']), int(meta['total']), 'A_STOCK_CODE', 'COMPANY_ABBR'
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
        for page in range(1, 101):
            if page > 1:
                time.sleep(.25)
            try:
                raw, items, total_pages, total_rows, code, name = china_page(venue, session, page)
                if not isinstance(items, list):
                    raise TypeError('Expected an array of exchange rows')
                page_records = [(row[code], row[name], True) for row in items]
            except (ValueError, KeyError, TypeError) as exc:
                raise ListingError('SCHEMA_DRIFT', f'{venue} listing response has unexpected fields') from exc
            if expected is None:
                expected = (total_pages, total_rows)
            codes = {str(row[0]).strip() for row in page_records}
            if (not 1 <= total_pages <= 100 or len(records) + len(items) > total_rows or not items or
                    expected != (total_pages, total_rows) or len(codes) != len(items) or seen & codes):
                raise ListingError('INCOMPLETE_PAGINATION', f'{venue} listing page totals or identities conflict')
            digest.update(raw)
            seen.update(codes)
            records.extend(page_records)
            if page == total_pages:
                if len(records) != total_rows:
                    raise ListingError('INCOMPLETE_PAGINATION', f'{venue} listing row count does not match publisher total')
                break
    rows, detail = parse_records(venue, records)
    detail['source_sha256'] = digest.hexdigest()
    if venue in {'SSE', 'SSE_STAR', 'SZSE_JSON', 'BSE'}:
        detail['completeness_check'] = 'PUBLISHER_PAGE_TOTALS_RECONCILED; NO_EXCHANGE_SCOPE_BENCHMARK'
    return rows, detail
