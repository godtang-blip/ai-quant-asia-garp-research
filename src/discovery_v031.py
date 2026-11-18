"""Five-market issuer discovery. Watchlist search, NOT a complete exchange census.

Every accepted ticker must have actual source provenance. The region screener is
vendor-curated, can omit stocks, and can return wrong security types; audit that.
"""
from __future__ import annotations
import re
import os
import pandas as pd
from .discovery import source_nikkei225
from .official_universe import source_jpx_list, source_twse_list, source_krx_list, previous_weekday

REGIONS = {'Korea': ('kr', (r'^\d{6}\.KS$', r'^\d{6}\.KQ$')),
           'Japan': ('jp', (r'^\d{4}\.T$',)),
           'China': ('cn', (r'^\d{6}\.SS$', r'^\d{6}\.SZ$', r'^\d{6}\.BJ$')),
           'Hong Kong': ('hk', (r'^\d{1,5}\.HK$',)),
           'Taiwan': ('tw', (r'^\d{4}\.TW$', r'^\d{4}\.TWO$'))}

BAD_TYPES = {'ETF','MUTUALFUND','FUND','INDEX','CRYPTOCURRENCY','CURRENCY','FUTURE','OPTION','BOND','WARRANT'}

def ticker_market_valid(ticker:str, market:str)->bool:
    return any(re.fullmatch(pattern,str(ticker).upper()) for pattern in REGIONS.get(str(market),('',()))[1])

def equity_type_status(quote:dict)->str:
    t=str(quote.get('quoteType') or quote.get('typeDisp') or '').upper().strip().replace(' ','')
    return 'VERIFIED_EQUITY_VENDOR' if t=='EQUITY' else ('REJECT_NON_EQUITY' if t in BAD_TYPES else 'TYPE_UNCONFIRMED')


def source_region(market:str, max_rows:int=100, page_size:int=50)->tuple[list[dict],dict]:
    import yfinance as yf
    code,_=REGIONS[market]
    found=[]; duplicate=set(); rejected=[]; pages=0
    query=yf.EquityQuery('eq',['region',code])
    for offset in range(0,max_rows,page_size):
        response=yf.screen(query,offset=offset,size=min(page_size,max_rows-offset))
        quotes=response.get('quotes',[]) if isinstance(response,dict) else []
        if not isinstance(quotes,list):raise ValueError('Vendor screener returned non-list quotes')
        pages+=1
        if not quotes:break
        for q in quotes:
            ticker=str(q.get('symbol') or '').upper().strip()
            if not ticker_market_valid(ticker,market):
                rejected.append('INVALID_MARKET_SYMBOL');continue
            security=equity_type_status(q)
            if security=='REJECT_NON_EQUITY':
                rejected.append('NON_EQUITY');continue
            if ticker in duplicate:continue
            duplicate.add(ticker)
            found.append({'ticker':ticker,'company':str(q.get('longName') or q.get('shortName') or ticker),
                          'market':market,'peer_group':'unclassified','industry_thesis':'NEW_SOURCE_NEEDS_REVIEW',
                          'discovery_source':f'Yahoo screener / region={code} / offset={offset}',
                          'security_type_status':security,'is_new_discovery':True})
        if len(quotes)<min(page_size,max_rows-offset):break
    return found,{'market':market,'pages':pages,'rejected_non_equity':rejected.count('NON_EQUITY'),
                  'rejected_bad_symbol':rejected.count('INVALID_MARKET_SYMBOL')}


