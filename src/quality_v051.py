"""v0.5.1 operational audits: coverage, watchlist balance and headline entity checks.

These are research process diagnostics, not stock rankings or financial verification.
Historical v0.5 artifacts are preserved unless explicitly noted below.
"""
from __future__ import annotations

import json
from pathlib import Path
import re
import unicodedata

import pandas as pd
from .discovery_v031 import REGIONS
from .listing_exports import VENUES
from .evidence import read_manual_decisions, render_evidence_book

SOURCE_KEYS={
    'Korea':'official_krx_listed_issues',
    'Japan':'official_jpx_full_listing',
    'China':'NO_OFFICIAL_ADAPTER',
    'Hong Kong':'NO_OFFICIAL_ADAPTER',
    'Taiwan':'official_twse_listed_companies',
}


def _read(root:Path,name:str)->pd.DataFrame:
    return pd.read_csv(root/name,dtype={'ticker':str},keep_default_na=False,encoding='utf-8-sig')


def _yes(value:object)->bool:
    return str(value).strip().lower() in {'true','1','yes'}


def _norm(value:object)->str:
    return unicodedata.normalize('NFKC',str(value or '')).casefold()


def _issuer_tokens(name:str)->list[str]:
    text=_norm(name)
    # Stop words do not identify a security; a short CJK core company name can.
    text=re.sub(r'\b(limited|holdings?|corporation|incorporated|inc|co|ltd|group|plc|company|the)\b',' ',text)
    words=re.findall(r'[a-z0-9]{3,}|[\u3400-\u9fff]{2,}|[\u3040-\u30ff]{2,}|[\uac00-\ud7af]{2,}',text)
    return [w for w in words if w not in {'corporate','international','technology','technologies','electronics','manufacturing','semiconductor'}]


def headline_entity_audit(ticker:str,company:str,title:str,aliases:list[str]|None=None)->tuple[str,str]:
    """Title-only *probable* entity match. Never claims the underlying article is read."""
    head=_norm(title)
    # An explicit foreign Exchange-qualified ticker is sufficient to reject a misattached headline.
    explicit=re.findall(r'(?<![a-z0-9])([0-9]{1,6})\.(tw|two|hk|ks|kq|t|ss|sz|bj)\b',head)
    target=ticker.casefold()
    foreign=[f'{code}.{suffix}'.upper() for code,suffix in explicit
             if f'{code}.{suffix}'.upper()!=target.upper()]
    if foreign:return 'QUARANTINE_OTHER_TICKER','Other exchange-qualified ticker(s): '+', '.join(foreign[:3])
    if target in head:return 'PROVISIONAL_TICKER_MATCH','Explicit target exchange-qualified ticker in headline'
    for alias in [company,*list(aliases or [])]:
        base=_norm(alias)
        if len(base)>=4 and base in head:
            return 'PROVISIONAL_NAME_MATCH','Issuer name appears in headline; article not read'
        tokens=_issuer_tokens(alias)
        # Multiple distinctive English tokens to avoid false matches of common single terms.
        latin=[w for w in tokens if re.fullmatch(r'[a-z0-9]+',w)]
        nonlatin=[w for w in tokens if not re.fullmatch(r'[a-z0-9]+',w)]
        if nonlatin and any(w in head for w in nonlatin if len(w)>=2):
            return 'PROVISIONAL_NAME_MATCH','Non-Latin issuer name token appears in headline'
        if len(latin)>=2 and all(re.search(r'(?<![a-z0-9])'+re.escape(w)+r'(?![a-z0-9])',head) for w in latin[:2]):
            return 'PROVISIONAL_NAME_MATCH','Two issuer-name tokens appear in headline'
    return 'QUARANTINE_NAME_UNCONFIRMED','No strong issuer identity in title; analyst review required'


