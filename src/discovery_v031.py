"""Five-market issuer discovery. Watchlist search, NOT a complete exchange census.

Every accepted ticker must have actual source provenance. The region screener is
vendor-curated, can omit stocks, and can return wrong security types; audit that.
"""
from __future__ import annotations
import re
import os
import json
from hashlib import sha256
from pathlib import Path
import pandas as pd
from .discovery import source_nikkei225
from .official_universe import source_jpx_list, source_twse_list, source_krx_list, previous_weekday, JPX_CODE
from .listing_exports import VENUES, load_listing_export

REGIONS = {'Korea': ('kr', (r'^\d{6}\.KS$', r'^\d{6}\.KQ$')),
           'Japan': ('jp', (rf'^{JPX_CODE}\.T$',)),
           'China': ('cn', (r'^\d{6}\.SS$', r'^\d{6}\.SZ$', r'^\d{6}\.BJ$')),
           'Hong Kong': ('hk', (r'^\d{1,5}\.HK$',)),
           'Taiwan': ('tw', (r'^\d{4}\.TW$', r'^\d{4}\.TWO$'))}

BAD_TYPES = {'ETF','MUTUALFUND','FUND','INDEX','CRYPTOCURRENCY','CURRENCY','FUTURE','OPTION','BOND','WARRANT'}

def ticker_market_valid(ticker:str, market:str)->bool:
    return any(re.fullmatch(pattern,str(ticker).upper()) for pattern in REGIONS.get(str(market),('',()))[1])

def canonical_ticker(ticker: str, market: str) -> str:
    ticker = str(ticker).upper().strip()
    if market == 'Hong Kong' and ticker_market_valid(ticker, market):
        return ticker.removesuffix('.HK').lstrip('0').zfill(4) + '.HK'
    return ticker


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
    logs = []
    candidates = []
    provenance = {ticker: ['CURATED_LIST'] for ticker in result.ticker}
    sources = []

    if mode in ('all5', 'nikkei', 'all5_official'):
        sources.append(('official_nikkei225', 'Japan', 'INDEX',
                        lambda: (source_nikkei225(), {})))
    if mode == 'all5_official':
        krx_date = os.environ.get('KRX_BASE_DATE') or previous_weekday()
        if os.environ.get('PUBLIC_DATA_API_KEY'):
            sources.append(('official_krx_listed_issues', 'Korea', 'LIVE_LISTING',
                            lambda: (source_krx_list(os.environ['PUBLIC_DATA_API_KEY'], krx_date),
                                     {'source_asof': krx_date})))
        else:
            logs.append({'source': 'official_krx_listed_issues', 'market': 'Korea',
                         'source_kind': 'LIVE_LISTING', 'status': 'NOT_CONFIGURED_AUTH_REQUIRED',
                         'error': 'PUBLIC_DATA_API_KEY absent; KRX exports can be imported'})
        sources.extend([
            ('official_jpx_full_listing', 'Japan', 'LIVE_LISTING', lambda: (source_jpx_list(), {})),
            ('official_twse_listed_companies', 'Taiwan', 'LIVE_LISTING', lambda: (source_twse_list(), {})),
        ])
        directory = os.environ.get('GARP_LISTING_EXPORT_DIR')
        for venue, (market, *_) in VENUES.items():
            path = Path(directory) / f'{venue}.csv' if directory else None
            if path is None or not path.exists():
                logs.append({'source': f'export_{venue}', 'market': market,
                             'source_kind': 'PUBLISHER_EXPORT', 'status': 'EXPORT_NOT_PROVIDED'})
                continue
            sources.append((f'export_{venue}', market, 'PUBLISHER_EXPORT',
                            lambda path=path, venue=venue: load_listing_export(path, venue)))
    if mode in ('all5', 'regional5', 'all5_official'):
        for market in REGIONS:
            sources.append((f'yahoo_screener_{market}', market, 'VENDOR_SAMPLE',
                            lambda market=market: source_region(market, per_region)))

    for name, market, kind, fetch in sources:
        entry = {'source': name, 'market': market, 'source_kind': kind}
        try:
            rows, detail = fetch()
            cleaned = []
            source_urls = set()
            for row in rows:
                ticker = canonical_ticker(row.get('ticker', ''), market)
                if row.get('market') != market or not ticker_market_valid(ticker, market):
                    continue
                row = {**row, 'ticker': ticker}
                row.setdefault('security_type_status', 'OFFICIAL_INDEX_TYPE_NEEDS_CONFIRMATION')
                cleaned.append(row)
                source_urls.add(row['discovery_source'])
                refs = provenance.setdefault(ticker, [])
                if name not in refs:
                    refs.append(name)
            candidates.extend(cleaned)
            url = detail.get('source_url') or ' | '.join(sorted(source_urls))
            entry.update(status='OK' if cleaned else 'NO_VALID_ROWS',
                         received=detail.get('received', len(rows)), accepted_pattern=len(cleaned),
                         rejected_non_equity=detail.get('rejected_non_equity', 0),
                         rejected_bad_symbol=detail.get('rejected_bad_symbol', 0) + len(rows) - len(cleaned),
                         source_url=url if kind != 'VENDOR_SAMPLE' else '',
                         source_asof=detail.get('source_asof', ''), source_sha256=detail.get('source_sha256', ''))
        except Exception as exc:
            entry.update(status='FAILED_NO_FALLBACK', error=f'{type(exc).__name__}: {str(exc)[:250]}')
        logs.append(entry)
    if candidates:
        added = pd.DataFrame(candidates)
        added = added[~added.ticker.isin(set(result.ticker))].drop_duplicates('ticker')
        result = pd.concat([result, added], ignore_index=True)
    result['listing_source_ids'] = result.ticker.map(lambda ticker: json.dumps(provenance[ticker]))
    columns = ['source', 'status', 'received', 'accepted_pattern', 'rejected_non_equity',
               'rejected_bad_symbol', 'error', 'market', 'source_kind', 'source_url',
               'source_asof', 'source_sha256']
    log = pd.DataFrame(logs, columns=columns)
    for column in ('received', 'accepted_pattern', 'rejected_non_equity', 'rejected_bad_symbol'):
        log[column] = log[column].fillna(0).astype(int)
    return result.reset_index(drop=True), log.fillna('')


def select_market_proportional(universe: pd.DataFrame, max_symbols: int) -> pd.DataFrame:
    """Apply the fetch budget in proportion to discovered security counts."""
    if max_symbols < 0:
        raise ValueError('max_symbols must be >=0')
    if max_symbols == 0 or max_symbols >= len(universe):
        return universe.copy().reset_index(drop=True)
    groups = dict(tuple(universe.groupby('market', sort=True)))
    allocations = {market: divmod(len(group) * max_symbols, len(universe))
                   for market, group in groups.items()}
    counts = {market: quotient for market, (quotient, _) in allocations.items()}
    remaining = max_symbols - sum(counts.values())
    by_remainder = sorted(groups, key=lambda market: -allocations[market][1])
    for market in by_remainder[:remaining]:
        counts[market] += 1
    selected = []
    for market, group in groups.items():
        # Keep the sample independent of publisher row order and security code sequence.
        order = group.ticker.map(lambda ticker: sha256(ticker.encode()).hexdigest()).sort_values()
        selected.extend(order.index[:counts[market]])
    return universe.loc[selected].reset_index(drop=True)


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
