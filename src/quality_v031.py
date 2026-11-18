"""Same-input score sensitivity and evidence quality; no fictitious alpha claim."""
from __future__ import annotations
import math
import pandas as pd
import numpy as np
from .scoring_v03 import CATEGORY_WEIGHTS, SECTOR_WEIGHTS


def _score_with_modified_weight(frame:pd.DataFrame,modified_cat:str|None, multiplier:float=1.0)->pd.Series:
    result=[]
    for _,r in frame.iterrows():
        weights=SECTOR_WEIGHTS.get(str(r.get('peer_group','')),CATEGORY_WEIGHTS).copy()
        if modified_cat:weights[modified_cat]*=multiplier
        weights={k:v/sum(weights.values()) for k,v in weights.items()}
        total=0.;cov=0.
        for cat,w in weights.items():
            try:v=float(r.get(f'{cat}_score_100'));coverage=float(r.get(f'{cat}_coverage'))
            except (ValueError,TypeError):continue
            if math.isfinite(v) and math.isfinite(coverage):
                total+=w*v*coverage;cov+=w*coverage
        result.append(total/cov*(.8+.2*cov) if cov>=.65 else math.nan)
    return pd.Series(result,index=frame.index)


def sensitivity_report(frame:pd.DataFrame)->tuple[pd.DataFrame,dict]:
    """+/-20% on one category weight at a time; rank only research-eligible names.

    Measures engineering/model stability, not predictive validity. Same input
    eliminates data-refresh and changing universe as confounders.
    """
    eligible=frame[frame.v031_research_eligible].copy().reset_index(drop=True)
    columns=['ticker','company','market','baseline_score','baseline_rank','rank_min','rank_max',
             'rank_range','rank_std','score_min','score_max','top10_scenario_share']
    if eligible.empty:return pd.DataFrame(columns=columns),{'scenarios':0,'stable_top10_overlap_mean':None}
    baseline=eligible.cross_industry_score_100.astype(float)
    ranks=[];scores=[];overlaps=[]
    original_top=set(eligible.loc[baseline.nlargest(10).index,'ticker'])
    for cat in CATEGORY_WEIGHTS:
        for mult in (.8,1.2):
            val=_score_with_modified_weight(eligible,cat,mult)
            srank=val.rank(ascending=False,method='min')
            ranks.append(srank);scores.append(val)
            overlaps.append(len(set(eligible.loc[val.nlargest(10).index,'ticker']) & original_top)/max(1,len(original_top)))
    rank_table=pd.concat(ranks,axis=1);score_table=pd.concat(scores,axis=1)
    out=pd.DataFrame({'ticker':eligible.ticker,'company':eligible.company,'market':eligible.market,
        'baseline_score':baseline.round(2),'baseline_rank':baseline.rank(ascending=False,method='min'),
        'rank_min':rank_table.min(axis=1),'rank_max':rank_table.max(axis=1),
        'rank_range':rank_table.max(axis=1)-rank_table.min(axis=1),
        'rank_std':rank_table.std(axis=1).round(2),
        'score_min':score_table.min(axis=1).round(2),'score_max':score_table.max(axis=1).round(2),
        'top10_scenario_share':(rank_table<=10).mean(axis=1).round(2)})
    out=out.sort_values('baseline_rank').reset_index(drop=True)
    return out,{'scenarios':len(ranks),'stable_top10_overlap_mean':round(float(np.mean(overlaps)),3),
                'eligible_scored_n':len(eligible),'study':'ONE_FACTOR_CATEGORY_WEIGHT_PLUS_MINUS_20PCT_SAME_INPUT',
                'not_predictive_validation':True}


