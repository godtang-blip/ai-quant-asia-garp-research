"""Offline quality and source-gate regression; no live requests, no trades."""
import json
from pathlib import Path
import pandas as pd
import pytest
from src.official_universe import parse_jpx_table, parse_twse_list, OFFICIAL_SOURCE_REGISTRY
from src.research_quality import (FIN_FIELDS, DCF_FIELDS, reconcile_financials,passed_primary_gate,
                                  dcf_per_share,value_assumptions,enhance)
from src.v05 import run as run_v05
import datetime as dt

CUTOFF=dt.date(2026,11,18)
URL='https://issuer.example.net/filing/2026-06'

def a_fin(metric='revenue',ticker='000990.KS'):
    return dict(ticker=ticker, metric=metric, primary_value='100000000',vendor_value='100000000',
        currency='KRW',unit='KRW',fiscal_period_start='2026-01-01',
        fiscal_period_end='2026-06-30',vendor_period_start='2026-01-01',
        vendor_period_end='2026-06-30',filing_date='2026-08-15',filing_url=URL,
        filing_page='p. 34',statement_label='Income statement line item',
        source_type='ISSUER_FILING',review_status='CONFIRMED',reviewer='Analyst')

def a_dcf(ticker='000990.KS'):
    return dict(ticker=ticker,asof_date='2026-11-18',currency='KRW',
        fcff_year0='1000000000',shares_outstanding='100000000',net_debt='200000000',
        current_price='40',growth_bear='-0.1',growth_base='0.08',growth_bull='0.2',
        discount_rate='0.12',terminal_growth='0.025',forecast_years='5',filing_url=URL,
        reviewer='Analyst',thesis='Three-year earnings durability driven by sales growth',
        catalyst='Company product demand recovery in next fiscal year',
        bear_case='Competitor pricing pressure could reduce cashflow materially',
        counterevidence='Latest segment margins are declining despite revenue growth',
        falsification_trigger='Exit research thesis if margins decline for two quarters')

def save_rows(path,rows,cols):
    pd.DataFrame(rows,columns=cols).to_csv(path,index=False,encoding='utf-8')

def test_official_jpx_filters_products_and_unsupported_alphanumeric():
    f=pd.DataFrame({'Code':['7203','123A','1321','8306'],
      'Company Name':['Toyota','A issue','ETF fund','Bank'],
      'Market/Products':['Prime Market (Domestic Stocks)','Growth Market (Domestic Stocks)',
                         'ETF','Standard Market (Domestic Stocks)']})
    found=parse_jpx_table(f)
    assert [x['ticker'] for x in found]==['7203.T','8306.T']
    assert all(x['discovery_source'].startswith('https://www.jpx.co.jp/') for x in found)


def test_official_twse_only_listed_code_4_digit_and_auditable():
    rows=parse_twse_list([{'公司代號':'2330','公司名稱':'台積電'},
       {'公司代號':'0050','公司名稱':'TEST INC'}, {'公司代號':'bad','公司名稱':'ignore'}])
    # Listing API itself is not an investment-security type verification.
    assert len(rows)==2 and rows[0]['ticker']=='2330.TW'
    assert all(x['security_type_status']!='VERIFIED_EQUITY_VENDOR' for x in rows)
    assert len(OFFICIAL_SOURCE_REGISTRY)==5


def test_financial_primary_audit_requires_period_match_source_and_reviewer(tmp_path):
    r=a_fin();r['vendor_period_end']='2026-03-31'
    save_rows(tmp_path/'source.csv',[r],FIN_FIELDS)
    frame,summary=reconcile_financials(tmp_path/'source.csv',cutoff=CUTOFF)
    assert frame.iloc[0].validation_status=='BLOCKED'
    assert 'VENDOR_PERIOD_NOT_ALIGNED' in frame.iloc[0].validation_flags
    assert summary['reconciled_n']==0
    r=a_fin();r['vendor_value']='90000000'
    save_rows(tmp_path/'source.csv',[r],FIN_FIELDS)
    frame,_=reconcile_financials(tmp_path/'source.csv',cutoff=CUTOFF)
    assert 'VENDOR_PRIMARY_DISCREPANCY_GT_2PCT' in frame.iloc[0].validation_flags


def test_financial_gate_cannot_count_duplication_or_wrong_period(tmp_path):
    rows=[a_fin('revenue'),a_fin('revenue'),a_fin('operating_income'),a_fin('net_income')]
    rows[3]['fiscal_period_end']=rows[3]['vendor_period_end']='2026-09-30'
    rows[3]['filing_date']='2026-10-15'
    save_rows(tmp_path/'source.csv',rows,FIN_FIELDS)
    result,_=reconcile_financials(tmp_path/'source.csv',cutoff=CUTOFF)
    assert passed_primary_gate(result)=={}
    rows[3]['fiscal_period_end']=rows[3]['vendor_period_end']='2026-06-30'
    save_rows(tmp_path/'source.csv',rows,FIN_FIELDS)
    result,_=reconcile_financials(tmp_path/'source.csv',cutoff=CUTOFF)
    assert passed_primary_gate(result)['000990.KS']['n']==3