# Published v0.5 archive counts. The archive did not report fetch success by market.
ARCHIVE_COUNTS = {
    'Korea': (99, 8), 'Japan': (310, 54), 'China': (91, 11),
    'Hong Kong': (101, 13), 'Taiwan': (1121, 154),
}
FINANCIAL_FIELDS = ('revenue_growth', 'earnings_growth', 'operating_margin',
                    'roe', 'revenue_total_raw', 'free_cashflow_raw')


def coverage_audit(outputs: Path, mode: str, failed_fetches: pd.DataFrame | None = None) -> tuple[pd.DataFrame, dict]:
    universe = _read(outputs, '11_discovery_universe.csv')
    selected = _read(outputs, '08_selected_universe.csv')
    ranked = _read(outputs, '01_all_research_candidates.csv') if failed_fetches is None else failed_fetches
    logs = _read(outputs, '12_discovery_sources_log.csv')
    logmap = {str(r.source): r.to_dict() for _, r in logs.iterrows()}
    total = len(ranked)
    rows = []
    official_missing = []
    for market, key in SOURCE_KEYS.items():
        subset = ranked[ranked.market.eq(market)]
        ext = universe[universe.market.eq(market)]
        source = logmap.get(key, {})
        status = source.get('status', 'NOT_REQUESTED')
        official_ids = {key} if status == 'OK' else set()
        export_ids = {f'export_{venue}' for venue, (region, *_) in VENUES.items()
                      if region == market and logmap.get(f'export_{venue}', {}).get('status') == 'OK'}
        if status != 'OK':
            official_missing.append(market)
        if mode == 'off':
            coverage = 'SNAPSHOT_NO_LIVE_DISCOVERY'
        elif official_ids:
            coverage = 'OFFICIAL_SUPPLEMENTAL_RETRIEVED_NOT_CENSUS'
        elif export_ids:
            coverage = 'PUBLISHER_EXPORT_IMPORTED_NOT_INDEPENDENTLY_VERIFIED'
        elif status == 'NOT_CONFIGURED_AUTH_REQUIRED':
            coverage = 'OFFICIAL_ACCESS_MISSING'
        elif key == 'NO_OFFICIAL_ADAPTER':
            coverage = 'VENDOR_ONLY_OFFICIAL_NOT_CONNECTED'
        else:
            coverage = 'OFFICIAL_RETRIEVAL_FAILED_OR_UNAVAILABLE'

        if 'listing_source_ids' in ext:
            source_ids = ext.listing_source_ids.map(json.loads)
            listing_backed = int(source_ids.map(lambda ids: bool(official_ids.union(export_ids).intersection(ids))).sum())
        else:
            listing_backed = None  # Archived artifacts omit deduplicated source membership.
        scores = pd.to_numeric(subset.get('cross_industry_score_100', pd.Series(dtype=float)), errors='coerce')
        eligible = int(subset.v031_research_eligible.map(_yes).sum()) if 'v031_research_eligible' in subset else 0
        success = subset.fetch_error.fillna('').eq('') if 'fetch_error' in subset else pd.Series(False, index=subset.index)
        metrics = subset.reindex(columns=FINANCIAL_FIELDS).apply(pd.to_numeric, errors='coerce')
        has_financials = metrics.replace([float('inf'), float('-inf')], float('nan')).notna().any(axis=1)
        rows.append({
            'market': market, 'official_source': key, 'official_source_status': status,
            'official_rows_received': int(source.get('accepted_pattern', 0) or 0),
            'publisher_exports_imported': '|'.join(sorted(export_ids)),
            'listing_backed_tickers_n': listing_backed,
            'discovered_universe_n': len(ext),
            'discovered_universe_share_pct': round(100 * len(ext) / len(universe), 2) if len(universe) else 0.0,
            'selected_for_vendor_fetch_n': int(selected.market.eq(market).sum()),
            'analyzed_n': len(subset),
            'analysis_share_pct': round(100 * len(subset) / total, 2) if total else 0.0,
            'successful_vendor_fetch_n': int(success.sum()),
            'financial_observations_n': int((success & has_financials).sum()),
            'scored_n': int(scores.notna().sum()),
            'industry_unclassified_n': int(subset.peer_group.eq('unclassified').sum()),
            'industry_unclassified_pct': round(100 * subset.peer_group.eq('unclassified').mean(), 2) if len(subset) else 0,
            'screening_eligible_n': eligible,
            'screening_eligible_rate_pct': round(100 * eligible / len(subset), 2) if len(subset) else 0,
            'coverage_status': coverage,
            'coverage_claim': 'PARTIAL_UNIVERSE_NOT_COMPARABLE_CENSUS',
        })
    frame = pd.DataFrame(rows)
    shares = frame.discovered_universe_share_pct
    dominant = frame.loc[shares.idxmax(), 'market'] if len(universe) else ''
    status = ('SNAPSHOT_COVERAGE_NOT_AUDITED' if mode == 'off' else
              'PARTIAL_COVERAGE' if official_missing else 'SUPPLEMENTAL_ONLY')
    metrics = {
        'market_coverage_status': status,
        'markets_without_retrieved_official_issuer_list': official_missing,
        'dominant_market': dominant,
        'dominant_market_share_pct': float(shares.max()),
        'dominant_market_selected_share_pct': (
            round(100 * selected.market.eq(dominant).mean(), 2) if dominant and len(selected) else 0),
        'market_concentration_warning': bool(shares.max() > 50),
        'full_five_market_census_verified': False,
        'complete_market_comparable_rankings_allowed': False,
    }
    frame.to_csv(outputs/'38_market_coverage_audit.csv', index=False, encoding='utf-8-sig')
    comparison = frame[['market', 'discovered_universe_n', 'selected_for_vendor_fetch_n',
                        'financial_observations_n', 'screening_eligible_n', 'coverage_status']].copy()
    comparison['archive_analyzed_n'] = comparison.market.map(lambda market: ARCHIVE_COUNTS[market][0])
    comparison['archive_analyzed_share_pct'] = (100 * comparison.archive_analyzed_n / 1722).round(2)
    comparison['archive_screening_eligible_n'] = comparison.market.map(lambda market: ARCHIVE_COUNTS[market][1])
    comparison['current_mode'] = mode
    comparison['current_run_status'] = 'ALL_FINANCIAL_FETCHES_FAILED' if failed_fetches is not None else 'FINISHED'
    comparison.to_csv(outputs/'45_coverage_comparison.csv', index=False, encoding='utf-8-sig')
    return frame, metrics


