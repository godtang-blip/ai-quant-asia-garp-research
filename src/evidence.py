"""Evidence intake: issuer-level provenance and explicit verification statuses.

NEWS: headlines + publisher + publication date; NOT full article interpretation.
EARNINGS: yfinance vendor quarterly series, NOT audited issuer filings.
DART: official filing metadata via optional DART_API_KEY; NOT filing-number verification.
No LLM generated facts, no automatic investment recommendations.
"""
from __future__ import annotations
import datetime as dt
from email.utils import parsedate_to_datetime
import io
import json
import os
from pathlib import Path
from urllib.parse import urlencode
import zipfile
import xml.etree.ElementTree as ET
import pandas as pd

COLUMNS=['ticker','company','market','evidence_type','published_date','retrieved_utc',
         'title','source_name','source_url','source_tier','verification_status',
         'claim_supported','analyst_note','identifier']


def _utc():return dt.datetime.now(dt.timezone.utc).isoformat()

def _date_str(s):
    try:return parsedate_to_datetime(str(s)).date().isoformat()
    except (ValueError,TypeError,IndexError):return ''

def news_rss(company:str,ticker:str,limit:int=4,session=None)->list[dict]:
    """Search recent headlines; availability is not guaranteed by the provider."""
    import requests
    sess=session or requests
    # Security: ticker+company are url-encoded by requests params, not direct URLs.
    q=f'"{company}" (earnings OR results OR revenue OR guidance OR shares) when:90d'
    resp=sess.get('https://news.google.com/rss/search',params={'q':q,'hl':'en-US','gl':'US','ceid':'US:en'},
                  headers={'User-Agent':'Mozilla/5.0 AsiaEquityResearch/0.3.1'},timeout=14)
    resp.raise_for_status()
    root=ET.fromstring(resp.content)
    docs=[]
    for item in root.findall('./channel/item')[:limit]:
        t=item.findtext('title','').strip();link=item.findtext('link','').strip()
        date=_date_str(item.findtext('pubDate',''))
        source=item.find('source')
        publisher=source.text.strip() if source is not None and source.text else 'Google News RSS publisher unknown'
        if not t or not link.startswith('https://'):continue
        docs.append({'title':t,'source_url':link,'published_date':date,'source_name':publisher,
                     'identifier':str(ticker)+'|'+str(date)+'|'+t[:90]})
    return docs


def quarterly_vendor_rows(ticker:str,limit:int=4)->list[dict]:
    import yfinance as yf
    table=yf.Ticker(ticker).quarterly_income_stmt
    if table is None or table.empty:return []
    fields={'Total Revenue':'revenue','Operating Income':'operating_income',
            'Net Income':'net_income','Diluted EPS':'diluted_eps'}
    rows=[]
    for quarter in list(table.columns)[:limit]:
        vals={'quarter_ending':str(quarter.date()) if hasattr(quarter,'date') else str(quarter)[:10]}
        for raw,normal in fields.items():
            if raw not in table.index:continue
            value=pd.to_numeric(pd.Series([table.loc[raw,quarter]]),errors='coerce').iloc[0]
            if pd.notna(value):vals[normal]=float(value)
        if len(vals)>1:rows.append(vals)
    return rows


def dart_stock_code_map(key:str, session=None)->dict[str,dict]:
    """Official downloadable ZIP mapping stock_code to corp_code; no guessed mapping."""
    import requests
    sess=session or requests
    res=sess.get('https://opendart.fss.or.kr/api/corpCode.xml',params={'crtfc_key':key},timeout=35)
    res.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(res.content)) as z:
        names=[n for n in z.namelist() if n.lower().endswith('.xml')]
        if not names:raise ValueError('DART corp code archive missing XML')
        xml=z.read(names[0])
    out={}
    for node in ET.fromstring(xml).findall('.//list'):
        stock=node.findtext('stock_code','').strip();corp=node.findtext('corp_code','').strip()
        if len(stock)==6 and stock.isdigit() and len(corp)==8 and corp.isdigit():
            out[stock]={'corp_code':corp,'corp_name':node.findtext('corp_name','').strip()}
    if not out:raise ValueError('DART mapping contains no stock codes')
    return out


