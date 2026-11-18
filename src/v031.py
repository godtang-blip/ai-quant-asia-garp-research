"""Asia GARP v0.3.1: auditable cross-market RESEARCH, no orders.

Not a firm replica, production valuation model, or point-in-time backtest.
A company is not 'undervalued' merely because its priority score is high.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import math
import time
import os
from pathlib import Path
import pandas as pd
import numpy as np
from .discovery_v031 import discover_five_markets, select_market_balanced
from .accounting import issuer_evidence, accounting_basis
from .fx import YahooFX, normalized_values
from .ranking import valid_number
from .scoring_v03 import compute_scores, SUBMETRICS, CATEGORY_WEIGHTS
from .screen import FIELDS, memo_template
from .evidence import collect_evidence, read_manual_decisions, render_evidence_book
from .quality_v031 import sensitivity_report, diagnostics, diagnostics_markdown


def vendor_industry_group(industry: str, sector: str) -> str:
    """Conservative heuristic, NOT verified investment-industry classification."""
    i=(str(industry or '')+' '+str(sector or '')).lower()
    if 'semiconductor equipment' in i or 'semiconductor materials' in i:return 'chip_equipment'
    if 'semiconductor' in i:return 'chip_components'
    if any(x in i for x in ('electric equipment','electrical equipment','electrical components','electronic components','industrial automation')):
        return 'industrial_electrification'
    if any(x in i for x in ('internet content','internet retail','internet software','software - application','information technology services')):
        return 'platforms'
    if any(x in i for x in ('game', 'entertainment','broadcasting')):return 'gaming_media'
    if any(x in i for x in ('biotechnology','drug manufacturer','pharmaceutical')):return 'healthcare_biopharma'
    if any(x in i for x in ('auto manufacturer','auto parts','automobiles')):return 'automakers'
    if any(x in i for x in ('apparel','luxury goods','household products','packaged foods','footwear')):return 'consumer_brands'
    return 'unclassified'


def _fetch_vendor(ticker:str) -> dict:
    import yfinance as yf
    info=yf.Ticker(ticker).get_info() or {}
    if not isinstance(info,dict) or not info:raise ValueError('No fundamentals from vendor')
    out={key:valid_number(info.get(source_key)) for key,source_key in FIELDS.items()}
    # forwardEPS/PE is a vendor field; do not fabricate its reporting currency.
    out.update({
        'free_cashflow_raw':valid_number(info.get('freeCashflow')),
        'market_cap':valid_number(info.get('marketCap')),
        'current_price':valid_number(info.get('currentPrice') or info.get('regularMarketPrice')),
        'forward_eps':valid_number(info.get('forwardEps')),
        'currency':str(info.get('currency') or '').upper(),
        'financial_currency':str(info.get('financialCurrency') or '').upper(),
        'debt_to_equity_ratio':valid_number(info.get('debtToEquity')) / 100,
        'price_change_52w':valid_number(info.get('52WeekChange')),
        'vendor_sector':str(info.get('sector') or ''),
        'vendor_industry':str(info.get('industry') or ''),
        'provider_name':str(info.get('longName') or info.get('shortName') or ''),
        'reported_accounting_standard':'UNKNOWN_PRIMARY_FILING_REQUIRED',
        'revenue_growth_period':'VENDOR_UNCONFIRMED',
        'earnings_growth_period':'VENDOR_UNCONFIRMED',
        'fcf_period':'VENDOR_UNCONFIRMED',
        'data_source':'yfinance_info',
        'vendor_quote_type':str(info.get('quoteType') or '').upper(),
        'revenue_total_raw':valid_number(info.get('totalRevenue')),
        'vendor_forward_pe_raw':valid_number(info.get('forwardPE')),
        'vendor_price_to_sales_raw':valid_number(info.get('priceToSalesTrailing12Months')),
        'source_url':'https://finance.yahoo.com/quote/'+ticker,
    })
    raw_split=info.get('lastSplitDate')
    if raw_split:
        try: out['last_split_date_utc']=dt.datetime.fromtimestamp(int(raw_split),dt.timezone.utc).date().isoformat()
        except Exception:out['last_split_date_utc']=''
    else:out['last_split_date_utc']=''
    out['split_factor']=str(info.get('lastSplitFactor') or '')
    return out


def audit_flags(row:dict, prior:set[str]) -> tuple[str,str]:
    flags=[]; limitations=[]
    def f(key): return valid_number(row.get(key))
    if str(row['ticker']) in prior:flags.append('UNRESOLVED_PRIOR_DISCREPANCY')
    if math.isfinite(f('revenue_growth')) and (f('revenue_growth')>1 or f('revenue_growth')<-.6):
        flags.append('EXTREME_REVENUE_GROWTH_VERIFY_PERIOD')
    if math.isfinite(f('earnings_growth')) and (f('earnings_growth')>2 or f('earnings_growth')<-.8):
        flags.append('EXTREME_EARNINGS_GROWTH_VERIFY_BASE')
    if math.isfinite(f('earnings_growth')) and f('earnings_growth')<-.3:
        flags.append('EARNINGS_DECLINE_OVER_30PCT')
    if math.isfinite(f('roe')) and (f('roe')>1.0 or f('roe') < -1.0):
        flags.append('EXTREME_ROE_VERIFY_NEGATIVE_EQUITY_OR_ONEOFFS')
    if math.isfinite(f('operating_margin')) and (f('operating_margin')>0.85 or f('operating_margin') < -.4):
        flags.append('EXTREME_OPERATING_MARGIN_VERIFY_SEGMENTS')
    if math.isfinite(f('forward_pe')) and (f('forward_pe')<5 or f('forward_pe')>100):
        flags.append('EXTREME_PE_VERIFY_SOURCE')
    if math.isfinite(f('fcf_yield')) and (f('fcf_yield')> .18 or f('fcf_yield')< -.10):
        flags.append('FCF_YIELD_EXTREME_VERIFY_ONEOFFS')
    split=str(row.get('last_split_date_utc') or '')
    if split:
        try:
            age=(dt.datetime.now(dt.timezone.utc).date()-dt.date.fromisoformat(split)).days
            if 0<=age<=180:flags.append('RECENT_SPLIT_CHECK_EPS_PRICE_BASIS')
        except ValueError:limitations.append('SPLIT_DATE_PARSE_FAILED')
    c=str(row.get('currency') or '');fc=str(row.get('financial_currency') or '')
    if not c or not fc:limitations.append('MISSING_CURRENCY_METADATA')
    if c and fc and c != fc:
        # Yahoo forwardEps may be quoted in a different currency than financialCurrency.
        # The PE vs price/eps check cannot be safely performed without explicit EPS unit.
        limitations.append('EPS_CURRENCY_UNKNOWN_CROSS_CURRENCY_PE_NOT_RECALCULATED')
    if c and fc and c==fc and f('forward_eps')>0 and f('current_price')>0 and f('forward_pe')>0:
        calc=f('current_price')/f('forward_eps')
        if abs(calc-f('forward_pe'))/f('forward_pe')>.2:
            flags.append('FORWARD_PE_EPS_PRICE_INCONSISTENCY')
    if row.get('fx_status') == 'FX_MISSING_NO_CONVERSION' and c and fc and c!=fc:
        limitations.append('CROSS_CURRENCY_FCF_NOT_COMPARABLE_NO_FX')
    if str(row.get('fx_status') or '') == 'FX_CONVERTED_VENDOR_PERIOD_UNVERIFIED':
        limitations.append('ONE_YEAR_AVERAGE_FX_PROXY_FCF_PERIOD_UNKNOWN')
    if str(row.get('reported_accounting_standard') or '').startswith('UNKNOWN'):
        limitations.append('ACCOUNTING_STANDARD_UNCONFIRMED_NO_IFRS_RESTATEMENT')
    if str(row.get('revenue_growth_period') or '').startswith('VENDOR'):
        limitations.append('GROWTH_PERIOD_UNVERIFIED')
    if not row.get('source_url'):limitations.append('MISSING_VENDOR_SOURCE_URL')
    if str(row.get('peer_group') or '') == 'unclassified':limitations.append('SECTOR_NEEDS_ANALYST_CONFIRMATION')
    return '|'.join(dict.fromkeys(flags)), '|'.join(dict.fromkeys(limitations))


def _read_curated(path:Path)->pd.DataFrame:
    df=pd.read_csv(path,dtype=str).fillna('')
    required={'ticker','company','market','peer_group','industry_thesis'}
    if missing:=required-set(df.columns):raise ValueError(f'Universe missing {missing}')
    if df.ticker.duplicated().any():raise ValueError('Duplicate curated ticker')
    return df


def _prior_open(universe_file:Path)->set[str]:
    file=universe_file.parent/'prior_discrepancies_to_review.csv'
    if not file.exists():return set()
    d=pd.read_csv(file,dtype=str).fillna('')
    if not {'ticker','status'}<=set(d.columns):raise ValueError('Prior discrepancies malformed')
    return set(d[d.status.str.upper()!='RESOLVED'].ticker)


def research_note(ranked:pd.DataFrame, meta:dict)->str:
    lines=['# Asia GARP v0.3.1 — research watchlist, NOT buy recommendations','',
        '> Independent prototype. NOT affiliated with Redpoint Partners or any investment firm.',
        '> Scores rank investigation priority using **unvalidated researcher-defined anchors**; they are NOT future-return predictions.',
        '',f"Generated: {meta['generated_utc']} | Mode: {meta['data_mode']}",
        f"Curated {meta['curated_n']} | Discovered new {meta['new_discovered_n']} | Fetched {meta['fetched_n']} | Rankable {meta['rankable_n']} | Shortlist {meta['shortlist_n']}",
        '', '## Ranked cross-industry screening candidates (still unverified)','',
        '| Ticker | Company | Industry group | Research score / 100 | Metric coverage | Review status |',
        '|---|---|---|---:|---:|---|']
    good=ranked[ranked.v031_research_eligible].head(15)
    if good.empty: lines.append('| — | — | — | — | — | no eligible candidates |')
    for _,r in good.iterrows():
        lines.append(f"| {r.ticker} | {r.company} | {r.peer_group} | {r.cross_industry_score_100:.1f} | {r.score_coverage:.0%} | unverified |")
    lines.extend(['','## What these scores do and do NOT mean','',
        '- Same *numeric* 0–100 scale across industries with fixed reference anchors; NOT empirically calibrated comparable alpha.',
        '- Different industries use different, declared P/E and P/S reference anchors. Weights and anchors are hypotheses, not proven investment edges.',
        '- Missing metrics reduce coverage and the published score. Suspect vendors and unresolved prior issues cannot pass the candidate gate.',
        '- **No accounting-standard conversion**: vendor ratios are tagged with unknown reporting basis until primary issuer filings confirm them.',
        '- Cross-currency market capitalization is converted to USD at a dated quote; FCF may use a 1-year FX mean as a proxy ONLY with visible uncertainty.',
        '- A company found via listing discovery may lack verified sector classification and remain in the unclassified research queue.',
        '- Company fundamentals, vendor reporting dates, shares/splits and adjusted EPS still require primary source checks.',
        '- Growth persistence, catalysts, price-implied expectations, DCF, peer valuation and bear case are human research tasks.',
        '- Screening is NOT point-in-time backtested, and there are no trades or holdings here.',
        '', '## Analyst questions','',
        '1. Which disclosed segment drives growth? Show the dated annual report / earnings presentation.',
        '2. Why is valuation justified vs sector history, implied future margins and competitor economics?',
        '3. Why this valuation method, and what happens if its key assumption changes?',
        '4. Is there a specific, evidenced re-rating catalyst? List strongest contrary evidence.',
        '5. What observation would *disprove* this thesis?','',
        '## Discovery status','',
        '- Discovery candidates are sourced from an official index constituent list and/or a vendor regional screener when those sources are reachable.',
        '- These sources are **not** a census of all Asian listed shares; uncovered names remain invisible.',
        '- Source failures are explicitly logged; no hidden replacement companies are generated.',
        '', '## Developer / researcher roles','',
        '- Requirements, research questions and analyst review: user-directed. Software implementation: AI-assisted.',
        '- Verify and be prepared to explain every assumption before publication or hiring-portfolio use.',
    ])
    return '\n'.join(lines)+'\n'


def run(universe_file:Path, outputs:Path, max_symbols:int=150, discover_mode:str='all5',
        fx_mode:str='live',delay_seconds:float=1.0,snapshot_csv:Path|None=None, per_region:int=50,
        evidence_mode:str='full', evidence_limit:int=8)->dict:
    if max_symbols<0:raise ValueError('max_symbols must be >= 0')
    if fx_mode not in ('live','off'):raise ValueError('fx_mode live/off')
    if evidence_mode not in ('off','news','full'):raise ValueError('evidence_mode off/news/full')
    if evidence_limit < 0 or evidence_limit > 30:raise ValueError('evidence_limit must be 0..30')
    base=_read_curated(universe_file)
    combined, discovery_log=discover_five_markets(base,discover_mode,per_region)
    # Keep baseline observations intact. Additional discoveries follow in published source order.
    selected=select_market_balanced(combined,max_symbols)
    prior=_prior_open(universe_file)
    gaap_evidence=issuer_evidence(universe_file.parent/'accounting_issuer_evidence.csv')
    now=dt.datetime.now(dt.timezone.utc).isoformat()
    snap=None
    if snapshot_csv:
        snap=pd.read_csv(snapshot_csv,dtype={'ticker':str}).set_index('ticker',drop=False)
        if snap.index.duplicated().any():raise ValueError('Duplicate snapshot ticker')
    fx=YahooFX() if fx_mode=='live' and snap is None else None
    # For historical snapshot replay, any live FX lookup would leak future FX.
    if snap is not None:fx=None
    rows=[]
    for idx, (_, s) in enumerate(selected.iterrows(),1):
        ticker=str(s.ticker)
        print(f'[{idx}/{len(selected)}] {ticker} {s.peer_group}',flush=True)
        r=s.to_dict()
        r.update({'retrieved_at_utc':now,'fetch_error':'','reported_accounting_standard':'UNKNOWN_PRIMARY_FILING_REQUIRED',
                  'vendor_quote_type':'', 'revenue_total_raw':math.nan, 'valuation_quote_status':'UNVERIFIED',
                  'free_cashflow_raw':math.nan, 'fcf_yield':math.nan,
                  'fx_status':'FX_OFF_OR_NOT_REQUESTED','data_source':'',
                  'revenue_growth_period':'VENDOR_UNCONFIRMED','earnings_growth_period':'VENDOR_UNCONFIRMED'})
        if snap is not None:
            if ticker in snap.index:
                r.update({k:v for k,v in snap.loc[ticker].to_dict().items() if k!='ticker'})
                r['data_source']='HISTORICAL_VENDOR_SNAPSHOT_NO_NEW_FX'
            else:r['fetch_error']='NOT_IN_REPLAY_SNAPSHOT'
        else:
            try:r.update(_fetch_vendor(ticker))
            except Exception as exc:r['fetch_error']=type(exc).__name__+': '+str(exc)[:130]
        # Validate security type from issuer-level vendor information when available.
        vendor_type=str(r.get('vendor_quote_type') or '').upper().strip()
        if vendor_type and vendor_type!='EQUITY':
            r['security_type_status']='NON_EQUITY_VENDOR_EXCLUDED'
        elif vendor_type=='EQUITY':
            r['security_type_status']='VERIFIED_EQUITY_VENDOR'
        if r.get('peer_group')=='unclassified':
            mapped=vendor_industry_group(str(r.get('vendor_industry') or ''),str(r.get('vendor_sector') or ''))
            r['peer_group']=mapped
            r['sector_mapping_status']='VENDOR_HEURISTIC_NEEDS_REVIEW' if mapped!='unclassified' else 'UNCLASSIFIED_NEEDS_REVIEW'
        else:r['sector_mapping_status']='CURATED_HUMAN_TAXONOMY_UNVERIFIED'
        if fx is not None and not r['fetch_error']:
            r.update(normalized_values(r,fx))
        elif snap is not None:
            # Replay preserves historical vendor FCF yield if supplied; cannot
            # convert old FCF with today's FX to claim point-in-time accuracy.
            r['fx_status']='SNAPSHOT_REPLAY_CURRENT_FX_NOT_APPLIED'
        r.update(accounting_basis(ticker,str(r.get('market') or ''),gaap_evidence))
        # A cross-currency vendor EPS cannot be assumed to be expressed in the quote currency.
        # Hold its forward P/E from scoring; record the original value for audit.
        c=str(r.get('currency') or '').upper(); fc=str(r.get('financial_currency') or '').upper()
        if c and fc and c!=fc:
            r['valuation_quote_status']='FORWARD_PE_HELD_EPS_UNIT_UNVERIFIED'
            r['vendor_forward_pe_raw']=r.get('vendor_forward_pe_raw',r.get('forward_pe'))
            r['forward_pe']=math.nan
            cap=valid_number(r.get('market_cap_usd')); sales=valid_number(r.get('revenue_total_raw'))
            rate=valid_number(r.get('financial_to_usd_avg'))
            if cap>0 and sales>0 and rate>0:
                r['vendor_price_to_sales_raw']=r.get('vendor_price_to_sales_raw',r.get('price_to_sales'))
                r['price_to_sales']=cap/(sales*rate)
                r['valuation_quote_status']='PE_HELD_PS_RECALCULATED_FX_PERIOD_PROXY'
            else:
                r['vendor_price_to_sales_raw']=r.get('vendor_price_to_sales_raw',r.get('price_to_sales'))
                r['price_to_sales']=math.nan
        elif c and fc and c==fc:
            r['valuation_quote_status']='SAME_CURRENCY_VENDOR_RATIO_UNVERIFIED'
        else:r['valuation_quote_status']='CURRENCY_UNKNOWN_VENDOR_RATIO_UNVERIFIED'
        if not r.get('fx_status'):r['fx_status']='FX_OFF_OR_NOT_REQUESTED'
        fl, limits=audit_flags(r,prior)
        r['data_quality_flags']=fl
        r['data_limitations']=limits
        rows.append(r)
        if snap is None and delay_seconds>0 and idx<len(selected): time.sleep(delay_seconds)
    if not rows:raise RuntimeError('No companies to analyze')
    d=pd.DataFrame(rows)
    if not d['fetch_error'].fillna('').eq('').any():
        raise RuntimeError('All fundamental data missing — no false success')
    ranked=compute_scores(d)
    # Two gates: provisional investigation vs *human-verified* investment memo.
    # New issuer discovery is NOT an automatic exclusion from research; it is
    # explicitly marked provisional and cannot be called a validated idea.
    has_sector=ranked.peer_group.ne('unclassified')
    profitable=(pd.to_numeric(ranked.operating_margin,errors='coerce')>0) & (pd.to_numeric(ranked.roe,errors='coerce')>0)
    is_new=ranked.is_new_discovery.map(lambda x:str(x).lower() in ('true','1'))
    safe_type=~ranked.security_type_status.fillna('').isin(['NON_EQUITY_VENDOR_EXCLUDED','REJECT_NON_EQUITY'])
    # Newly discovered symbols need a vendor-confirmed equity type before joining the investigation shortlist.
    safe_type &= (~is_new | ranked.security_type_status.fillna('').eq('VERIFIED_EQUITY_VENDOR'))
    clean=ranked.data_quality_flags.fillna('').eq('')
    viable=(ranked.cross_industry_score_100.notna() & (ranked.score_coverage >= .70)
           & has_sector & profitable & clean & safe_type & ranked.fetch_error.fillna('').eq(''))
    ranked['v031_research_eligible']=viable
    ranked['v031_research_status']='REVIEW_REQUIRED'
    ranked.loc[viable & is_new,'v031_research_status']='PROVISIONAL_NEW_DISCOVERY'
    ranked.loc[viable & ~is_new,'v031_research_status']='PROVISIONAL_CURATED_CANDIDATE'
    ranked.loc[~safe_type,'v031_research_status']='SECURITY_TYPE_REQUIRES_VERIFICATION'
    ranked.loc[ranked.security_type_status.fillna('').isin(['NON_EQUITY_VENDOR_EXCLUDED','REJECT_NON_EQUITY']),'v031_research_status']='REJECT_NON_EQUITY_INSTRUMENT'
    ranked['v031_memo_ready']=False # requires audited filings & analyst approval, never auto-true
    ranked=ranked.sort_values(['v031_research_eligible','cross_industry_score_100','ticker'],
                              ascending=[False,False,True],na_position='last').reset_index(drop=True)
    shortlist=ranked[ranked.v031_research_eligible].head(10).copy()
    # Order and index must be computed AFTER sorting: pre-sort positional masks mislabel discoveries.
    is_new=ranked.is_new_discovery.map(lambda x:str(x).lower() in ('true','1'))
    decisions=read_manual_decisions(universe_file.parent/'research_decisions.csv')
    # Evidence is collected only for top provisional investigation names, never for entire multi-hundred watchlist.
    # When replaying a snapshot, external evidence fetching is automatically disabled to avoid as-of-date leakage.
    active_evidence_mode='off' if snapshot_csv else evidence_mode
    ev=collect_evidence(shortlist,mode=active_evidence_mode,limit=evidence_limit,
        registry=universe_file.parent/'issuer_source_registry.csv',key=os.environ.get('DART_API_KEY'))
    sensitivity, sensitivity_meta=sensitivity_report(ranked)
    quality=diagnostics(ranked,discovery_log,ev['ledger'],decisions,sensitivity_meta)
    quality.update({'evidence_mode_requested':evidence_mode,
                    'evidence_mode_executed':active_evidence_mode,
                    'evidence_limit':evidence_limit,
                    'snapshot_live_evidence_suppressed':bool(snapshot_csv),
                    'fx_unchanged_from_v03':True,'gaap_to_ifrs_restated':False})
    meta={'pipeline_revision':'0.3.1','generated_utc':now,
        'data_mode':'SNAPSHOT_REPLAY_NOT_LIVE' if snap is not None else 'LIVE_YFINANCE_UNVERIFIED',
        'discovery_mode':discover_mode,'discovery_sources_ok':int(discovery_log.status.eq('OK').sum()) if not discovery_log.empty else 0,
        'discovery_sources_failed':int(discovery_log.status.eq('FAILED_NO_FALLBACK').sum()) if not discovery_log.empty else 0,
        'curated_n':len(base),'new_discovered_n':int(combined.is_new_discovery.sum()),
        'total_universe_watchlist_n':len(combined),'fetched_n':len(selected),
        'fetch_failures_n':int(ranked.fetch_error.fillna('').ne('').sum()),
        'rankable_n':int(ranked.cross_industry_score_100.notna().sum()),
        'shortlist_n':len(shortlist),'new_research_eligible_n':int((ranked.v031_research_eligible & is_new).sum()),
        'memo_verified_ready_n':0,'market_counts_selected':{str(k):int(v) for k,v in selected.market.value_counts().items()},'flagged_n':int(ranked.data_quality_flags.fillna('').ne('').sum()),
        'sector_needs_review_n':int(ranked.sector_mapping_status.str.contains('REVIEW').sum()),
        'fx_converted_n':int(ranked.fx_status.eq('FX_CONVERTED_VENDOR_PERIOD_UNVERIFIED').sum()),
        'filing_verification':'NOT_PERFORMED_ON_PRIMARY_STATEMENTS', 'actual_trades':'NONE',
        'expected_return_backtest':'NOT_PERFORMED','score_calibration':'NOT_PERFORMED',
        'accounting_restated_to_ifrs':False,'fx_historical_point_in_time_verified':False,
        'evidence_mode':active_evidence_mode,'evidence_items_collected':len(ev['ledger']),
        'analyst_hypotheses_rejected_n':int(decisions.decision.eq('REJECTED').sum()) if not decisions.empty else 0}
    outputs.mkdir(parents=True,exist_ok=True)
    def save(df,name):df.to_csv(outputs/name,index=False,encoding='utf-8-sig')
    save(ranked,'01_all_research_candidates.csv')
    save(shortlist,'02_research_shortlist.csv')
    (outputs/'03_research_report.md').write_text(research_note(ranked,meta),encoding='utf-8')
    (outputs/'04_run_metadata.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
    save(ranked[(ranked.data_quality_flags.fillna('').ne('')) | (~ranked.v031_research_eligible)],'05_data_quality_review.csv')
    peers=ranked.groupby('peer_group',dropna=False).agg(analyzed=('ticker','size'),final_eligible=('v031_research_eligible','sum'),avg_score_coverage=('score_coverage','mean')).reset_index()
    save(peers,'06_peer_coverage.csv')
    (outputs/'07_investment_memo_TEMPLATE.md').write_text(memo_template(),encoding='utf-8')
    save(selected,'08_selected_universe.csv')
    queue_fields=['ticker','company','market','peer_group','is_new_discovery','cross_industry_score_100',
                  'v031_research_status','v03_review_flags','data_quality_flags','data_limitations',
                  'reported_accounting_standard','revenue_growth_period','earnings_growth_period',
                  'currency','financial_currency','fx_status','fx_source_quote','fx_source_financial',
                  'source_url','retrieved_at_utc']
    save(ranked[[x for x in queue_fields if x in ranked.columns]],'09_filing_verification_queue.csv')
    (outputs/'10_portfolio_methodology_NOTE.md').write_text(
        'v0.3.1: fixed-reference cross-industry investigation scores, sector-aware valuation bands, disclosed coverage, FX and accounting audit queues. No verified undervaluation or actual holdings. AI-assisted implementation; user-led requirements. See README.\n',encoding='utf-8')
    save(combined,'11_discovery_universe.csv')
    save(discovery_log,'12_discovery_sources_log.csv')
    save(ranked[[x for x in ('ticker','currency','financial_currency','quote_to_usd','financial_to_usd_avg',
        'fx_price_asof','fx_source_quote','fx_source_financial','market_cap','market_cap_usd','free_cashflow_raw',
        'fcf_usd_proxy','fcf_yield','fx_status','valuation_quote_status','vendor_forward_pe_raw','vendor_price_to_sales_raw','price_to_sales') if x in ranked.columns]], '13_fx_normalization_audit.csv')
    save(ranked[[x for x in ('ticker','market','reported_accounting_standard','gaap_comparability_status',
        'gaap_evidence_url','gaap_evidence_date','gaap_reviewed_by','jurisdiction_accounting_hint',
        'revenue_growth_period','earnings_growth_period','data_limitations','sector_mapping_status') if x in ranked.columns]],
        '14_accounting_comparability_audit.csv')
    cols=['ticker','company','market','peer_group','cross_industry_score_100','score_coverage',
        *[f'{c}_score_100' for c in CATEGORY_WEIGHTS], 'sector_weights_used','v031_research_eligible','v031_research_status','v03_review_flags']
    save(ranked[cols],'15_cross_industry_scores.csv')
    (outputs/'16_analyst_research_queue.md').write_text(
        '# Research verification queue (human sign-off required)\n\n'+
        f'Analysis count: {len(ranked)} / newest discoveries: {int(ranked.is_new_discovery.sum())}\n\n'+
        '\n'.join(f"- {r.ticker}: {r.v03_review_flags or 'Vendor metrics unverified'}; {str(r.data_limitations)[:160]}" for _,r in ranked.head(40).iterrows())+
        '\n\nNo recommendation until dated filing and valuation checks.\n',encoding='utf-8')
    save(pd.DataFrame(fx.log if fx is not None else [],columns=['currency','status','spot','avg','spot_asof','period_from','period_to','source','detail']),
         '17_fx_quotes_log.csv')
    save(ranked[ranked.v031_research_eligible & is_new], '29_new_discovery_research_queue.csv')
    for key,filename in [('ledger','18_evidence_ledger.csv'),('news','19_news_headlines.csv'),
          ('earnings','20_vendor_quarterly_earnings.csv'),('filings','21_regulator_filings_index.csv'),
          ('log','22_evidence_sources_log.csv')]:
        save(ev[key],filename)
    save(sensitivity,'23_same_input_weight_sensitivity.csv')
    (outputs/'24_research_quality_audit.json').write_text(json.dumps(quality,indent=2,ensure_ascii=False),encoding='utf-8')
    (outputs/'25_research_quality_audit.md').write_text(diagnostics_markdown(quality),encoding='utf-8')
    save(decisions,'26_research_decisions.csv')
    (outputs/'27_evidence_book.md').write_text(render_evidence_book(shortlist,ev['ledger'],decisions),encoding='utf-8')
    (outputs/'28_decision_log_GUIDE.md').write_text(
      '# Research Decision Log — analyst sign-off required\n\n'
      'Edit `data/research_decisions.csv` manually after reading source filings.\n'
      'Use `INVESTIGATING`, `ON_HOLD`, `REJECTED`, or `ACCEPTED`.\n\n'
      '`REJECTED` is a valuable conclusion if the counterevidence disproves an initial thesis.\n'
      'Provide decision date, original hypothesis, decisive counterevidence,\n'
      'reason, source URLs, and a revisit trigger.\n\n'
      'A high score or AI-generated headline NEVER auto-accepts or auto-rejects a thesis.\n',encoding='utf-8')
    print('v0.3.1 result',json.dumps(meta,ensure_ascii=False),flush=True)
    return meta


def main():
    p=argparse.ArgumentParser(description='v0.3.1 independent Asia equity research; no trading')
    p.add_argument('--universe',type=Path,default=Path('data/universe.csv'))
    p.add_argument('--output',type=Path,default=Path('outputs'))
    p.add_argument('--max-symbols',type=int,default=150,help='0=all discovered, >0=market-balanced limit')
    p.add_argument('--discover-mode',choices=['off','nikkei','regional5','all5'],default='all5')
    p.add_argument('--fx-mode',choices=['live','off'],default='live')
    p.add_argument('--delay-seconds',type=float,default=1.0)
    p.add_argument('--snapshot-csv',type=Path,default=None)
    p.add_argument('--per-region',type=int,default=90)
    p.add_argument('--evidence-mode',choices=['off','news','full'],default='full')
    p.add_argument('--evidence-limit',type=int,default=8,help='Investigate at most this many shortlist names (0..30)')
    args=p.parse_args()
    run(args.universe,args.output,args.max_symbols,args.discover_mode,args.fx_mode,args.delay_seconds,args.snapshot_csv,args.per_region,args.evidence_mode,args.evidence_limit)

if __name__=='__main__':main()