def diagnostics(frame:pd.DataFrame,discovery_log:pd.DataFrame,evidence:pd.DataFrame,
                decisions:pd.DataFrame,sensitivity:dict)->dict:
    has=pd.to_numeric(frame.cross_industry_score_100,errors='coerce').notna()
    is_new=frame.is_new_discovery.map(lambda v:str(v).lower() in ('true','1'))
    official=(evidence.evidence_type.eq('REGULATOR_FILING') if not evidence.empty else pd.Series(dtype=bool))
    return {'analyzed_n':len(frame), 'score_available_n':int(has.sum()),
        'score_coverage_mean':round(float(pd.to_numeric(frame.score_coverage,errors='coerce').mean()),3),
        'quality_warning_n':int(frame.data_quality_flags.fillna('').ne('').sum()),
        'research_eligible_n':int(frame.v031_research_eligible.sum()),
        'new_research_eligible_n':int((frame.v031_research_eligible & is_new).sum()),
        'primary_filing_metadata_found_n':int(official.sum()) if len(official) else 0,
        'primary_filing_financial_values_verified_n':0,
        'financial_periods_verified_n':0,
        'accounting_to_ifrs_restated_n':0,
        'news_headlines_collected_n':int(evidence.evidence_type.eq('NEWS_HEADLINE').sum()) if not evidence.empty else 0,
        'earning_statements_vendor_n':int(evidence.evidence_type.eq('EARNINGS_VENDOR').sum()) if not evidence.empty else 0,
        'analyst_accept_n':int(decisions.decision.eq('ACCEPTED').sum()) if not decisions.empty else 0,
        'analyst_reject_n':int(decisions.decision.eq('REJECTED').sum()) if not decisions.empty else 0,
        'source_failure_n':int(discovery_log.status.eq('FAILED_NO_FALLBACK').sum()) if not discovery_log.empty else 0,
        'sensitivity':sensitivity,
        'point_in_time_future_return_test':'NOT_PERFORMED',
        'return_prediction_calibration':'NOT_PERFORMED',
        'investment_recommendation':'NONE',
        'quality_interpretation':'PIPELINE_DIAGNOSTICS_NOT_PROOF_OF_BETTER_EQUITY_ANALYSIS'}


def diagnostics_markdown(meta:dict)->str:
    lines=['# v0.3.1 Research Quality Audit','',
        '**Do not conflate a successful workflow with accurate valuation or excess returns.**','',
        f"- Analyzed: {meta['analyzed_n']}; scores available: {meta['score_available_n']}",
        f"- Research-only eligible: {meta['research_eligible_n']}; newly found: {meta['new_research_eligible_n']}",
        f"- Vendor anomalous metrics: {meta['quality_warning_n']}",
        f"- DART filing references collected: {meta['primary_filing_metadata_found_n']} (not contents audited)",
        f"- Financial values reconciled to official filings: {meta['primary_filing_financial_values_verified_n']}",
        f"- News headlines: {meta['news_headlines_collected_n']}; vendor quarterly rows: {meta['earning_statements_vendor_n']}",
        f"- Analyst-accepted thesis: {meta['analyst_accept_n']}; analyst-rejected thesis: {meta['analyst_reject_n']}",
        f"- Weight sensitivity: {meta['sensitivity'].get('scenarios',0)} same-input scenarios; mean top10 overlap={meta['sensitivity'].get('stable_top10_overlap_mean')}",
        '', '## What has **not** been validated','',
        '- Global coverage is not a census of the five exchanges; vendor screening may omit issuers.',
        '- Filing collection is a link/metadata operation, not an independent audit of reported earnings.',
        '- Yahoo Finance growth fields lack verified reporting-period alignment.',
        '- Industry anchors and weights are not calibrated against forward returns.',
        '- Currency conversion is an estimated normalization, not IAS 21-compliant issuer financial restatement.',
        '- Cross-currency forward P/E is withheld without EPS unit proof.',
        '', '## Next research quality gates','',
        '1. For each memo candidate, reconcile at least 3 key figures to a dated issuer filing.',
        '2. Check revenue and earnings comparisons on the same fiscal periods and units.',
        '3. Produce intrinsic-value scenarios with assumptions, catalysts and strongest bear case.',
        '4. Record rejected ideas as explicit analyst decisions with dated evidence.',
        '5. Only then compare research conclusions; future predictive validity still requires point-in-time out-of-sample validation.','']
    return '\n'.join(lines)
