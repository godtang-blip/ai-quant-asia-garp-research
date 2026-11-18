"""Asia GARP v0.5 -- documented fundamental reconciliation and research gates.

Crucial distinction: manually signed primary evidence is NOT proof the software
independently read the filing. Missing reviews leave stages locked. No strategy
returns/alpha claims or automated trades.
"""
from __future__ import annotations
import datetime as dt
import json
import math
from urllib.parse import urlparse
from pathlib import Path
import pandas as pd

FIN_FIELDS = ['ticker','metric','primary_value','vendor_value','currency','unit',
 'fiscal_period_start','fiscal_period_end','vendor_period_start','vendor_period_end',
 'filing_date','filing_url','filing_page','statement_label','source_type','review_status','reviewer']
DCF_FIELDS = ['ticker','asof_date','currency','fcff_year0','shares_outstanding','net_debt',
 'current_price','growth_bear','growth_base','growth_bull','discount_rate','terminal_growth',
 'forecast_years','filing_url','reviewer','thesis','catalyst','bear_case',
 'counterevidence','falsification_trigger']

ALLOWED_METRICS = {'revenue','operating_income','net_income','operating_cashflow',
                   'free_cashflow','total_assets','diluted_eps','share_count'}
PRIMARY_TYPES = {'ISSUER_FILING','REGULATOR_FILING'}
REQUIRED_MEMO_TEXT = ('thesis','catalyst','bear_case','counterevidence','falsification_trigger')


def _rows(path:Path, fields:list[str])->pd.DataFrame:
    if not path.exists():return pd.DataFrame(columns=fields)
    df=pd.read_csv(path,dtype=str,keep_default_na=False)
    missing=set(fields)-set(df.columns)
    if missing:raise ValueError(f'{path.name}: missing columns {sorted(missing)}')
    return df[fields].fillna('')


def _real_url(s:str)->bool:
    try:
        r=urlparse(str(s).strip())
        return (r.scheme=='https' and bool(r.netloc) and r.hostname not in
                ('example.org','example.com','localhost','test.invalid'))
    except Exception:return False


def _date(s:str, cutoff:dt.date)->dt.date|None:
    try:
        value=dt.date.fromisoformat(str(s).strip())
        return value if value <= cutoff else None
    except (ValueError,TypeError):return None


def _float(s:str)->float|None:
    try:
        v=float(s)
        return v if math.isfinite(v) else None
    except (TypeError,ValueError,OverflowError):return None


def reconcile_financials(path:Path, *, cutoff:dt.date|None=None)->tuple[pd.DataFrame,dict]:
    """Require matched fiscal periods, denominations, primary URL and reviewer.

    2% tolerance is a deliberately conservative heuristic; a mismatch goes into
    the audit queue until an analyst investigates, never silently reconciled.
    """
    today=cutoff or dt.datetime.now(dt.timezone.utc).date()
    frame=_rows(path,FIN_FIELDS)
    out=[]
    for _,r in frame.iterrows():
        row=r.to_dict(); flags=[]
        if row['metric'] not in ALLOWED_METRICS:flags.append('UNKNOWN_METRIC')
        if row['source_type'] not in PRIMARY_TYPES:flags.append('NOT_PRIMARY_SOURCE')
        if row['review_status']!='CONFIRMED' or not row['reviewer'].strip():flags.append('NOT_ANALYST_CONFIRMED')
        if not _real_url(row['filing_url']) or not row['filing_page'].strip() or not row['statement_label'].strip():
            flags.append('PRIMARY_SOURCE_LOCATOR_INCOMPLETE')
        fdate=_date(row['filing_date'],today)
        p0=_date(row['fiscal_period_start'],today);p1=_date(row['fiscal_period_end'],today)
        v0=_date(row['vendor_period_start'],today);v1=_date(row['vendor_period_end'],today)
        if not fdate or not p0 or not p1 or p0>p1 or fdate<p1:flags.append('PRIMARY_PERIOD_OR_DATE_INVALID')
        if not v0 or not v1 or v0!=p0 or v1!=p1:flags.append('VENDOR_PERIOD_NOT_ALIGNED')
        if not row['currency'].strip() or not row['unit'].strip():flags.append('CURRENCY_UNIT_MISSING')
        p=_float(row['primary_value']);v=_float(row['vendor_value'])
        if p is None or v is None:flags.append('NON_NUMERIC_VALUE')
        diff=abs(p-v)/max(abs(p),abs(v),1e-12) if p is not None and v is not None else None
        if diff is not None and diff>0.02:flags.append('VENDOR_PRIMARY_DISCREPANCY_GT_2PCT')
        row.update(relative_difference=diff or 0.0 if diff is not None else '',
                   validation_status='RECONCILED_MANUAL_ATTESTED' if not flags else 'BLOCKED',
                   validation_flags='|'.join(flags))
        out.append(row)
    detail=pd.DataFrame(out,columns=FIN_FIELDS+['relative_difference','validation_status','validation_flags'])
    return detail,{'submitted_n':len(frame),'reconciled_n':int(detail.validation_status.eq('RECONCILED_MANUAL_ATTESTED').sum()) if not detail.empty else 0,
                   'blocked_n':int(detail.validation_status.eq('BLOCKED').sum()) if not detail.empty else 0,
                   'verification_method':'MANUAL_ATTESTATION_WITH_LOCATORS_NOT_AUTOMATED_FILING_PARSING'}