def dart_recent_filings(stock_code:str,corp_map:dict,key:str,session=None,days:int=180,limit:int=7)->list[dict]:
    import requests
    d=corp_map.get(stock_code)
    if not d:return []
    sess=session or requests
    end=dt.datetime.now(dt.timezone.utc).date();start=end-dt.timedelta(days=days)
    res=sess.get('https://opendart.fss.or.kr/api/list.json',params={
        'crtfc_key':key,'corp_code':d['corp_code'],'bgn_de':start.strftime('%Y%m%d'),
        'end_de':end.strftime('%Y%m%d'),'page_count':min(100,limit)},timeout=18)
    res.raise_for_status();payload=res.json()
    if payload.get('status')=='013':return [] # no records
    if payload.get('status')!='000':raise ValueError('DART list API status '+str(payload.get('status')))
    result=[]
    for r in payload.get('list',[])[:limit]:
        ident=str(r.get('rcept_no') or '')
        if not (len(ident)==14 and ident.isdigit()):continue
        raw_date=str(r.get('rcept_dt') or '')
        result.append({'title':str(r.get('report_nm') or ''),'published_date':
                       f'{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}' if len(raw_date)==8 else '',
                       'source_name':'OPENDART (Korea regulator)',
                       'source_url':'https://dart.fss.or.kr/dsaf001/main.do?rcpNo='+ident,'identifier':ident})
    return result


def read_manual_decisions(file:Path)->pd.DataFrame:
    fields=['ticker','company','decision','decision_date','initial_thesis','key_counterevidence',
            'decision_reason','evidence_urls','revisit_trigger','analyst_reviewed_by']
    if not file.exists():return pd.DataFrame(columns=fields)
    df=pd.read_csv(file,dtype=str).fillna('')
    if not set(fields).issubset(df.columns):raise ValueError('Research decisions missing columns')
    if df.ticker.duplicated().any():raise ValueError('Research decision ticker duplicated')
    permitted={'INVESTIGATING','ACCEPTED','REJECTED','ON_HOLD'}
    if not set(df.decision).issubset(permitted):raise ValueError('Invalid research decision')
    for _,r in df.iterrows():
        if r.decision in {'ACCEPTED','REJECTED'}:
            if not (r.decision_date and r.decision_reason and r.evidence_urls and r.analyst_reviewed_by):
                raise ValueError(f'{r.ticker} decision requires date, reason, source and analyst approval')
    return df


def collect_evidence(candidates:pd.DataFrame,mode:str='full',limit:int=8,
                     registry:Path|None=None, key:str|None=None)->dict:
    if mode not in ('off','news','full'):raise ValueError('mode must be off/news/full')
    news=[];earnings=[];filings=[];ledger=[];logs=[]
    if mode=='off' or limit<=0:
        return {'news':pd.DataFrame(columns=['ticker','title','source_url','published_date','source_name','identifier']),
                'earnings':pd.DataFrame(columns=['ticker','company','market','quarter_ending','revenue','operating_income','net_income','diluted_eps','currency','data_source','verification_status']),
                'filings':pd.DataFrame(columns=['ticker','title','source_url','published_date','source_name','identifier','filing_source','verification_status']),
                'ledger':pd.DataFrame(columns=COLUMNS),
                'log':pd.DataFrame(columns=['ticker','source','status','detail'])}
    rows=candidates.head(limit)
    issued={}
    if registry and registry.exists():
        df=pd.read_csv(registry,dtype=str).fillna('')
        for _,r in df.iterrows():issued[str(r.get('ticker',''))]=r.to_dict()
    corpmap={}
    if key and any(str(r.market)=='Korea' for _,r in rows.iterrows()) and mode=='full':
        try:corpmap=dart_stock_code_map(key)
        except Exception as exc:logs.append({'ticker':'*','source':'DART_CORP_MAP','status':'FAILED','detail':type(exc).__name__+': '+str(exc)[:120]})
    generated=_utc()
    def log(ticker,source,status,detail=''):
        logs.append({'ticker':ticker,'source':source,'status':status,'detail':detail[:150]})
    def add(ticker,company,market,typ,source,doc,pub_tier,status):
        ledger.append({'ticker':ticker,'company':company,'market':market,'evidence_type':typ,
            'published_date':doc.get('published_date',''),'retrieved_utc':generated,
            'title':doc.get('title',''),'source_name':doc.get('source_name',source),
            'source_url':doc.get('source_url',''),'source_tier':pub_tier,
            'verification_status':status,'claim_supported':'',
            'analyst_note':'','identifier':doc.get('identifier','')})
    for _,r in rows.iterrows():
        t=str(r.ticker);name=str(r.company);market=str(r.market)
        if mode in ('news','full'):
            try:
                found=news_rss(name,t)
                for doc in found:
                    news.append({'ticker':t,**doc})
                    add(t,name,market,'NEWS_HEADLINE','GOOGLE_NEWS_RSS',doc,'SECONDARY_AGGREGATOR',
                        'HEADLINE_COLLECTED_ARTICLE_UNREAD')
                log(t,'NEWS_RSS','OK' if found else 'EMPTY',str(len(found)))
            except Exception as exc:log(t,'NEWS_RSS','FAILED',type(exc).__name__+': '+str(exc))
        if mode=='full':
            try:
                qrows=quarterly_vendor_rows(t)
                for q in qrows:
                    earnings.append({'ticker':t,'company':name,'market':market,**q,
                                     'currency':str(r.get('financial_currency','')),
                                     'data_source':'yfinance.quarterly_income_stmt','verification_status':'VENDOR_UNVERIFIED'})
                    doc={'published_date':'','title':'Vendor quarterly statement for period '+q['quarter_ending'],
                         'source_url':'https://finance.yahoo.com/quote/'+t+'/financials/',
                         'identifier':t+'|'+q['quarter_ending']}
                    add(t,name,market,'EARNINGS_VENDOR','yfinance',doc,'DATA_VENDOR',
                        'VENDOR_STATEMENT_NOT_CROSSCHECKED_WITH_FILING')
                log(t,'EARNINGS_VENDOR','OK' if qrows else 'EMPTY',str(len(qrows)))
            except Exception as exc:log(t,'EARNINGS_VENDOR','FAILED',type(exc).__name__+': '+str(exc))
            if market=='Korea':
                if not key:log(t,'OPENDART','API_KEY_NOT_CONFIGURED')
                elif not corpmap:log(t,'OPENDART','CORP_MAP_UNAVAILABLE')
                else:
                    try:
                        docs=dart_recent_filings(t[:6],corpmap,key)
                        for doc in docs:
                            filings.append({'ticker':t,**doc,'filing_source':'OPENDART','verification_status':'REGULATOR_INDEX_METADATA_ONLY'})
                            add(t,name,market,'REGULATOR_FILING','OPENDART',doc,'PRIMARY_REGULATOR_INDEX',
                                'FILING_METADATA_FOUND_CONTENT_NOT_AUDITED')
                        log(t,'OPENDART','OK' if docs else 'EMPTY',str(len(docs)))
                    except Exception as exc:log(t,'OPENDART','FAILED',type(exc).__name__+': '+str(exc))
            else:log(t,'PRIMARY_REGULATOR', 'NO_AUTOMATED_CONNECTOR_FOR_THIS_MARKET')
        doc=issued.get(t,{})
        for kind in ('filing_url','earnings_url'):
            url=doc.get(kind,'')
            if str(url).startswith('https://'):
                add(t,name,market,'ISSUER_LINK_REGISTERED','MANUAL_REGISTRY',
                    {'title':'Analyst registered '+kind, 'source_url':url,
                     'published_date':doc.get('source_date',''),'identifier':t+'|'+kind},
                    'ISSUER_LINK_UNVERIFIED','REGISTERED_NOT_AUTOMATICALLY_VERIFIED')
    return {'news':pd.DataFrame(news),'earnings':pd.DataFrame(earnings),
            'filings':pd.DataFrame(filings),'ledger':pd.DataFrame(ledger,columns=COLUMNS),
            'log':pd.DataFrame(logs,columns=['ticker','source','status','detail'])}