def produce_research_queues(outputs:Path,per_market:int=5,global_top:int=10)->dict:
    ranked=_read(outputs,'01_all_research_candidates.csv')
    # Use already computed v0.31 research gate; do not override it for cosmetic balance.
    filtered=ranked[ranked.v031_research_eligible.map(_yes)].copy()
    filtered['priority_score']=pd.to_numeric(filtered.cross_industry_score_100,errors='coerce')
    filtered=filtered.sort_values(['priority_score','ticker'],ascending=[False,True],na_position='last')
    fields=['ticker','company','market','peer_group','priority_score','v031_research_status',
            'sector_mapping_status','data_quality_flags','discovery_source']
    results=[]
    def attach(group:pd.DataFrame,lane:str,market:str):
        for rank,(_,r) in enumerate(group.iterrows(),1):
            d={k:r.get(k,'') for k in fields}
            d.update(lane=lane,within_lane_rank=rank,market_group=market,
                     priority_interpretation='INVESTIGATE_ONLY_NOT_A_TARGET_PRICE')
            results.append(d)
    attach(filtered.head(global_top),'GLOBAL_UNQUOTED_SCORE','ALL')
    for market in REGIONS:
        market_subset=filtered[filtered.market.eq(market)]
        attach(market_subset.head(per_market),'MARKET_COVERAGE_REVIEW',market)
        if market_subset.empty:
            d={k:'' for k in fields}
            d.update(lane='MARKET_COVERAGE_REVIEW',within_lane_rank=0,market_group=market,
                     market=market,priority_interpretation='NO_ELIGIBLE_ISSUER_MANUAL_CHECK')
            results.append(d)
    frame=pd.DataFrame(results)
    frame.to_csv(outputs/'39_market_research_queue.csv',index=False,encoding='utf-8-sig')
    return {'global_candidates_n':min(global_top,len(filtered)),
            'cross_market_review_rows_n':len(frame)-min(global_top,len(filtered))}


