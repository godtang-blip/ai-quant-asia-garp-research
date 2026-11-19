"""Strictly attributed *supplemental* official issuer lists.

Only proven, downloadable parsers; market coverage is never mislabeled complete.
URLs are publisher URLs. HTTP/errors are logged by the caller and never replaced
with guessed companies. Source issuer registration != vendor equity verification.
"""
from __future__ import annotations

from io import BytesIO
import datetime as dt
import re
import pandas as pd
import requests

JPX_XLSX = 'https://www.jpx.co.jp/english/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_e.xlsx'
JPX_XLS = JPX_XLSX.removesuffix('x')
JPX_JAPANESE_XLS = 'https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls'
JPX_CODE = r'[0-9][0-9ACDFGHJKLMNPRSTUWXY][0-9][0-9ACDFGHJKLMNPRSTUWXY]'
TWSE_JSON = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
KRX_API = 'https://apis.data.go.kr/1160100/GetKrxListedInfoService_V2/getItemInfo_V2'


def _market_row(code: str, name: str, market: str, source: str) -> dict:
    return {'ticker': code, 'company': name, 'market': market,
            'peer_group': 'unclassified', 'industry_thesis': 'OFFICIAL_LIST_ISSUER_UNREVIEWED',
            'discovery_source': source, 'security_type_status': 'OFFICIAL_ISSUER_LIST_TYPE_CHECK_VENDOR',
            'is_new_discovery': True}


def _jpx_normalize_header(value: object) -> str:
    """Ignore spacing/punctuation/full-width variants when matching JPX headers."""
    import unicodedata
    raw = unicodedata.normalize('NFKC', str(value or '')).lower()
    return re.sub(r'[^\w\u3040-\u30ff\u3400-\u9fff]+', '', raw)


def _jpx_columns(columns) -> dict[str, object] | None:
    normalized = {c: _jpx_normalize_header(c) for c in columns}
    def find(candidates, *, forbid=()):
        for word in candidates:
            needle=_jpx_normalize_header(word)
            for column,text in normalized.items():
                if needle in text and not any(_jpx_normalize_header(x) in text for x in forbid):
                    return column
        return None
    # Avoid interpreting dates, venue identifiers or issuer classification as ticker codes.
    code=find(['Local Code','Issue Code','Securities Code','銘柄コード','コード','Code'],forbid=['industry','sector','業種','topix','分類'])
    name=find(['Name (English)','Company Name','Issue Name','銘柄名','会社名','Name'],forbid=['industry','sector','業種','分類'])
    segment=find(['Market/Products','Market and Products','Market Segment','Market Category',
                  'Market/Product','Section/Products','Market Division','市場・商品区分','市場区分','市場商品区分',
                  '上場市場','Market'],forbid=['capitalization','時価総額'])
    return {'code':code,'name':name,'segment':segment} if all(v is not None for v in (code,name,segment)) else None


def _jpx_locate_table(frame:pd.DataFrame) -> tuple[pd.DataFrame,dict]:
    """Accept explicit headers or up to 12 title/preamble rows before header.

    Do not invent a market classification if no compatible header is found.
    """
    cols=_jpx_columns(frame.columns)
    if cols:return frame.copy(),cols
    for row_index in range(min(12,len(frame))):
        raw=frame.iloc[row_index].tolist()
        cols=_jpx_columns(raw)
        if cols:
            # Assign temporary unique labels to survive duplicate/blank Excel columns.
            renamed=[]; seen={}
            for v in raw:
                base=str(v).strip() or 'unnamed'
                n=seen.get(base,0);seen[base]=n+1
                renamed.append(base if not n else f'{base}__{n}')
            rebuilt=frame.iloc[row_index+1:].copy()
            rebuilt.columns=renamed
            updated=_jpx_columns(rebuilt.columns)
            if updated:return rebuilt,updated
    description=', '.join(str(x)[:65] for x in list(frame.columns)[:20])
    raise ValueError('JPX schema/header unrecognized (fail closed); observed headers: '+description)


