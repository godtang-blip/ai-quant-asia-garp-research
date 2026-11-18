"""Independent universe extension from identified sources; no invented tickers.

Nikkei 225 official public index table and optional yfinance screening.  Failure
is logged, not filled with guessed stocks.  These are watchlist *candidates*,
NOT a complete exchange list or a 300-name company-fundamentals audit.
"""
from __future__ import annotations
from io import StringIO
import re
import pandas as pd

NIKKEI_URL = 'https://indexes.nikkei.co.jp/en/nkave/index/component'
REGIONS = {'Japan': ('jp', '.T'), 'Korea': ('kr', '.KS'),
           'Taiwan': ('tw', '.TW'), 'Hong Kong': ('hk', '.HK')}

def _record(symbol, name, market, source, group='unclassified'):
    return {'ticker':str(symbol), 'company':str(name), 'market':market,
        'peer_group':group,'industry_thesis':'DISCOVERED_UNREVIEWED',
        'discovery_source':source,'is_new_discovery':True}


def parse_nikkei_html(html: str) -> list[dict]:
    """Parse actual published code table; refuses unverified regex ticker guessing."""
    out=[]
    try:
        tables=pd.read_html(StringIO(html))
    except (ImportError, ValueError):
        return []
    for t in tables:
        t.columns=[str(x).strip().lower() for x in t.columns]
        code_cols=[c for c in t.columns if 'code' in c]
        name_cols=[c for c in t.columns if 'company' in c or 'name' in c]
        if not code_cols or not name_cols:
            continue
        for _, row in t.iterrows():
            raw=str(row[code_cols[0]]).strip()
            match=re.fullmatch(r'\s*(\d{4})\s*(?:\.0)?\s*',raw)
            if not match: continue
            name=str(row[name_cols[0]]).strip()
            if len(name)<2 or name.lower()=='nan': continue
            out.append(_record(f'{match.group(1)}.T',name,'Japan',NIKKEI_URL))
    # avoid accidentally accepting nav tables as a full component index
    unique={d['ticker']:d for d in out}
    return list(unique.values()) if len(unique)>=30 else []


def source_nikkei225() -> list[dict]:
    import requests
    resp=requests.get(NIKKEI_URL,headers={'User-Agent':'Mozilla/5.0 (compatible; EquityResearch/0.3)'},timeout=30)
    resp.raise_for_status()
    rows=parse_nikkei_html(resp.text)
    if not rows:
        raise ValueError('OFFICIAL_NIKKEI_TABLE_UNREADABLE; no guessed replacements')
    return rows


def source_yahoo_screener(region: str, limit: int=50) -> list[dict]:
    import yfinance as yf
    if region not in REGIONS: raise ValueError('Unsupported region')
    region_code, expected_suffix=REGIONS[region]
    query=yf.EquityQuery('eq',['region', region_code])
    result=yf.screen(query, offset=0, size=min(limit,100))
    quotes=result.get('quotes',[]) if isinstance(result,dict) else []
    out=[]
    for quote in quotes:
        ticker=str(quote.get('symbol') or '').upper().strip()
        if not ticker.endswith(expected_suffix): continue
        name=quote.get('shortName') or quote.get('longName') or ticker
        out.append(_record(ticker,name,region,f'yfinance.screen:region={region_code}'))
    return out


def discover_universe(base: pd.DataFrame, mode: str='nikkei', per_region: int=50):
    """Returns combined list, audit table. No network if mode='off'.

    Curated records retain analyst peer_group; discovered unclassified stocks
    are research queue ONLY, not silently assumed financially comparable.
    """
    if mode not in ('off','nikkei','regional','both'):
        raise ValueError('discover mode must be off, nikkei, regional or both')
    data=base.copy().fillna('')
    data['is_new_discovery']=False
    data['discovery_source']='ANALYST_CURATED_UNIVERSE_CSV'
    logs=[]
    additions=[]
    sources=[]
    if mode in ('nikkei','both'): sources.append(('official_nikkei225',source_nikkei225))
    if mode in ('regional','both'):
        for reg in REGIONS:
            sources.append((f'yahoo_screener_{reg}',lambda reg=reg:source_yahoo_screener(reg,per_region)))
    for label, fn in sources:
        try:
            vals=fn()
            logs.append({'source':label,'status':'OK','received':len(vals),'error':''})
            additions.extend(vals)
        except Exception as exc:
            logs.append({'source':label,'status':'FAILED_NO_FALLBACK','received':0,
                         'error':type(exc).__name__+': '+str(exc)[:200]})
    if additions:
        new=pd.DataFrame(additions)
        new=new[~new.ticker.isin(data.ticker)].drop_duplicates('ticker',keep='first')
        data=pd.concat([data,new],ignore_index=True)
    return data.reset_index(drop=True),pd.DataFrame(logs,columns=['source','status','received','error'])