def audit_news(outputs:Path, data:Path)->dict:
    rows=_read(outputs,'19_news_headlines.csv')
    ledger=_read(outputs,'18_evidence_ledger.csv')
    ranked=_read(outputs,'01_all_research_candidates.csv')
    issuer={str(r.ticker):r.to_dict() for _,r in ranked.iterrows()}
    registry=data/'issuer_source_registry.csv'
    registry_data={}
    if registry.exists():
        reg=pd.read_csv(registry,dtype=str,keep_default_na=False)
        registry_data={str(r.ticker):r.to_dict() for _,r in reg.iterrows()}
    review=[]
    for _,r in rows.iterrows():
        t=str(r.ticker)
        company=str(issuer.get(t,{}).get('company',t))
        aliases=[issuer.get(t,{}).get('provider_name','')]
        # Registry names are reviewer-maintained; do not interpret other fields as aliases.
        for col in ('official_company_name','legal_name'):
            aliases.append(registry_data.get(t,{}).get(col,''))
        verdict,reason=headline_entity_audit(t,company,str(r.title),[a for a in aliases if a])
        d=r.to_dict();d.update(company=company,issuer_match_status=verdict,
                              issuer_match_reason=reason,article_read=False,claim_verified=False)
        review.append(d)
    out=pd.DataFrame(review,columns=['ticker','company','title','source_url','published_date','source_name',
                 'identifier','issuer_match_status','issuer_match_reason','article_read','claim_verified'])
    out.to_csv(outputs/'40_news_relevance_audit.csv',index=False,encoding='utf-8-sig')
    judgments={(str(r.ticker),str(r.identifier)):str(r.issuer_match_status) for _,r in out.iterrows()}
    if not ledger.empty:
        for i,r in ledger[ledger.evidence_type.eq('NEWS_HEADLINE')].iterrows():
            verdict=judgments.get((str(r.ticker),str(r.identifier)),'QUARANTINE_MATCH_NOT_ASSESSED')
            ledger.at[i,'verification_status']='HEADLINE_'+verdict+'_ARTICLE_UNREAD'
            ledger.at[i,'claim_supported']=''
        ledger.to_csv(outputs/'18_evidence_ledger.csv',index=False,encoding='utf-8-sig')
        # Rewrite derivative Evidence Book; retain all sources with explicit quarantine labels.
        shortlist=_read(outputs,'02_research_shortlist.csv')
        decisions=read_manual_decisions(data/'research_decisions.csv')
        (outputs/'27_evidence_book.md').write_text(render_evidence_book(shortlist,ledger,decisions),encoding='utf-8')
    return {'news_headlines_n':len(out),
            'news_quarantined_n':int(out.issuer_match_status.str.startswith('QUARANTINE').sum()) if len(out) else 0,
            'news_provisional_title_match_n':int(out.issuer_match_status.str.startswith('PROVISIONAL').sum()) if len(out) else 0,
            'news_articles_read_n':0,'news_claims_fully_verified_n':0}