def render_evidence_book(candidates:pd.DataFrame, evidence:pd.DataFrame, decisions:pd.DataFrame)->str:
    lines=['# Evidence Book — Research only','',
       'Source discovery is **not** verification of a financial claim. News RSS contains headlines, not full articles.',
       'Primary filings and specific valuation theses require an analyst to read and sign off.','',
       'A **REJECTED** hypothesis is a valid research outcome and is preserved in data/research_decisions.csv.','']
    dec={str(r.ticker):r for _,r in decisions.iterrows()}
    for _,r in candidates.iterrows():
        t=str(r.ticker);lines.extend([f'## {r.company} ({t}, {r.market})','',
            f"- Provisional investigation score: {r.get('cross_industry_score_100','')} (not expected return)",
            f"- Investigation gate: {r.get('v031_research_status','REVIEW_REQUIRED')}",
            '- Growth/valuation figures: vendor snapshots; **not issuer-confirmed**'])
        if t in dec:
            d=dec[t]
            lines.append(f'- Analyst decision: **{d.decision}**; reason: {d.decision_reason or "not supplied"}')
            if d.key_counterevidence:lines.append(f'- Counterevidence: {d.key_counterevidence}')
            if d.revisit_trigger:lines.append(f'- Revisit condition: {d.revisit_trigger}')
        sub=evidence[evidence.ticker.eq(t)] if not evidence.empty else pd.DataFrame()
        if sub.empty:lines.append('- Sources: none collected; **do not infer a positive thesis**')
        else:
            lines.extend(['','| Date | Type | Title / Link | Verification |','|---|---|---|---|'])
            for _,d in sub.head(16).iterrows():
                title=str(d.title).replace('|','/').replace('[','(').replace(']',')')[:100]
                link=str(d.source_url)
                lines.append(f'| {d.published_date or "—"} | {d.evidence_type} | [{title}]({link}) | {d.verification_status} |')
        lines.extend(['','**To investigate:** What is the market missing? Which filing confirms the metrics? ',
                      'What evidence contradicts the thesis? What would falsify it?',''])
    return '\n'.join(lines)+'\n'