def parse_jpx_table(frame:pd.DataFrame, source: str = JPX_XLSX, *, include_industries=False) -> list[dict]:
    """Parse domestic Prime/Standard/Growth equity candidates; no ETF/REIT guesswork."""
    df,found=_jpx_locate_table(frame)
    code,name,segment=(found[k] for k in ('code','name','segment'))
    industry = next((col for col in df if str(col).strip().casefold() in
                     {'33業種区分', '33-sector name', '33 sector name', '33 sectors', 'industry (33 sectors)'}), None)
    disclosed = next((col for col in df if str(col).strip() in {'日付', 'Date'}), None)
    result={}
    for _,r in df.iterrows():
        token=str(r[code]).strip().upper()
        if token.endswith('.0'):token=token[:-2]
        title=str(r[name]).strip()
        typ=str(r[segment]).lower()
        if not re.fullmatch(JPX_CODE,token) or not title or title.lower()=='nan':continue
        # EXPLICIT segment match; English/Japanese aliases. Reject broad 'Tokyo' etc.
        domestic=any(s in typ for s in ('prime','standard','growth','プライム','スタンダード','グロース'))
        if not domestic:continue
        if any(s in typ for s in ('etf','etn','reit','fund','preferred','foreign','investment trust',
                                  'infrastructure','投資信託','外国','優先','pro market')):continue
        result[token+'.T']=_market_row(token+'.T',title,'Japan',source)
        if include_industries and industry is not None and pd.notna(r[industry]):
            asof = str(r[disclosed]).strip() if disclosed is not None else ''
            match = re.fullmatch(r'(\d{4})[-/]?(\d{2})[-/]?(\d{2})(?: 00:00:00)?', asof)
            result[token+'.T'].update(exchange_industry=str(r[industry]).strip(), listing_source_url=source,
                                      listing_source_date='-'.join(match.groups()) if match else '')
    if not result:raise ValueError('JPX parsed table contained no eligible domestic equity rows')
    return list(result.values())


def source_jpx_list(session=None, *, include_industries=False) -> list[dict]:
    sess=session or requests
    failures = []
    for url in (JPX_XLS, JPX_JAPANESE_XLS, JPX_XLSX):
        try:
            options = {'allow_redirects': False} if include_industries else {}
            reply = sess.get(url, timeout=35, headers={'User-Agent': 'AsiaGARPResearch/0.5.1'}, **options)
            reply.raise_for_status()
            content = reply.content
            if len(content) > 15_000_000:
                raise ValueError('JPX file exceeds permitted size')
            if content.startswith(b'PK\x03\x04'):
                engine = 'openpyxl'
            elif content.startswith(bytes.fromhex('d0cf11e0a1b11ae1')):
                engine = 'xlrd'
            else:
                raise ValueError('JPX response is not an Excel workbook')
            frame = pd.read_excel(BytesIO(content), header=None, dtype=str, engine=engine)
            rows = parse_jpx_table(frame, url, include_industries=include_industries)
            if include_industries and not any(row.get('exchange_industry') for row in rows):
                raise ValueError('Exchange workbook has no identified industry column')
            return rows
        except Exception as exc:
            failures.append(f"{url.rsplit('/', 1)[-1]}: {exc}")
    raise ValueError('All JPX workbook variants failed: ' + '; '.join(failures))


def parse_twse_list(payload) -> list[dict]:
    """TWSE listed-company disclosure (not OTC and not all Taiwan securities)."""
    if not isinstance(payload,list):raise ValueError('TWSE official JSON expected list')
    out={}
    for row in payload:
        if not isinstance(row,dict):continue
        code=str(row.get('公司代號') or row.get('Code') or '').strip()
        name=str(row.get('公司名稱') or row.get('公司簡稱') or row.get('CompanyName') or '').strip()
        if not re.fullmatch(r'[0-9]{4}',code) or not name:continue
        out[code+'.TW']=_market_row(code+'.TW',name,'Taiwan',TWSE_JSON)
    if not out:raise ValueError('TWSE official JSON contained no listed company codes')
    return list(out.values())


def source_twse_list(session=None) -> list[dict]:
    sess=session or requests
    response=sess.get(TWSE_JSON,timeout=35,headers={'User-Agent':'AsiaGARPResearch/0.5'})
    response.raise_for_status()
    if len(response.content)>15_000_000:raise ValueError('TWSE response exceeds permitted size')
    return parse_twse_list(response.json())


def parse_krx_list(payload) -> list[dict]:
    """Return KOSPI / KOSDAQ common issue code candidates only; excludes KONEX and unclear types.

    KRX datasets may include non-common stocks with 6-digit codes; final vendor
    equity confirmation remains necessary, and no all-market coverage is claimed.
    """
    result = payload.get('response',{}) if isinstance(payload,dict) else {}
    header=result.get('header',{}) or {}
    if str(header.get('resultCode','00')).zfill(2)!='00':
        raise ValueError('KRX official API error code '+str(header.get('resultCode')))
    body=result.get('body',{}) or {}
    items=(body.get('items') or {}).get('item',[]) if isinstance(body.get('items'),dict) else []
    if isinstance(items,dict):items=[items]
    if not isinstance(items,list):raise ValueError('KRX returned invalid item list')
    seen={}
    for r in items:
        if not isinstance(r,dict):continue
        code=str(r.get('srtnCd') or '').strip().upper().removeprefix('A')
        name=str(r.get('itmsNm') or r.get('corpNm') or '').strip()
        category=str(r.get('mrktCtg') or '').strip().upper()
        if not re.fullmatch(r'[0-9]{6}',code) or not name:continue
        if category in ('KOSPI','유가증권시장'):
            suf='.KS'
        elif category in ('KOSDAQ','코스닥'):
            suf='.KQ'
        else:continue
        seen[code+suf]=_market_row(code+suf,name,'Korea',KRX_API)
    return list(seen.values())