def discover_five_markets(base:pd.DataFrame, mode:str='all5',per_region:int=90)->tuple[pd.DataFrame,pd.DataFrame]:
    if mode not in ('off','all5','regional5','nikkei','all5_official'):
        raise ValueError('discover_mode must be off, all5, regional5, nikkei, all5_official')
    result=base.copy().fillna('');result['is_new_discovery']=False
    result['discovery_source']='CURATED_LIST'
    result['security_type_status']='CURATED_TICKER_TYPE_NEEDS_CONFIRMATION'
    logs=[]; candidates=[]
    sources=[]
    if mode in ('all5','nikkei','all5_official'):
        sources.append(('official_nikkei225',lambda: (source_nikkei225(),{'market':'Japan','pages':1,'rejected_non_equity':0,'rejected_bad_symbol':0})))
    if mode == 'all5_official':
        if os.environ.get('PUBLIC_DATA_API_KEY'):
            sources.append(('official_krx_listed_issues',lambda: (source_krx_list(
                os.environ['PUBLIC_DATA_API_KEY'],os.environ.get('KRX_BASE_DATE') or previous_weekday()),
                {'market':'Korea','pages':1})))
        sources.append(('official_jpx_full_listing',lambda: (source_jpx_list(),{'market':'Japan','pages':1})))
        sources.append(('official_twse_listed_companies',lambda: (source_twse_list(),{'market':'Taiwan','pages':1})))
    if mode in ('all5','regional5','all5_official'):
        for market in REGIONS:
            sources.append((f'yahoo_screener_{market}',lambda market=market:source_region(market,per_region)))
    if mode == 'all5_official' and not os.environ.get('PUBLIC_DATA_API_KEY'):
        logs.append({'source':'official_krx_listed_issues','status':'NOT_CONFIGURED_AUTH_REQUIRED',
          'received':0,'accepted_pattern':0,'rejected_non_equity':0,'rejected_bad_symbol':0,
          'error':'Set PUBLIC_DATA_API_KEY on GitHub to enable official KRX data'})
    for name,func in sources:
        try:
            rows,detail=func()
            cleaned=[]
            for row in rows:
                if ticker_market_valid(row.get('ticker',''),row.get('market','')):
                    row.setdefault('security_type_status','OFFICIAL_INDEX_TYPE_NEEDS_CONFIRMATION')
                    cleaned.append(row)
            candidates.extend(cleaned)
            logs.append({'source':name,'status':'OK','received':len(rows),'accepted_pattern':len(cleaned),
                         'rejected_non_equity':detail.get('rejected_non_equity',0),
                         'rejected_bad_symbol':detail.get('rejected_bad_symbol',0),'error':''})
        except Exception as exc:
            logs.append({'source':name,'status':'FAILED_NO_FALLBACK','received':0,'accepted_pattern':0,
                         'rejected_non_equity':0,'rejected_bad_symbol':0,'error':f'{type(exc).__name__}: {str(exc)[:150]}'})
    if candidates:
        added=pd.DataFrame(candidates)
        added=added[~added.ticker.isin(set(result.ticker))].drop_duplicates('ticker')
        result=pd.concat([result,added],ignore_index=True)
    return result.reset_index(drop=True),pd.DataFrame(logs,columns=['source','status','received','accepted_pattern','rejected_non_equity','rejected_bad_symbol','error'])


def select_market_balanced(universe:pd.DataFrame,max_symbols:int)->pd.DataFrame:
    """Equal initial coverage of available markets; not an equal-weight portfolio."""
    if max_symbols<0:raise ValueError('max_symbols must be >=0')
    if max_symbols==0 or max_symbols>=len(universe):return universe.copy().reset_index(drop=True)
    # Round robin, with curated-first within every market, then discovered.
    buckets={m:universe[universe.market.eq(m)].sort_values('is_new_discovery',kind='stable').to_dict('records')
             for m in REGIONS}
    other=universe[~universe.market.isin(REGIONS)].to_dict('records')
    if other:buckets['Other']=other
    output=[]
    while len(output)<max_symbols and any(buckets.values()):
        for market in list(buckets):
            if buckets[market]:output.append(buckets[market].pop(0))
            if len(output)>=max_symbols:break
    return pd.DataFrame(output,columns=universe.columns).reset_index(drop=True)
