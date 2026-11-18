"""Asia GARP v0.2.1: balanced idea discovery with reproducible data-quality triage.

Research only. No trading, broker/API secrets, or automated investment advice.
"""
from __future__ import annotations
import argparse
import datetime as dt
import json
import time
from pathlib import Path
import numpy as np
import pandas as pd
from .ranking import METRICS, rate_peer_universe, valid_number, diversified_shortlist
from .universe import balanced_sample

FIELDS = {
    'revenue_growth': 'revenueGrowth',
    'earnings_growth': 'earningsGrowth',
    'operating_margin': 'operatingMargins',
    'roe': 'returnOnEquity',
    'forward_pe': 'forwardPE',
    'price_to_sales': 'priceToSalesTrailing12Months',
}


def pull_ticker(ticker: str) -> dict:
    import yfinance as yf
    info = yf.Ticker(ticker).get_info() or {}
    if not isinstance(info, dict) or not info:
        raise RuntimeError('No public-provider fundamentals returned')
    out = {key: valid_number(info.get(k)) for key, k in FIELDS.items()}
    fcf = valid_number(info.get('freeCashflow'))
    cap = valid_number(info.get('marketCap'))
    price_cur = str(info.get('currency') or '')
    fin_cur = str(info.get('financialCurrency') or '')
    same_currency = bool(price_cur and fin_cur and price_cur == fin_cur)
    # A market cap reported in HKD and company cash flow in CNY are NOT
    # comparable without a dated FX rate. Keep FCF yield missing, but allow
    # peer screening on the OTHER verified-coverage metrics.
    out['fcf_yield'] = fcf / cap if same_currency and np.isfinite(fcf) and np.isfinite(cap) and cap > 0 else np.nan
    last_split_date = ''
    last_split_factor = str(info.get('lastSplitFactor') or '')
    split_recent = False
    try:
        raw_date = info.get('lastSplitDate')
        if raw_date is not None:
            split_dt = dt.datetime.fromtimestamp(int(raw_date), tz=dt.timezone.utc)
            last_split_date = split_dt.strftime('%Y-%m-%d')
            age = (dt.datetime.now(dt.timezone.utc).date() - split_dt.date()).days
            split_recent = 0 <= age <= 180
    except (TypeError, ValueError, OverflowError, OSError):
        last_split_date = ''
    out.update({
        'market_cap': cap, 'currency': price_cur, 'financial_currency': fin_cur,
        'forward_eps': valid_number(info.get('forwardEps')),
        'current_price': valid_number(info.get('currentPrice') or info.get('regularMarketPrice')),
        'trailing_pe': valid_number(info.get('trailingPE')),
        'provider_name': info.get('longName') or info.get('shortName') or '',
        'info_warning': '' if same_currency else 'FCF_YIELD_NOT_CALCULATED_CURRENCY_MISMATCH_OR_MISSING',
        'fcf_yield_status': 'VENDOR_SAME_CURRENCY_UNVERIFIED' if same_currency and np.isfinite(out['fcf_yield']) else 'MISSING_OR_CURRENCY_MISMATCH',
        'last_split_date_utc': last_split_date,
        'last_split_factor': last_split_factor,
        'split_recent': split_recent,
        'metric_period': 'VENDOR_DEFINED_UNCONFIRMED',
        'revenue_growth_period': 'VENDOR_DEFINED_UNCONFIRMED',
        'earnings_growth_period': 'VENDOR_DEFINED_UNCONFIRMED',
        'data_source': 'yfinance_info',
    })
    return out


def _fmt(x, pct=False):
    try:
        if pd.isna(x): return 'N/A'
    except (TypeError, ValueError): return 'N/A'
    try:
        v=float(x)
        return f'{v*100:.1f}%' if pct else f'{v:.1f}'
    except (ValueError, TypeError): return 'N/A'


