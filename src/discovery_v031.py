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
from .evidence import dart_stock_code_map
from .china_vendor_exports import SOURCE as TUSHARE_URL, SOURCE_IDS, load_tushare_export
from .china_security_master import ENDPOINT as BAOSTOCK_ENDPOINT, fetch_baostock
from .venue_sources import SOURCES, fetch_listing, failure_code, observed_utc
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


def discover_five_markets(base:pd.DataFrame, mode:str='all5',per_region:int=90, *, security_master:bool=False,
                          china_only:bool=False, provisional_inventory:list|None=None)->tuple[pd.DataFrame,pd.DataFrame]:
    if mode not in ('off','all5','regional5','nikkei','all5_official'):
        raise ValueError('discover_mode must be off, all5, regional5, nikkei, all5_official')
    if china_only:
        base = base.loc[base.market.eq('China')].copy()
    result=base.copy().fillna('');result['is_new_discovery']=False
    result['discovery_source']='CURATED_LIST'
    result['security_type_status']='CURATED_TICKER_TYPE_NEEDS_CONFIRMATION'
    logs = []
    candidates = []
    provenance = {ticker: ['CURATED_LIST'] for ticker in result.ticker}
    sources = []
    china_names = {}
    china_listing_evidence = {}
    official_china = {'live_SSE', 'live_SSE_STAR', 'live_SZSE', 'live_SZSE_JSON', 'live_BSE'}
    mainland_exports = {'export_SSE': ('SSE_MAIN', 'SSE_STAR'),
                        'export_SZSE': ('SZSE_MAIN', 'SZSE_CHINEXT'), 'export_BSE': ('BSE',)}

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
        sources.extend((f'live_{venue}', market, 'LIVE_LISTING',
                        lambda venue=venue: fetch_listing(venue))
                       for venue, (market, _, _) in SOURCES.items())
        if security_master or os.environ.get('GARP_ENABLE_BAOSTOCK') == '1':
            sources.append(('baostock_security_master', 'China', 'THIRD_PARTY_SECURITY_MASTER', fetch_baostock))
        vendor_directory = os.environ.get('GARP_TUSHARE_EXPORT_DIR')
        if vendor_directory:
            sources.extend((source_id, 'China', 'THIRD_PARTY_SECURITY_MASTER',
                            lambda venue=venue: load_tushare_export(Path(vendor_directory)/f'{venue}.csv', venue))
                           for venue, source_id in SOURCE_IDS.items())
        directory = os.environ.get('GARP_LISTING_EXPORT_DIR')
        for venue, (market, *_) in VENUES.items():
            path = Path(directory) / f'{venue}.csv' if directory else None
            if path is None or not path.exists():
                logs.append({'source': f'export_{venue}', 'market': market,
                             'source_kind': 'PUBLISHER_EXPORT', 'status': 'EXPORT_NOT_PROVIDED'})
                continue
            sources.append((f'export_{venue}', market, 'PUBLISHER_EXPORT',
                            lambda path=path, venue=venue: load_listing_export(path, venue)))
    if per_region > 0 and mode in ('all5', 'regional5', 'all5_official'):
        for market in REGIONS:
            sources.append((f'yahoo_screener_{market}', market, 'VENDOR_SAMPLE',
                            lambda market=market: source_region(market, per_region)))

    if china_only:
        sources = [source for source in sources if source[1] == 'China']
        logs = [entry for entry in logs if entry['market'] == 'China']
    outcomes = {}
    for name, market, kind, fetch in sources:
        entry = {'source': name, 'market': market, 'source_kind': kind,
                 'observed_utc': observed_utc()}
        if name == 'baostock_security_master':
            entry.update(source_url=BAOSTOCK_ENDPOINT,
                         scope='Active A-share master and dated provider inventory',
                         evidence_classification='THIRD_PARTY_SECURITY_MASTER')
        if name in SOURCE_IDS.values():
            entry.update(source_url=TUSHARE_URL, evidence_classification='THIRD_PARTY_SECURITY_MASTER')
        if name in official_china:
            entry['evidence_classification'] = 'OFFICIAL_EXCHANGE_LISTING'
        if name in mainland_exports:
            primary = {
                'export_SSE': ('live_SSE', 'live_SSE_STAR'),
                'export_SZSE': ('live_SZSE', 'live_SZSE_JSON'),
                'export_BSE': ('live_BSE',),
            }[name]
            succeeded = [outcomes.get(route, {}).get('status') == 'OK' for route in primary]
            vendor = outcomes.get('baostock_security_master', {})
            vendor_counts = json.loads(vendor.get('scope_counts') or '{}')
            vendor_has_scope = (vendor.get('retrieval_mode') == 'LIVE_VENDOR_SDK' and
                                all(vendor_counts.get(board, 0) > 0 for board in mainland_exports[name]))
            official_has_scope = all(succeeded) if name == 'export_SSE' else any(succeeded)
            if official_has_scope or vendor_has_scope:
                entry.update(status='SKIPPED_LIVE_LISTING_AVAILABLE')
                logs.append(entry)
                continue
        if name.startswith('live_'):
            _, url, scope = SOURCES[name.removeprefix('live_')]
            entry.update(source_url=url, scope=scope)
        if name in {'live_SZSE_JSON', 'live_SSE_STAR'}:
            primary = outcomes['live_SZSE' if name == 'live_SZSE_JSON' else 'live_SSE']
            if (name == 'live_SZSE_JSON' and primary['status'] == 'OK') or primary.get('failure_code') in {
                'FORBIDDEN', 'PROXY_FORBIDDEN', 'RATE_LIMITED', 'AUTHENTICATION_FAILED',
            }:
                entry.update(status='SKIPPED_PRIMARY_ROUTE', error=primary.get('failure_code') or 'Workbook succeeded')
                logs.append(entry)
                continue
        try:
            rows, detail = fetch()
            provisional = detail.get('provisional_rows', [])
            if detail.get('failure_stage'):
                entry['evidence_classification'] = 'UNVERIFIED_CANDIDATE'
            if provisional_inventory is not None:
                provisional_inventory.extend(provisional)
            cleaned = []
            source_urls = set()
            for row in rows:
                ticker = canonical_ticker(row.get('ticker', ''), market)
                if row.get('market') != market or not ticker_market_valid(ticker, market):
                    continue
                row = {**row, 'ticker': ticker}
                row.setdefault('security_type_status', 'OFFICIAL_INDEX_TYPE_NEEDS_CONFIRMATION')
                if name in official_china or kind == 'THIRD_PARTY_SECURITY_MASTER' or name in mainland_exports:
                    china_names.setdefault(ticker, {})[name] = row['company']
                    classification = entry.get('evidence_classification', 'PUBLISHER_EXPORT')
                    china_listing_evidence.setdefault(ticker, set()).add(classification)
                cleaned.append(row)
                source_urls.add(row['discovery_source'])
                refs = provenance.setdefault(ticker, [])
                if name not in refs:
                    refs.append(name)
            candidates.extend(cleaned)
            url = detail.get('source_url') or ' | '.join(sorted(source_urls))
            entry.update(status=('OK' if cleaned else 'PROVISIONAL_INVENTORY_ONLY'
                                 if detail.get('failure_stage') else 'NO_VALID_ROWS'),
                         failure_code=detail.get('failure_code', ''),
                         failure_stage=detail.get('failure_stage', ''),
                         provisional_inventory_n=len(provisional),
                         sdk_metrics=json.dumps(detail['sdk_metrics']) if 'sdk_metrics' in detail else '',
                         received=detail.get('received', len(rows)), accepted_pattern=len(cleaned),
                         rejected_non_equity=detail.get('rejected_non_equity', 0),
                         rejected_bad_symbol=detail.get('rejected_bad_symbol', 0) + len(rows) - len(cleaned),
                         source_url=url if kind != 'VENDOR_SAMPLE' else '',
                         scope=detail.get('scope', ''), duplicate_rows=detail.get('duplicate_rows', 0),
                         excluded_by_category=detail.get('excluded_by_category', ''),
                         source_asof=detail.get('source_asof', ''), source_sha256=detail.get('source_sha256', ''),
                         scope_counts=detail.get('scope_counts', ''),
                         unknown_classification=detail.get('unknown_classification', ''),
                         inactive_or_after_cutoff=detail.get('inactive_or_after_cutoff', ''),
                         completeness_check=detail.get('completeness_check', ''),
                         retrieval_mode=detail.get('retrieval_mode', ''),
                         response_diagnostics=json.dumps(detail['response_diagnostics'])
                         if 'response_diagnostics' in detail else '')
        except Exception as exc:
            code = failure_code(exc)
            entry.update(status='FAILED_NO_FALLBACK', failure_code=code,
                         error=f'{type(exc).__name__}: {str(exc)[:250]}')
            if hasattr(exc, 'diagnostics'):
                entry['response_diagnostics'] = json.dumps(exc.diagnostics)
            if code in {'INCOMPLETE_OR_STALE_SOURCE', 'INCOMPLETE_PAGINATION'}:
                entry['evidence_classification'] = 'INCOMPLETE_OR_STALE_SOURCE'
        logs.append(entry)
        outcomes[name] = entry
    if candidates:
        added = pd.DataFrame(candidates)
        added = added[~added.ticker.isin(set(result.ticker))].drop_duplicates('ticker')
        result = pd.concat([result, added], ignore_index=True)
    result['listing_source_ids'] = result.ticker.map(lambda ticker: json.dumps(provenance[ticker]))
    if mode == 'all5_official':
        result['listing_evidence_class'] = result.ticker.map(
            lambda ticker: '|'.join(sorted(china_listing_evidence.get(ticker, {'UNVERIFIED_CANDIDATE'}))))
        result.loc[~result.market.eq('China'), 'listing_evidence_class'] = ''
        result['listing_source_names'] = result.ticker.map(
            lambda ticker: json.dumps(china_names.get(ticker, {}), ensure_ascii=False))
        result['listing_name_disagreement'] = result.ticker.map(
            lambda ticker: len({' '.join(name.casefold().split()) for name in china_names.get(ticker, {}).values()}) > 1)
    if mode == 'all5_official' and not china_only:
        dart_log = {'source': 'opendart_issuer_crosscheck', 'market': 'Korea',
                    'source_kind': 'ISSUER_IDENTITY_ONLY', 'observed_utc': observed_utc(),
                    'source_url': 'https://opendart.fss.or.kr/api/corpCode.xml',
                    'scope': 'Identity match for already discovered Korean tickers; no listing or type assertion'}
        dart_key = os.environ.get('DART_API_KEY')
        if dart_key:
            try:
                mapping = dart_stock_code_map(dart_key)
                korean = result.market.eq('Korea')
                result.loc[korean, 'dart_corp_code'] = result.loc[korean, 'ticker'].map(
                    lambda ticker: mapping.get(ticker.split('.')[0], {}).get('corp_code', ''))
                result.loc[korean, 'dart_corp_name'] = result.loc[korean, 'ticker'].map(
                    lambda ticker: mapping.get(ticker.split('.')[0], {}).get('corp_name', ''))
                dart_log.update(status='OK', received=len(mapping),
                                identity_matches=int(result.loc[korean, 'dart_corp_code'].ne('').sum()))
            except Exception as exc:
                # Exception messages can contain the key in a request URL.
                dart_log.update(status='FAILED_NO_FALLBACK', failure_code=failure_code(exc),
                                error=type(exc).__name__)
        else:
            dart_log.update(status='NOT_CONFIGURED_AUTH_REQUIRED', error='DART_API_KEY absent')
        logs.append(dart_log)
    columns = ['source', 'status', 'received', 'accepted_pattern', 'rejected_non_equity',
               'rejected_bad_symbol', 'error', 'market', 'source_kind', 'source_url',
               'source_asof', 'source_sha256', 'scope', 'observed_utc', 'failure_code', 'duplicate_rows', 'excluded_by_category', 'identity_matches',
               'evidence_classification', 'scope_counts', 'unknown_classification', 'completeness_check', 'retrieval_mode', 'inactive_or_after_cutoff', 'response_diagnostics', 'failure_stage', 'provisional_inventory_n', 'sdk_metrics']
    log = pd.DataFrame(logs, columns=columns)
    for column in ('received', 'accepted_pattern', 'rejected_non_equity', 'rejected_bad_symbol'):
        log[column] = log[column].fillna(0).astype(int)
    return result.reset_index(drop=True), log.fillna('')