def high_score_review(outputs:Path,limit:int=30)->dict:
    ranked=_read(outputs,'01_all_research_candidates.csv')
    scores=pd.to_numeric(ranked.cross_industry_score_100,errors='coerce')
    subset=ranked[~ranked.v031_research_eligible.map(_yes) & scores.notna()].copy()
    subset['numeric_score']=pd.to_numeric(subset.cross_industry_score_100,errors='coerce')
    subset=subset.sort_values(['numeric_score','ticker'],ascending=[False,True]).head(limit)
    keys=['ticker','company','market','numeric_score','peer_group','v031_research_status',
          'data_quality_flags','data_limitations','sector_mapping_status','fetch_error','source_url']
    out=subset.reindex(columns=keys).fillna('')
    out.insert(0,'review_status','RECHECK_NOT_APPROVED')
    out.insert(1,'review_purpose','HIGH_SCORE_SCREENING_GATE_FAILED_NOT_BUY_SIGNAL')
    out.to_csv(outputs/'41_high_score_recheck_queue.csv',index=False,encoding='utf-8-sig')
    return {'high_score_recheck_queue_n':len(out)}


def enhance_v051(outputs:Path,data:Path,discover_mode:str='all5_official')->dict:
    coverage,cm=coverage_audit(outputs,discover_mode)
    queues=produce_research_queues(outputs)
    news=audit_news(outputs,data)
    recheck=high_score_review(outputs)
    quality=json.loads((outputs/'34_research_quality_v05.json').read_text(encoding='utf-8'))
    result={**cm,**queues,**news,**recheck,
            'version':'0.5.1',
            'candidate_sourcing_bias_audited':True,
            'official_financial_figures_machine_verified_n':0,
            'research_performance_improvement_proven':False,
            'trades_executed':False,
            'reviewed_investment_memo_n':int(quality.get('memo_ready_n',0)),
            'source_v05_stage_gate_not_modified':True}
    (outputs/'42_research_readiness_v051.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# Asia GARP Research v0.5.1 — Coverage & Evidence Audit','',
        '> These diagnostics are about data availability and attribution, not future returns.','',
        f"**Coverage: {cm['market_coverage_status']}**; dominant discovered market: {cm['dominant_market']} ({cm['dominant_market_share_pct']}% of discovered), {cm['dominant_market_selected_share_pct']}% of analyzed.",'']
    lines += ['| Market | Universe names | Discovered share | Analyzed | Eligible | Unclassified | Official listing |',
              '|---|---:|---:|---:|---:|---:|---|']
    for _,r in coverage.iterrows():
        lines.append(f"| {r.market} | {r.discovered_universe_n} | {r.discovered_universe_share_pct}% | {r.analyzed_n} | {r.screening_eligible_n} | {r.industry_unclassified_n} | {r.coverage_status} |")
    lines += ['', '## Reading the market tables', '',
        '- These are discovered *lists*, not the full set of currently listed companies in every market.',
        '- `GLOBAL_UNQUOTED_SCORE` is an unvalidated global screening heuristic, not comparable expected return.',
        '- `MARKET_COVERAGE_REVIEW` is a separate investigation lane; it is NOT a portfolio allocation rule.',
        '- A larger Taiwan population does not prove a higher Taiwan investment opportunity rate.',
        '', '## Evidence caution','',
        f"- News titles: {news['news_headlines_n']} total; quarantined: {news['news_quarantined_n']}; provisionally issuer-matched: {news['news_provisional_title_match_n']}.",
        '- All article bodies remain unread; a name match is not fact checking.',
        f"- Primary financials machine checked against filings: {result['official_financial_figures_machine_verified_n']}.",
        f"- Manually signed memo-ready cases: {result['reviewed_investment_memo_n']}.",
        '', '## Next steps for analyst','',
        '1. Review source failures in `12_discovery_sources_log.csv` and `38_market_coverage_audit.csv`.',
        '2. Restore JPX / authorized KRX feed and source China/HK issuer lists legitimately.',
        '3. Review broad industry labels instead of treating electronic components as electrification.',
        '4. Inspect `40_news_relevance_audit.csv`; read actual articles and issuer filings before citing claims.',
        '5. Resolve numeric filing reconciliations and produce a source-linked investment memo.',
        '', 'No backtest alpha, causal benefit or fully automated AI source validation is claimed.']
    (outputs/'43_quality_diagnostics_v051.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    return result