def source_krx_list(service_key:str,bas_dt:str,session=None)->list[dict]:
    """Date-scoped official API; an invalid/holiday date fails visibly.

    An API key from data.go.kr is required, and the returned issue type is
    not independently audited as common equity by this connector.
    """
    if not service_key.strip():raise ValueError('KRX official API service key missing')
    if not re.fullmatch(r'[0-9]{8}',bas_dt):raise ValueError('KRX basDt must be YYYYMMDD')
    sess=session or requests
    output={};page=1;max_pages=15;total=None
    seen_issues = set()
    while page<=max_pages:
        try:
            response=sess.get(KRX_API,params={'serviceKey':service_key,'basDt':bas_dt,
                 'resultType':'json','numOfRows':1000,'pageNo':page},timeout=30)
        except requests.RequestException as exc:
            raise ValueError(f'KRX request failed: {type(exc).__name__}') from None
        if not response.ok:
            raise ValueError(f'KRX official API HTTP {response.status_code}')
        payload=response.json()
        body=(payload.get('response',{}) or {}).get('body',{}) if isinstance(payload,dict) else {}
        count=int(body.get('totalCount',0) or 0) if isinstance(body,dict) else 0
        page_rows=parse_krx_list(payload)
        items = (body.get('items') or {}).get('item', [])
        items = [items] if isinstance(items, dict) else items
        identities = {str(item.get('isinCd') or item.get('srtnCd') or '') for item in items}
        expected = min(1000, max(0, count - (page - 1) * 1000))
        if ((total is not None and total != count) or len(items) != expected or
                '' in identities or len(identities) != len(items) or seen_issues.intersection(identities)):
            raise ValueError('INCOMPLETE_PAGINATION: KRX returned inconsistent totals or repeated issues')
        seen_issues.update(identities)
        for row in page_rows:output[row['ticker']]=row
        if total is None:total=count
        if page*1000>=count:break
        page+=1
    if total and page*1000<total:raise ValueError('KRX page limit exceeded; cannot label full retrieval')
    if not output:raise ValueError('KRX returned zero KOSPI/KOSDAQ candidates; holiday or invalid date?')
    return list(output.values())


def previous_weekday(today:dt.date|None=None)->str:
    value=today or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    value-=dt.timedelta(days=1)
    while value.weekday()>=5:value-=dt.timedelta(days=1)
    return value.strftime('%Y%m%d')


OFFICIAL_SOURCE_REGISTRY = [
    {'market':'Korea','source':'KRX data marketplace / public data API',
     'url':'https://www.data.go.kr/en/data/15094775/openapi.do',
     'implementation':'AUTOMATED_IF_KEY_CONFIGURED',
     'note':'Requires authorized PUBLIC_DATA_API_KEY and valid KRX_BASE_DATE (YYYYMMDD), holidays may need override'},
    {'market':'Japan','source':'JPX monthly issued securities XLSX',
     'url':JPX_XLS,'implementation':'AUTOMATED_SUPPLEMENTAL',
     'note':'Domestic equity classes with supported numeric and alphanumeric security codes'},
    {'market':'China','source':'SSE/SZSE issuer lists',
     'url':'https://www.sse.com.cn/','implementation':'LOCAL_PUBLISHER_EXPORT_SUPPORTED',
     'note':'SSE, SZSE and BSE exports can be imported; direct listing retrieval is not connected'},
    {'market':'Hong Kong','source':'HKEX securities lists',
     'url':'https://www.hkex.com.hk/Services/Trading/Securities/Securities-Lists?sc_lang=en',
     'implementation':'LOCAL_PUBLISHER_EXPORT_SUPPORTED',
     'note':'HKEX export can be imported; direct listing retrieval is not connected'},
    {'market':'Taiwan','source':'TWSE open data: listed company information',
     'url':TWSE_JSON,'implementation':'AUTOMATED_SUPPLEMENTAL',
     'note':'TWSE live listing; Taipei Exchange (TPEx) files can be imported separately'},
]