def minimum_market_fetches(max_symbols: int) -> int:
    """Reserve up to half the budget across the five markets, with a one-name floor."""
    return max(1, max_symbols // (2 * len(REGIONS))) if max_symbols > 0 else 0


def select_market_coverage_aware(universe: pd.DataFrame, max_symbols: int) -> pd.DataFrame:
    """Give each available market a floor, then allocate by remaining capacity."""
    if max_symbols < 0:
        raise ValueError('max_symbols must be >=0')
    if max_symbols == 0 or max_symbols >= len(universe):
        return universe.copy().reset_index(drop=True)
    universe = universe.reset_index(drop=True)
    groups = dict(tuple(universe.groupby('market', sort=True, dropna=False)))
    floor = minimum_market_fetches(max_symbols)
    counts = dict.fromkeys(groups, 0)
    remaining = max_symbols
    # If the cap cannot cover every market, give the scarcest lists first access.
    market_order = sorted((market for market in REGIONS if market in groups),
                          key=lambda market: (len(groups[market]), market))
    for market in market_order:
        counts[market] = min(floor, len(groups[market]), remaining)
        remaining -= counts[market]

    capacity = {market: len(group) - counts[market] for market, group in groups.items()}
    total_capacity = sum(capacity.values())
    allocations = {market: divmod(size * remaining, total_capacity)
                   for market, size in capacity.items()}
    for market, (whole, _) in allocations.items():
        counts[market] += whole
    leftover = max_symbols - sum(counts.values())
    by_remainder = sorted(groups, key=lambda market: -allocations[market][1])
    for market in by_remainder[:leftover]:
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