def report(ranked: pd.DataFrame, shortlist: pd.DataFrame, pulled_at: str, meta: dict) -> str:
    out = [
        '# Asia GARP v0.2.1 — independent research ONLY', '',
        f"Generated (UTC): {pulled_at} | Mode: {meta['data_mode']}", '',
        '> Independent prototype. NOT affiliated with any investment firm; NOT its proprietary process.',
        '> Scores are peer-relative IDEA SCREENING only. NOT intrinsic value, verified undervaluation, or buy signals.',
        '> Yahoo provider fields are NOT confirmed point-in-time or cross-checked against primary filings.',
        '', '## Data and selection health', '',
        f"- Curated universe: {meta['curated_universe_n']} | This run: {meta['universe_n']} across {meta['industry_groups_selected']} groups",
        f"- Numeric scores available: {meta['rankable_n']} | Qualifying for unverified shortlist: {meta['shortlist_n']}",
        f"- Quality-flagged: {meta['flagged_n']} | Fetch failures: {meta['data_errors_n']} | Data needs review: {meta['review_n']}",
        '- Sector-balanced selection means the first 12/24 names are not automatically all semiconductor companies.',
        '- Screening flags refer to decision-blocking concerns. Non-blocking coverage limits are in the full CSV.',
        '- A no-warning row is still UNVERIFIED; vendor ratios can be wrong even if internally consistent.',
        '- Currency mismatches cause a missing FCF yield, never an invented FX conversion. Other metrics can still be scored.',
        '', '## Sector-diversified short list — verify each against primary sources', '',
        '| Company | Ticker | Peer group | Exploratory score | Revenue growth* | Forward PE* | Flags |',
        '|---|---|---|---:|---:|---:|---|',
    ]
    if shortlist.empty:
        out.append('| NO CANDIDATES | — | — | — | — | — | Insufficient coverage or review flags |')
    else:
        for _, r in shortlist.iterrows():
            limit = 'FCF unavailable' if not np.isfinite(valid_number(r.get('fcf_yield'))) else 'vendor periods unconfirmed'
            out.append(f"| {r.get('company','')} | {r['ticker']} | {r['peer_group']} | {_fmt(r['exploratory_score_100'])} | {_fmt(r['revenue_growth'],True)} | {_fmt(r['forward_pe'])} | no blocking flags; {limit} |")
    out += [
        '', '*Vendor-defined periods; different company reporting bases may NOT be comparable.',
        '', '## What needs manual examination', '',
    ]
    flagged = ranked[ranked['data_quality_flags'].ne('') | (~ranked['rankable']) | ranked['fetch_error'].fillna('').ne('')]
    if flagged.empty:
        out.append('- No heuristic warnings, but no filing-level validation was performed.')
    else:
        for _, r in flagged.head(40).iterrows():
            reason = r['data_quality_flags'] or r['fetch_error'] or 'MISSING_METRICS_OR_PEER_COVERAGE'
            out.append(f"- {r['ticker']} ({r['peer_group']}): {reason}")
    out += [
        '', '## PM discussion and next research steps', '',
        '1. Why is THIS company underappreciated? What does the current market price imply?',
        '2. Is growth structural or cyclical? Check segment revenue, unit economics and cash conversion.',
        '3. Why choose DCF vs PSR vs EV/EBITDA? Compare methods, assumptions, and sensitivities.',
        '4. What exact dated event/filing could re-rate shares? Check source and plausibility.',
        '5. What is the strongest bear case and the measurable thesis invalidation condition?',
        '6. Record a source URL and source publication date for EVERY material assumption.',
        '', '## Limits', '',
        '- Only manually curated companies were searched. This is NOT discovery across all Asian exchanges.',
        '- Peer groups and weights are analyst examples. Country accounting, net cash/debt, diluted EPS and cross-currency differences remain unadjusted.',
        '- Prices, EPS estimates, growth and FCF snapshots may use different reporting windows.',
        '- Flags are heuristics; an unusual value might be valid or erroneous. Do not suppress evidence.',
        '- Vendor lastSplitDate is indicative only; it cannot prove there was no recent split.',
        '- Profitability flags prioritize core GARP; loss-making turnarounds require a separate thesis, not a silent pass.',
        '- No earnings surprise, catalyst, multi-language filings, consensus revisions or real valuation range is automatically verified.',
        '- Not a backtest, forecasting model, trading engine, or investment recommendation.',
    ]
    out += [
        '', '## Portfolio-ready explanation (do not present as a validated recommendation)', '',
        'The system takes a manually curated multi-industry Asia equity universe, retrieves public-provider',
        'snapshot metrics and calculates peer-relative exploratory scores. Outliers, possible split basis',
        'issues and deteriorating profitability are moved into a reviewer queue. Currency mismatch',
        'is reported as missing FCF yield, not silently treated as zero or converted without a known FX rate.',
        'All vendor data remain unverified until checked against dated company filings; the research memo',
        'must explain the valuation method, a bear case and an observable catalyst.',
    ]
    return '\n'.join(out)+'\n'