def passed_primary_gate(frame:pd.DataFrame)->dict[str,dict]:
    """3 distinct audited metrics from one same fiscal period/currency/unit.

    At least revenue and an earnings/cash flow metric. Duplicated records never
    inflate 3-metric coverage.
    """
    if frame.empty:return {}
    good=frame[frame.validation_status.eq('RECONCILED_MANUAL_ATTESTED')]
    result={}
    for ticker,items in good.groupby('ticker'):
        groups=items.groupby(['fiscal_period_start','fiscal_period_end','currency','unit'])
        eligible=[]
        for (start,end,currency,unit),group in groups:
            by_metric=group.drop_duplicates('metric')
            metrics=set(by_metric.metric)
            if ('revenue' in metrics and metrics & {'operating_income','net_income','operating_cashflow','free_cashflow'}
                    and len(metrics)>=3):
                eligible.append({'period_start':start,'period_end':end,'currency':currency,
                    'unit':unit,'metrics':sorted(metrics),'n':len(metrics),
                    'primary_sources':int(by_metric.filing_url.nunique())})
        if eligible:result[str(ticker)]=sorted(eligible,key=lambda g:g['period_end'],reverse=True)[0]
    return result


def dcf_per_share(row:dict)->dict:
    """FCFF DCF at three user-provided scenarios in *one declared local unit*.

    FCFF, net debt and market cap denominators must share unit. Unit consistency
    cannot be inferred automatically from arbitrary vendor snapshots.
    """
    required=['fcff_year0','shares_outstanding','net_debt','current_price',
              'growth_bear','growth_base','growth_bull','discount_rate','terminal_growth','forecast_years']
    v={k:_float(row.get(k)) for k in required}
    if any(value is None for value in v.values()):raise ValueError('Missing or nonfinite DCF assumption')
    if not row.get('currency','').strip():raise ValueError('Missing valuation currency')
    if v['fcff_year0']<=0 or v['shares_outstanding']<=0 or v['current_price']<=0:
        raise ValueError('FCFF, shares and price must be positive')
    years=v['forecast_years']
    if years!=int(years) or not 3<=int(years)<=10:raise ValueError('Forecast years must be integer 3..10')
    discount=v['discount_rate']; terminal=v['terminal_growth']
    if not .03<=discount<=.5 or not -.1<=terminal<=.10 or terminal>=discount-.005:
        raise ValueError('Discount rate insufficient relative to terminal growth')
    growths=[v['growth_'+k] for k in ('bear','base','bull')]
    if not all(-.7<=g<=1.0 for g in growths) or growths!=sorted(growths):
        raise ValueError('Scenario growth assumptions invalid or unordered')
    result={}
    for label,g in zip(('bear','base','bull'),growths):
        fcf=v['fcff_year0'];pv=0.
        for year in range(1,int(years)+1):
            fcf *= 1+g
            pv += fcf/(1+discount)**year
        terminal_value=fcf*(1+terminal)/(discount-terminal)
        equity=pv+terminal_value/(1+discount)**int(years)-v['net_debt']
        result[label]=equity/v['shares_outstanding']
    if result['bear']>result['base']+1e-6 or result['base']>result['bull']+1e-6:
        raise ValueError('Scenario intrinsic values out of order')
    return {**{f'intrinsic_{k}':value for k,value in result.items()},
            'reference_price':v['current_price'],
            'upside_base_pct':result['base']/v['current_price']-1,
            'terminal_value_method':'FCFF Gordon growth, constant scenario growth for all forecast years',
            'model_type':'ILLUSTRATIVE_MANUAL_INPUT_DCF_NOT_FORECAST_VALIDATION'}


