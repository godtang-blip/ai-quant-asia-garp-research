"""Cross-industry IDEA-PRIORITY scoring on an explicitly common numeric scale.

Reference anchors are independent research assumptions, NOT trained/calibrated
against forward returns.  Scores are not mathematically equivalent to
future alpha/valuation. Warn/withhold when coverage or consistency is poor.
"""
from __future__ import annotations
import math
import pandas as pd
import numpy as np

# Anchors are *absolute levels*, not a percentile of a tiny peer group.
# Direction: higher is better unless indicated otherwise.
ANCHORS = {
 'revenue_growth': ([-.35,0,.10,.22,.45],[0,25,50,75,100]),
 'earnings_growth': ([-.6,-.10,.10,.30,.75],[0,25,50,75,100]),
 'operating_margin': ([-.15,.03,.12,.22,.40],[0,25,50,75,100]),
 'roe': ([-.25,.04,.12,.22,.40],[0,25,50,75,100]),
 'fcf_yield': ([-.05,.005,.03,.06,.12],[0,25,50,75,100]),
 'debt_to_equity_ratio': ([0,.25,.75,1.75,4],[100,85,60,30,0]),
 'price_change_52w': ([-.65,-.2,0,.25,.70],[0,25,50,75,100]),
}
# Sector-specific baseline valuation reference points (example hypotheses).
# A P/E of 25 has different expectations for pharmaceutical vs automakers.
PE_ANCHORS = {
 'platforms':(12,22,42),'industrial_electrification':(12,21,37),
 'healthcare_biopharma':(13,26,48),'gaming_media':(11,22,40),
 'consumer_brands':(12,23,40),'chip_equipment':(12,24,43),
 'automakers':(6,12,22),'chip_manufacturing':(10,20,36),
 'chip_components':(10,21,38),'unclassified':(10,20,40),
}
PS_ANCHORS = {
 'platforms':(1.2,3.5,8),'industrial_electrification':(.7,2.2,5),
 'healthcare_biopharma':(1.3,4.5,11),'gaming_media':(1,3,8),
 'consumer_brands':(.6,2,6),'chip_equipment':(.9,3.6,8),
 'automakers':(.2,.8,2),'chip_manufacturing':(1,4,10),
 'chip_components':(.7,2.5,7),'unclassified':(.8,3,8),
}
# Objective frame weights: 25/20/25/20/10, methods researcher-specified.
CATEGORY_WEIGHTS = {'growth':.25,'profitability':.20,'valuation':.25,'resilience':.20,'momentum':.10}
# Research-only subjective sector adjustments; each vector sums to 1.0.
# Not optimized, backtested or learned from forward return data.
SECTOR_WEIGHTS = {
 'platforms':{'growth':.30,'profitability':.20,'valuation':.20,'resilience':.20,'momentum':.10},
 'industrial_electrification':{'growth':.25,'profitability':.25,'valuation':.20,'resilience':.20,'momentum':.10},
 'healthcare_biopharma':{'growth':.30,'profitability':.20,'valuation':.20,'resilience':.20,'momentum':.10},
 'gaming_media':{'growth':.25,'profitability':.20,'valuation':.25,'resilience':.20,'momentum':.10},
 'consumer_brands':{'growth':.20,'profitability':.25,'valuation':.25,'resilience':.20,'momentum':.10},
 'chip_equipment':{'growth':.25,'profitability':.20,'valuation':.25,'resilience':.20,'momentum':.10},
 'automakers':{'growth':.20,'profitability':.20,'valuation':.30,'resilience':.20,'momentum':.10},
 'chip_manufacturing':{'growth':.25,'profitability':.20,'valuation':.25,'resilience':.20,'momentum':.10},
 'chip_components':{'growth':.25,'profitability':.20,'valuation':.25,'resilience':.20,'momentum':.10},
}
assert all(abs(sum(x.values())-1.0)<1e-9 for x in SECTOR_WEIGHTS.values())
SUBMETRICS = {
 'growth':('revenue_growth','earnings_growth'),
 'profitability':('operating_margin','roe'),
 'valuation':('forward_pe','price_to_sales'),
 'resilience':('fcf_yield','debt_to_equity_ratio'),
 'momentum':('price_change_52w',),
}


def number(v):
    try:
        n=float(v)
        return n if math.isfinite(n) else math.nan
    except (TypeError, ValueError):return math.nan