def memo_template() -> str:
    return '''# Candidate research memo template (manual analyst approval required)

**Company / ticker:** __________   **Research date:** __________

## One-sentence thesis (why price is wrong)
- 

## 1. What does the company actually do? Growth mechanism
- Segment/product revenue drivers:
- Asian supply-chain / competitor context:
- Sources with publication dates:

## 2. Why this valuation method? (DCF vs PSR vs peers)
- Business economics and predictable cash flows:
- Method A and main assumptions:
- Method B and main assumptions:
- Bull/base/bear RANGE, not a spurious precise target:
- Current market price and implied expectations:
- Currency, filing time, EPS dilution, share-class issues:

## 3. Market misperception and catalyst
- What is consensus missing (evidence, not speculation)?
- Specific catalyst and when to monitor:
- Primary source URL and publication date:

## 4. Bear case, risks and invalidation
- Strongest counterargument:
- Evidence that would falsify the thesis:
- Downside scenario and valuation sensitivity:

## 5. AI provenance and human review
- Automated screening role:
- Primary documents checked by me:
- AI outputs I rejected or corrected:
- Open questions / cannot conclude yet:

**Investment view:** RESEARCH ONLY / NO DECISION UNTIL VALIDATED
'''


def _load_universe(path: Path) -> pd.DataFrame:
    u = pd.read_csv(path, dtype=str).fillna('')
    required = {'ticker', 'company', 'market', 'peer_group', 'industry_thesis'}
    if required - set(u.columns):
        raise ValueError('Universe missing: '+', '.join(sorted(required - set(u.columns))))
    if u['ticker'].duplicated().any() or not u['ticker'].str.strip().all():
        raise ValueError('Missing or duplicate ticker')
    return u