def value_assumptions(path:Path, *, cutoff:dt.date|None=None)->tuple[pd.DataFrame,dict]:
    today=cutoff or dt.datetime.now(dt.timezone.utc).date()
    source=_rows(path,DCF_FIELDS)
    if source.ticker.duplicated().any():raise ValueError('Duplicated valuation ticker')
    rows=[]
    for _,r in source.iterrows():
        d=r.to_dict();issues=[]
        if not _date(d['asof_date'],today):issues.append('VALUATION_ASOF_INVALID')
        if not _real_url(d['filing_url']) or not d['reviewer'].strip():issues.append('VALUATION_SOURCE_OR_REVIEWER_MISSING')
        for f in REQUIRED_MEMO_TEXT:
            if len(d[f].strip())<12:issues.append(f.upper()+'_NOT_REVIEWED')
        try:calc=dcf_per_share(d)
        except ValueError as exc:issues.append('DCF_'+str(exc).replace(' ','_')[:80]);calc={}
        d.update(calc)
        d.update(valuation_status='MODELED_MANUAL_INPUT_REVIEWED' if not issues else 'BLOCKED',
                 valuation_flags='|'.join(issues))
        rows.append(d)
    frame=pd.DataFrame(rows)
    return frame, {'valuation_inputs_n':len(source),'valuation_model_valid_n':int(frame.valuation_status.eq('MODELED_MANUAL_INPUT_REVIEWED').sum()) if not frame.empty else 0}


def _safe_markdown(s:str)->str:
    return str(s).replace('|','/').replace('\n',' ').replace('\r',' ').strip()


