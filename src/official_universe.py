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
TWSE_JSON = 'https://openapi.twse.com.tw/v1/opendata/t187ap03_L'
KRX_API = 'https://apis.data.go.kr/1160100/GetKrxListedInfoService_V2/getItemInfo_V2'


def _market_row(code: str, name: str, market: str, source: str) -> dict:
    return {'ticker': code, 'company': name, 'market': market,
            'peer_group': 'unclassified', 'industry_thesis': 'OFFICIAL_LIST_ISSUER_UNREVIEWED',
            'discovery_source': source, 'security_type_status': 'OFFICIAL_ISSUER_LIST_TYPE_CHECK_VENDOR',
            'is_new_discovery': True}


def parse_jpx_table(frame: pd.DataFrame) -> list[dict]:
    """Accept domestic common shares only; reject ETFs, REITs, products and unclear classes.

    TSE 2026 increasingly uses alphanumeric issue codes. Current scoring engine
    supports numerical 4-digit .T only; excluded codes are not silently remapped.
    """
    df=frame.copy()
    def pick(*phrases):
        for col in df.columns:
            s=str(col).strip().lower().replace(' ','')
            if any(p in s for p in phrases):return col
        raise ValueError('JPX listing required column absent: '+str(phrases))
    code=pick('code','コード'); name=pick('name','銘柄名','社名')
    segment=pick('market/products','marketandproducts','marketsegment','市場・商品区分')
    result={}
    for _,r in df.iterrows():
        token=str(r[code]).strip().replace('.0','')
        title=str(r[name]).strip()
        typ=str(r[segment]).lower()
        if not re.fullmatch(r'[0-9]{4}',token) or not title or title.lower()=='nan':continue
        if not any(s in typ for s in ('prime','standard','growth')):continue
        if any(s in typ for s in ('etf','etn','reit','fund','preferred','foreign','investment trust','infrastructure')):continue
        result[token+'.T']=_market_row(token+'.T',title,'Japan',JPX_XLSX)
    if not result:raise ValueError('JPX official table contained no eligible domestic equity rows')
    return list(result.values())


def source_jpx_list(session=None) -> list[dict]:
    sess=session or requests
    reply=sess.get(JPX_XLSX,timeout=35,headers={'User-Agent':'AsiaGARPResearch/0.5'})
    reply.raise_for_status()
    if len(reply.content)>15_000_000:raise ValueError('JPX file exceeds permitted size')
    return parse_jpx_table(pd.read_excel(BytesIO(reply.content),dtype=str))


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
    while page<=max_pages:
        response=sess.get(KRX_API,params={'serviceKey':service_key,'basDt':bas_dt,
             'resultType':'json','numOfRows':1000,'pageNo':page},timeout=30)
        response.raise_for_status()
        payload=response.json()
        body=(payload.get('response',{}) or {}).get('body',{}) if isinstance(payload,dict) else {}
        count=int(body.get('totalCount',0) or 0) if isinstance(body,dict) else 0
        page_rows=parse_krx_list(payload)
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
     'url':JPX_XLSX,'implementation':'AUTOMATED_SUPPLEMENTAL',
     'note':'Domestic equity classes with numeric 4-digit codes; others excluded pending parser extension'},
    {'market':'China','source':'SSE/SZSE issuer lists',
     'url':'https://www.sse.com.cn/','implementation':'NOT_CONNECTED',
     'note':'No verified fully accessible publisher listing adapter'},
    {'market':'Hong Kong','source':'HKEX securities lists',
     'url':'https://www.hkex.com.hk/Services/Trading/Securities/Securities-Lists?sc_lang=en',
     'implementation':'NOT_CONNECTED',
     'note':'Listing file parsing and issuer/security-type auditing not implemented'},
    {'market':'Taiwan','source':'TWSE open data: listed company information',
     'url':TWSE_JSON,'implementation':'AUTOMATED_SUPPLEMENTAL',
     'note':'TWSE listing only; Taipei Exchange (TPEx) OTC not included'},
]