def run(universe_file: Path, outputs: Path, max_symbols: int = 24,
        delay_seconds: float = 1.0, snapshot_csv: Path | None = None) -> dict:
    base = _load_universe(universe_file)
    selected = balanced_sample(base, max_symbols)
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat()
    archived = None
    if snapshot_csv is not None:
        archived = pd.read_csv(snapshot_csv, dtype={'ticker': str}).set_index('ticker', drop=False)
        if archived.index.duplicated().any():
            raise ValueError('Snapshot has duplicate tickers')
    rows=[]
    for i, (_, s) in enumerate(selected.iterrows(), 1):
        ticker=s['ticker']
        print(f'[{i}/{len(selected)}] {ticker} peer={s["peer_group"]}', flush=True)
        row=s.to_dict()
        row.update({field: np.nan for field in METRICS})
        row.update({'fetch_error':'', 'info_warning':'', 'retrieved_at_utc':timestamp,
                    'metric_period':'VENDOR_DEFINED_UNCONFIRMED',
                    'revenue_growth_period':'VENDOR_DEFINED_UNCONFIRMED',
                    'earnings_growth_period':'VENDOR_DEFINED_UNCONFIRMED',
                    'fcf_yield_status':'UNKNOWN','split_recent':False,
                    'last_split_date_utc':'','last_split_factor':'',
                    'data_source':'yfinance_info','currency':'', 'financial_currency':''})
        if archived is not None:
            if ticker in archived.index:
                a=archived.loc[ticker]
                for field in [*METRICS,'market_cap','currency','financial_currency','forward_eps',
                              'current_price','trailing_pe','provider_name','info_warning','metric_period',
                              'retrieved_at_utc','fetch_error','revenue_growth_period',
                              'earnings_growth_period','fcf_yield_status','split_recent',
                              'last_split_date_utc','last_split_factor','data_source']:
                    if field in archived.columns:
                        row[field] = a[field]
            else:
                row['fetch_error']='SNAPSHOT_MISSING_SYMBOL'
        else:
            try:
                row.update(pull_ticker(ticker))
            except Exception as error:
                row['fetch_error'] = type(error).__name__+': '+str(error)[:160]
            if delay_seconds and i < len(selected): time.sleep(delay_seconds)
        rows.append(row)
    d=pd.DataFrame(rows)
    d['fetch_error']=d['fetch_error'].fillna('').astype(str)
    d['info_warning']=d['info_warning'].fillna('').astype(str)
    if not d['fetch_error'].eq('').any():
        raise RuntimeError('All data unavailable. No fake/stale success fallback.')
    # Snapshot replay preserves the source's retrieved_at_utc for auditability.
    # A missing field does NOT imply verified data or the absence of corporate actions.
    ranked=rate_peer_universe(d)
    # Persistent reviewer queue from suspicious observations in the preceding run.
    # Never silently treat an old discrepancy as resolved by a later vendor snapshot.
    prior_path=universe_file.parent/'prior_discrepancies_to_review.csv'
    if prior_path.exists():
        prior=pd.read_csv(prior_path,dtype=str).fillna('')
        if not {'ticker','status'} <= set(prior.columns):
            raise ValueError('Invalid prior discrepancy review list')
        open_symbols=set(prior.loc[prior['status'].str.upper()!='RESOLVED','ticker'])
    else:
        open_symbols=set()
    ranked['prior_run_discrepancy'] = ranked['ticker'].apply(
        lambda sym: 'PRIOR_VENDOR_DISCREPANCY_VERIFY_FILINGS' if sym in open_symbols else '')
    affected=ranked['prior_run_discrepancy'].ne('')
    ranked.loc[affected,'data_quality_flags'] = ranked.loc[affected].apply(
        lambda row: '|'.join(filter(None, [row['data_quality_flags'], row['prior_run_discrepancy']])),axis=1)
    ranked.loc[affected,'shortlist_eligible']=False
    ranked.loc[affected & ranked['rankable'],'screen_status']='REVIEW_SUSPECT_METRICS'
    ranked=ranked.sort_values(['shortlist_eligible','rankable','exploratory_score_100','ticker'],
        ascending=[False, False, False, True],na_position='last').reset_index(drop=True)
    shortlist=diversified_shortlist(ranked)
    flagged=ranked['data_quality_flags'].ne('')
    meta={
        'run_generated_utc':timestamp,
        'data_mode':'SNAPSHOT_REPLAY_NOT_LIVE' if archived is not None else 'LIVE_YFINANCE_UNVERIFIED',
        'source':'snapshot CSV' if archived is not None else 'yfinance (vendor-defined snapshot)',
        'curated_universe_n':len(base), 'universe_n':len(selected),
        'industry_groups_selected':int(selected['peer_group'].nunique()),
        'industry_group_counts':{k:int(v) for k,v in selected['peer_group'].value_counts().items()},
        'rankable_n':int(ranked['rankable'].sum()),
        'shortlist_eligible_n':int(ranked['shortlist_eligible'].sum()),
        'shortlist_n':len(shortlist),
        'flagged_n':int(flagged.sum()),
        'data_errors_n':int(ranked['fetch_error'].ne('').sum()),
        'review_n':int(ranked['screen_status'].ne('UNVERIFIED_RESEARCH_CANDIDATE').sum()),
        'paper_or_real_orders':'NONE',
        'filing_level_verification':'NOT_PERFORMED',
        'is_entire_asia_market_scan':False,
        'vendor_periods_verified':False,
        'independent_cross_provider_validation':False,
        'fcf_missing_n':int(ranked['fcf_yield'].isna().sum()),
        'split_review_n':int(ranked['data_quality_flags'].str.contains('SPLIT|SHARE',na=False).sum()),
        'profitability_review_n':int(ranked['data_quality_flags'].str.contains('NON_POSITIVE|EARNINGS_DECLINE',na=False).sum()),
        'growth_period_unconfirmed_n':int(ranked['data_limitations'].str.contains('GROWTH_PERIOD_VENDOR_UNCONFIRMED',na=False).sum()),
        'pipeline_revision':'0.2.1',
    }
    outputs.mkdir(parents=True,exist_ok=True)
    ranked.to_csv(outputs/'01_all_research_candidates.csv',index=False,encoding='utf-8-sig')
    shortlist.to_csv(outputs/'02_research_shortlist.csv',index=False,encoding='utf-8-sig')
    (outputs/'03_research_report.md').write_text(report(ranked, shortlist, timestamp, meta),encoding='utf-8')
    (outputs/'04_run_metadata.json').write_text(json.dumps(meta,indent=2,ensure_ascii=False),encoding='utf-8')
    ranked[flagged | (~ranked['rankable']) | ranked['fetch_error'].ne('')].to_csv(outputs/'05_data_quality_review.csv',index=False,encoding='utf-8-sig')
    peer = ranked.groupby('peer_group').agg(selected_n=('ticker','size'),
            rankable_n=('rankable','sum'),eligible_n=('shortlist_eligible','sum'),
            avg_coverage=('coverage_weight','mean')).reset_index()
    peer.to_csv(outputs/'06_peer_coverage.csv',index=False,encoding='utf-8-sig')
    (outputs/'07_investment_memo_TEMPLATE.md').write_text(memo_template(),encoding='utf-8')
    selected.to_csv(outputs/'08_balanced_selection.csv',index=False,encoding='utf-8-sig')
    # Dedicated work queue: a clean relative rank does not establish company value.
    review_fields = ['ticker','company','market','peer_group','exploratory_score_100',
                     'screen_status','data_quality_flags','data_limitations','prior_run_discrepancy',
                     'revenue_growth','revenue_growth_period','earnings_growth','earnings_growth_period',
                     'operating_margin','roe','forward_pe','current_price','forward_eps',
                     'last_split_date_utc','last_split_factor','split_recent',
                     'currency','financial_currency','fcf_yield','fcf_yield_status',
                     'retrieved_at_utc','filing_verification']
    ranked[[c for c in review_fields if c in ranked.columns]].to_csv(
        outputs/'09_filing_verification_queue.csv',index=False,encoding='utf-8-sig')
    (outputs/'10_portfolio_methodology_NOTE.md').write_text('''# Screening methodology, limits, and responsibility (v0.2.1)

- Scope: 61 **manually selected** Asian equities across nine industry peer groups, not an exchange-wide search.
- Research process: retrieve vendor snapshots → evaluate coverage/outliers → peer-relative scores → diversification → analyst filings verification → thesis and bear case.
- Assumptions: exploratory weights are independent hypotheses, not any asset manager's proprietary recipe. A rank is NOT an estimate of intrinsic value.
- QA: the reviewer queue identifies valuation extremes, price/EPS inconsistency, recent vendor-reported splits, profitability deterioration, unknown growth periods and FX-denominated FCF omissions.
- Reproducibility: source code, workflow configuration, peer universe, generated UTC time and CSV results are preserved by each workflow artifact (retention policy applies).
- Unresolved: primary filings have NOT been cross-checked automatically; vendor period definitions, corporate actions and cross-currency financial data may still be incorrect.
- Contribution disclosure: investment criteria and QA goals were user-directed; implementation was AI-assisted and must be independently understood and reviewed by the submitter.

**For a 1–2 page equity memo:** spend only 3–5 lines on this method and link to GitHub. The majority must explain the company thesis, valuation-method choice, catalyst, bear case and falsifiable conditions.
''',encoding='utf-8')

    print(f"Saved {len(shortlist)} diversified, unverified research candidates from {len(selected)} firms / {meta['industry_groups_selected']} groups")
    return meta


def main():
    p=argparse.ArgumentParser(description='Asia GARP v0.2.1 independent research; no trades')
    p.add_argument('--universe',type=Path,default=Path('data/universe.csv'))
    p.add_argument('--output',type=Path,default=Path('outputs'))
    p.add_argument('--max-symbols',type=int,default=24,help='0=all manually curated; 12=4 peer groups x3; 24=8 groups x3')
    p.add_argument('--delay-seconds',type=float,default=1.0)
    p.add_argument('--snapshot-csv',type=Path,default=None,help='Offline CSV replay; does NOT refresh financial data')
    args=p.parse_args()
    run(args.universe,args.output,args.max_symbols,args.delay_seconds,args.snapshot_csv)

if __name__=='__main__': main()