def enhance(outputs:Path,data:Path,*,asof_date:dt.date|None=None,enable_reviews:bool=True)->dict:
    """Postprocess v0.31 files; leave original 29 outputs unchanged for audit."""
    cutoff=asof_date or dt.datetime.now(dt.timezone.utc).date()
    ranked=pd.read_csv(outputs/'01_all_research_candidates.csv',dtype={'ticker':str},keep_default_na=False)
    decisions=pd.read_csv(outputs/'26_research_decisions.csv',dtype=str,keep_default_na=False)
    v031=json.loads((outputs/'24_research_quality_audit.json').read_text(encoding='utf-8'))
    financials,fstats=reconcile_financials(data/'verified_financials.csv',cutoff=cutoff)
    assumptions,vstats=value_assumptions(data/'valuation_assumptions.csv',cutoff=cutoff)
    primary=passed_primary_gate(financials) if enable_reviews else {}
    validvaluations={str(r.ticker):r.to_dict() for _,r in assumptions.iterrows()
            if r.valuation_status=='MODELED_MANUAL_INPUT_REVIEWED'} if enable_reviews else {}
    manual={str(r.ticker):r.to_dict() for _,r in decisions.iterrows()}
    rows=[]
    for _,r in ranked.iterrows():
        t=str(r.ticker)
        screened=str(r.get('v031_research_eligible','')).lower() in ('true','1')
        stage='SCREENED' if screened else 'REVIEW_REQUIRED'
        reasons=[]
        if not screened:reasons.append('SCREENING_GATE_FAILED')
        if t not in primary:reasons.append('THREE_SAME_PERIOD_PRIMARY_FINANCIAL_METRICS_NOT_RECONCILED')
        if screened and t in primary:stage='EVIDENCE_CHECKED'
        if t not in validvaluations:reasons.append('VALUATION_AND_COUNTEREVIDENCE_NOT_REVIEWED')
        if stage=='EVIDENCE_CHECKED' and t in validvaluations:
            val=validvaluations[t]
            if val['currency']!=primary[t]['currency']:
                reasons.append('VALUATION_CURRENCY_MISMATCH_TO_VERIFIED_FINANCIALS')
            else:stage='VALUATION_REVIEWED'
        decision=manual.get(t,{})
        reviewed=decision.get('decision')=='ACCEPTED' and all(str(decision.get(k,'')).strip()
             for k in ('decision_date','decision_reason','evidence_urls','analyst_reviewed_by',
                       'key_counterevidence','initial_thesis','revisit_trigger'))
        if not reviewed:reasons.append('HUMAN_ACCEPTANCE_WITH_COUNTEREVIDENCE_NOT_RECORDED')
        if stage=='VALUATION_REVIEWED' and reviewed:stage='MEMO_READY'
        row={'ticker':t,'company':r.get('company',''),'market':r.get('market',''),
            'priority_score':r.get('cross_industry_score_100',''),
            'research_stage':stage, 'memo_ready':stage=='MEMO_READY',
            'primary_metrics_reconciled':primary.get(t,{}).get('n',0),
            'primary_period_end':primary.get(t,{}).get('period_end',''),
            'primary_document_verification':'MANUALLY_ATTESTED' if t in primary else 'NONE',
            'valuation_reviewed':t in validvaluations,
            'analyst_decision':decision.get('decision',''),
            'blocking_reasons':'|'.join(dict.fromkeys(reasons))}
        if t in validvaluations:
            for k in ('intrinsic_bear','intrinsic_base','intrinsic_bull','reference_price','upside_base_pct'):
                row[k]=validvaluations[t].get(k,'')
        rows.append(row)
    stages=pd.DataFrame(rows)
    financials.to_csv(outputs/'30_primary_financial_reconciliation.csv',index=False,encoding='utf-8-sig')
    assumptions.to_csv(outputs/'31_valuation_scenario_audit.csv',index=False,encoding='utf-8-sig')
    stages.to_csv(outputs/'32_research_stage_gate.csv',index=False,encoding='utf-8-sig')
    memo=[]
    memo.extend(['# Asia GARP v0.5 — Evidence-Gated Investment Research','',
        '> Research workflow only. Screening rank is not a return forecast or a recommendation.','',
        f'- Analysis date (UTC): {cutoff.isoformat()}',
        '- Primary numbers below are manually attested, not machine verified against source PDFs.',
        '- Valuation scenarios are assumption-sensitive examples, not target prices.',''])
    for _,r in stages.head(30).iterrows():
        t=r.ticker
        memo.extend([f'## {_safe_markdown(r.company)} ({t}) — {r.research_stage}','',
            f'- Screening priority: {_safe_markdown(r.priority_score)} / 100 (UNVALIDATED for alpha)',
            f'- Primary metric count, same fiscal period: {r.primary_metrics_reconciled}',
            f'- Pending gates: {_safe_markdown(r.blocking_reasons) or "none"}'])
        if t in primary:
            memo.append(f"- Verified period: {primary[t]['period_end']}; currency: {primary[t]['currency']}; checked metrics: {', '.join(primary[t]['metrics'])}")
        if t in validvaluations:
            v=validvaluations[t]
            memo.append('- Illustrative DCF in '+v['currency']+': bear '+f"{v['intrinsic_bear']:.2f} / base {v['intrinsic_base']:.2f} / bull {v['intrinsic_bull']:.2f}"+' per share')
            memo.extend([f"- Investment hypothesis: {_safe_markdown(v['thesis'])}",
                f"- Catalyst: {_safe_markdown(v['catalyst'])}",
                f"- Strongest bear case: {_safe_markdown(v['bear_case'])}",
                f"- Counterevidence: {_safe_markdown(v['counterevidence'])}",
                f"- Thesis falsification: {_safe_markdown(v['falsification_trigger'])}",
                f"- Analyst source: {_safe_markdown(v['filing_url'])}"])
        else:
            memo.append('- Valuation: withheld until signed inputs and all counterarguments are supplied')
        memo.append('')
    (outputs/'33_analyst_memoranda.md').write_text('\n'.join(memo)+'\n',encoding='utf-8')
    stats={**fstats,**vstats, 'version':'0.5','asof_utc_date':cutoff.isoformat(),
        'primary_reviews_applied':bool(enable_reviews),
        'analyzed_n':len(stages),
        'screened_n':int(stages.research_stage.isin(['SCREENED','EVIDENCE_CHECKED','VALUATION_REVIEWED','MEMO_READY']).sum()),
        'evidence_checked_n':int(stages.research_stage.isin(['EVIDENCE_CHECKED','VALUATION_REVIEWED','MEMO_READY']).sum()),
        'valuation_reviewed_n':int(stages.research_stage.isin(['VALUATION_REVIEWED','MEMO_READY']).sum()),
        'memo_ready_n':int(stages.memo_ready.sum()),
        'reconciled_primary_metric_n':int(fstats['reconciled_n']) if enable_reviews else 0,
        'source_evidence_mode':'MANUAL_ONLY_FOR_NUMERIC_FILING_VERIFICATION',
        'future_return_predictive_validation':'NOT_PERFORMED',
        'research_accuracy_improvement':'NOT_PROVEN_BY_PIPELINE_TESTS',
        'trade_orders':'NONE',
        'baseline_v031':{k:v031.get(k) for k in ('analyzed_n','research_eligible_n',
            'primary_filing_financial_values_verified_n','quality_warning_n','analyst_accept_n',
            'point_in_time_future_return_test')},
        'delta_comparability':'CURRENT_V031_PIPELINE_SAME_RUN; quality gates added, not future return evidence'}
    (outputs/'34_research_quality_v05.json').write_text(json.dumps(stats,indent=2,ensure_ascii=False),encoding='utf-8')
    summary=['# v0.5 | Research Quality Upgrade Audit','',
        '**Research operational quality and investment decision quality are separate.**','',
        f"- Investigated: {stats['analyzed_n']}; screening eligible: {stats['screened_n']}",
        f"- Official financial rows manually reconciled: {stats['reconciled_primary_metric_n']} / submitted {stats['submitted_n']}",
        f"- Evidence-checked names: {stats['evidence_checked_n']}",
        f"- Model-validated DCF scenarios: {stats['valuation_model_valid_n']}",
        f"- Valuation-reviewed names: {stats['valuation_reviewed_n']}",
        f"- Human-signed memo-ready: {stats['memo_ready_n']}",
        '', '## Quality interpretation','',
        '- No signed primary numeric reviews means **zero** Evidence Checked and Memo Ready.',
        '- Failing period/currency matching or >2% vendor-primary differences blocks reconciliation.',
        '- A saved link, a headline, or a financial vendor field alone does not count as verified.',
        '- Analyst-submitted figures are not machine-parsed or independently source-audited.',
        '- DCF is a scenario sensitivity calculation based on reviewed inputs; assumptions can still be wrong.',
        '- No point-in-time forward-return backtest or predictive accuracy is claimed.',
        '', '## Baseline v0.31 diagnostics (same underlying engine/run)','',
        f"- Source-side eligible: {v031.get('research_eligible_n',0)}",
        f"- Source-side metric completeness: {v031.get('score_coverage_mean',0)}",
        f"- Source-side vendor anomalies: {v031.get('quality_warning_n',0)}",
        '', '## Next analyst actions','',
        '1. Read the named official filing page, sign the number and matched vendor period.',
        '2. Explain each blocked metric, especially mismatched vendor accounting periods.',
        '3. Document three valuation growth scenarios and competitive threats.',
        '4. Record a dated decision with a testable falsification rule.',
        '5. Only compare research hit rates after point-in-time prospective data collection.','']
    (outputs/'35_quality_upgrade_comparison.md').write_text('\n'.join(summary),encoding='utf-8')
    return stats