def anchor_score(field, val, group='unclassified'):
    n=number(val)
    if not math.isfinite(n):return math.nan
    if field in ('forward_pe','price_to_sales'):
        if n<=0:return math.nan
        anchors=(PE_ANCHORS if field=='forward_pe' else PS_ANCHORS).get(group,(10,20,40) if field=='forward_pe' else (.8,3,8))
        # cheaper ratio -> higher exploratory score; 25x cannot be compared as
        # a precise intrinsic-value estimate; 3 anchors reduce cliff effects.
        return float(np.interp(n, [anchors[0]/2,*anchors,anchors[2]*2],[100,85,50,20,0]))
    xs,ys=ANCHORS[field]
    if field=='debt_to_equity_ratio' and n<0: return math.nan
    return float(np.interp(n,xs,ys))


def compute_scores(data: pd.DataFrame) -> pd.DataFrame:
    d=data.copy()
    for col in ('ticker','peer_group'):
        if col not in d: raise ValueError(f'Missing {col}')
    for cat,fields in SUBMETRICS.items():
        scores=[]
        coverage=[]
        for _, r in d.iterrows():
            vals=[anchor_score(f,r.get(f),str(r.get('peer_group') or 'unclassified')) for f in fields]
            present=[v for v in vals if math.isfinite(v)]
            scores.append(sum(present)/len(present) if present else math.nan)
            coverage.append(len(present)/len(fields))
        d[f'{cat}_score_100']=scores
        d[f'{cat}_coverage']=coverage
    total=[]; cov=[]; statuses=[]; flags=[]
    for _,r in d.iterrows():
        sum_score=0;available_weight=0
        selected_weights=SECTOR_WEIGHTS.get(str(r.get('peer_group') or ''),CATEGORY_WEIGHTS)
        for cat,w in selected_weights.items():
            s=number(r[f'{cat}_score_100'])
            if math.isfinite(s):
                sum_score+=w*s*number(r[f'{cat}_coverage'])
                available_weight+=w*number(r[f'{cat}_coverage'])
        coverage=available_weight
        cov.append(round(coverage,3))
        # A weighted sum that is exactly 65% can land just below it in binary.
        meets_score_coverage = coverage >= .65 or math.isclose(
            coverage, .65, rel_tol=0, abs_tol=1e-12
        )
        fl=[]
        if r.get('peer_group','') in ('unclassified','other',''):
            fl.append('SECTOR_UNCLASSIFIED_REQUIRES_ANALYST_MAPPING')
        if r.get('fetch_error') and str(r.get('fetch_error')) not in ('','nan','None'):
            fl.append('DATA_FETCH_ERROR')
        if number(r.get('operating_margin'))<=0 or number(r.get('roe'))<=0:
            fl.append('NON_POSITIVE_PROFITABILITY')
        if str(r.get('data_quality_flags') or '') not in ('','nan','None'):
            fl.append('V021_DATA_WARNING')
        if not (math.isfinite(number(r.get('forward_pe'))) or math.isfinite(number(r.get('price_to_sales')))):
            fl.append('NO_VALUATION_REFERENCE')
        if not meets_score_coverage:
            fl.append('INSUFFICIENT_METRIC_COVERAGE')
        # Combined data score used only to prioritize manual due diligence.
        score = sum_score / coverage if meets_score_coverage else math.nan
        # apply mild proportional coverage penalty instead of propping sparse
        # coverage up to a deceptive top score.
        score *= (0.80+0.20*coverage) if math.isfinite(score) else 1
        total.append(round(score,2) if math.isfinite(score) else math.nan)
        flags.append('|'.join(fl))
        statuses.append('REVIEW_NO_GLOBAL_RANK' if fl else 'UNVERIFIED_RESEARCH_CANDIDATE')
    d['score_coverage']=cov
    d['cross_industry_score_100']=total
    d['v03_review_flags']=flags
    d['v03_status']=statuses
    d['v03_shortlist_eligible']=d['v03_review_flags'].eq('') & d['cross_industry_score_100'].notna()
    d['sector_weights_used']=d['peer_group'].apply(lambda g:';'.join(f'{k}={v:.2f}' for k,v in SECTOR_WEIGHTS.get(str(g),CATEGORY_WEIGHTS).items()))
    d['score_method']='V03_FIXED_ANCHORS_SECTOR_WEIGHTS_UNCALIBRATED_NOT_EXPECTED_RETURN'
    return d.sort_values(['v03_shortlist_eligible','cross_industry_score_100','ticker'],
       ascending=[False,False,True],na_position='last').reset_index(drop=True)