def test_asof_cutoff_prevents_future_filing_confirmation(tmp_path):
    r=a_fin();r['filing_date']='2026-12-01'
    save_rows(tmp_path/'source.csv',[r],FIN_FIELDS)
    df,_=reconcile_financials(tmp_path/'source.csv',cutoff=CUTOFF)
    assert 'PRIMARY_PERIOD_OR_DATE_INVALID' in df.iloc[0].validation_flags


def test_dcf_scenario_order_and_discount_logic():
    vals=dcf_per_share(a_dcf())
    assert vals['intrinsic_bear']<vals['intrinsic_base']<vals['intrinsic_bull']
    assert vals['model_type'].startswith('ILLUSTRATIVE')
    r=a_dcf();r['discount_rate']='0.01'
    with pytest.raises(ValueError,match='Discount'):
        dcf_per_share(r)
    r=a_dcf();r['growth_bear']='0.30'
    with pytest.raises(ValueError,match='Scenario'):
        dcf_per_share(r)


def test_no_sources_never_auto_upgrade(tmp_path):
    pd.DataFrame([{'ticker':'000990.KS','company':'Test','market':'Korea','cross_industry_score_100':80,
        'v031_research_eligible':True}]).to_csv(tmp_path/'01_all_research_candidates.csv',index=False)
    (tmp_path/'24_research_quality_audit.json').write_text(json.dumps({'research_eligible_n':1}))
    pd.DataFrame(columns=['ticker','decision']).to_csv(tmp_path/'26_research_decisions.csv',index=False)
    data=tmp_path/'data';data.mkdir()
    save_rows(data/'verified_financials.csv',[],FIN_FIELDS)
    save_rows(data/'valuation_assumptions.csv',[],DCF_FIELDS)
    stats=enhance(tmp_path,data,asof_date=CUTOFF)
    assert stats['screened_n']==1 and stats['memo_ready_n']==0
    assert stats['evidence_checked_n']==0
    stage=pd.read_csv(tmp_path/'32_research_stage_gate.csv')
    assert stage.loc[0,'research_stage']=='SCREENED'


def test_signed_evidence_valuation_and_acceptance_progress_gates(tmp_path):
    pd.DataFrame([{'ticker':'000990.KS','company':'DB HiTek','market':'Korea','cross_industry_score_100':75,
        'v031_research_eligible':True}]).to_csv(tmp_path/'01_all_research_candidates.csv',index=False)
    (tmp_path/'24_research_quality_audit.json').write_text(json.dumps({'research_eligible_n':1}))
    decisions=pd.DataFrame([{'ticker':'000990.KS','decision':'ACCEPTED','decision_date':'2026-11-18',
        'decision_reason':'Valuation and margins evaluated','evidence_urls':URL,
        'analyst_reviewed_by':'Reviewer','key_counterevidence':'Shortfall of demand',
        'initial_thesis':'Competitive manufacturing economics','revisit_trigger':'Next report'}])
    decisions.to_csv(tmp_path/'26_research_decisions.csv',index=False)
    data=tmp_path/'data';data.mkdir()
    save_rows(data/'verified_financials.csv',[a_fin(m) for m in ('revenue','operating_income','net_income')],FIN_FIELDS)
    save_rows(data/'valuation_assumptions.csv',[a_dcf()],DCF_FIELDS)
    report=enhance(tmp_path,data,asof_date=CUTOFF)
    assert report['reconciled_primary_metric_n']==3
    assert report['evidence_checked_n']==1 and report['memo_ready_n']==1
    assert pd.read_csv(tmp_path/'32_research_stage_gate.csv').loc[0,'research_stage']=='MEMO_READY'
    assert 'Strongest bear case' in (tmp_path/'33_analyst_memoranda.md').read_text()


def test_replay_run_requires_off_and_does_not_promote_without_cutoff(tmp_path):
    with pytest.raises(ValueError,match='lookahead'):
        run_v05(Path('data/universe.csv'),tmp_path/'out',1,'all5_official','off',0,
                tmp_path/'snapshot.csv',90,'off',0)


def test_valuation_requires_counterarguments(tmp_path):
    r=a_dcf();r['counterevidence']='none'
    save_rows(tmp_path/'vals.csv',[r],DCF_FIELDS)
    frame,stats=value_assumptions(tmp_path/'vals.csv',cutoff=CUTOFF)
    assert frame.loc[0,'valuation_status']=='BLOCKED'
    assert stats['valuation_model_valid_n']==0


def test_krx_official_list_restricts_market_and_requires_symbol():
    from src.official_universe import parse_krx_list
    rows=parse_krx_list({'response':{'header':{'resultCode':'00'},'body':{'items':{'item':[
      {'srtnCd':'A005930','itmsNm':'삼성전자','mrktCtg':'KOSPI'},
      {'srtnCd':'035720','itmsNm':'카카오','mrktCtg':'KOSDAQ'},
      {'srtnCd':'0123','itmsNm':'NO','mrktCtg':'KOSPI'},
      {'srtnCd':'123456','itmsNm':'NO','mrktCtg':'KONEX'}]}}}})
    assert [r['ticker'] for r in rows]==['005930.KS','035720.KQ']
