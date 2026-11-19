import math
import pandas as pd
import pytest
from pathlib import Path
from src import v03, discovery, accounting
from src.fx import FXQuote, normalized_values
from src.scoring_v03 import anchor_score, compute_scores, SECTOR_WEIGHTS


def test_fixed_anchors_are_cross_industry_scale_but_sector_valuation_adjusted():
    assert anchor_score('revenue_growth',.30,'automakers') > anchor_score('revenue_growth',.05,'platforms')
    assert anchor_score('forward_pe',12,'automakers') < anchor_score('forward_pe',12,'healthcare_biopharma')
    assert all(abs(sum(row.values())-1)<1e-10 for row in SECTOR_WEIGHTS.values())


def test_missing_metrics_do_not_win_by_renormalization():
    samples=pd.DataFrame([
       {'ticker':'FULL','peer_group':'platforms','revenue_growth':.2,'earnings_growth':.22,
        'operating_margin':.2,'roe':.25,'fcf_yield':.06,'debt_to_equity_ratio':.3,
        'forward_pe':18,'price_to_sales':3,'price_change_52w':.2,'data_quality_flags':'','fetch_error':''},
       {'ticker':'SPARSE','peer_group':'platforms','revenue_growth':.4,'earnings_growth':None,
        'operating_margin':None,'roe':None,'fcf_yield':None,'debt_to_equity_ratio':None,
        'forward_pe':12,'price_to_sales':None,'price_change_52w':None,'data_quality_flags':'','fetch_error':''}
    ])
    r=compute_scores(samples).set_index('ticker')
    assert math.isnan(r.loc['SPARSE','cross_industry_score_100'])
    assert r.loc['FULL','v03_shortlist_eligible']
    assert r.loc['FULL','cross_industry_score_100']<=100


def test_weighted_coverage_keeps_the_inclusive_65_percent_boundary():
    boundary = {
        'ticker': 'BOUNDARY',
        'peer_group': 'platforms',
        'revenue_growth': .2,
        'operating_margin': .2,
        'roe': .25,
        'price_to_sales': 3,
        'debt_to_equity_ratio': .3,
        'price_change_52w': .2,
    }
    below = {**boundary, 'ticker': 'BELOW', 'price_to_sales': None}
    scored = compute_scores(pd.DataFrame([boundary, below])).set_index('ticker')
    assert scored.loc['BOUNDARY', 'score_coverage'] == .65
    assert math.isfinite(scored.loc['BOUNDARY', 'cross_industry_score_100'])
    assert 'INSUFFICIENT_METRIC_COVERAGE' not in scored.loc['BOUNDARY', 'v03_review_flags']
    assert scored.loc['BELOW', 'score_coverage'] == .55
    assert math.isnan(scored.loc['BELOW', 'cross_industry_score_100'])
    assert 'INSUFFICIENT_METRIC_COVERAGE' in scored.loc['BELOW', 'v03_review_flags']


class FixtureFX:
    def to_usd(self,currency):
        rates={'HKD':(0.13,0.129),'CNY':(0.14,0.135),'USD':(1,1)}
        return FXQuote(currency,'USD',*rates[currency],'2026-11-17','2025-11-17','2026-11-17','SYNTHETIC_FX_TEST') if currency in rates else None


def test_cross_currency_fcf_yield_recomputed_in_usd():
    x=normalized_values({'currency':'HKD','financial_currency':'CNY','market_cap':1000,
        'free_cashflow_raw':100,'current_price':50},FixtureFX())
    assert x['market_cap_usd']==pytest.approx(130)
    assert x['fcf_usd_proxy']==pytest.approx(13.5)
    assert x['fcf_yield']==pytest.approx(13.5/130)
    assert x['fx_price_asof']=='2026-11-17'
    assert x['fx_status']=='FX_CONVERTED_VENDOR_PERIOD_UNVERIFIED'


def test_cross_currency_fx_failure_never_divides_mismatched_units():
    class EmptyFX:
        def to_usd(self,c):return None
    x=normalized_values({'currency':'HKD','financial_currency':'CNY','market_cap':1000,
        'free_cashflow_raw':100,'current_price':50},EmptyFX())
    assert math.isnan(x['fcf_yield'])
    y=normalized_values({'currency':'HKD','financial_currency':'HKD','market_cap':1000,
        'free_cashflow_raw':100,'current_price':50},EmptyFX())
    assert y['fcf_yield']==pytest.approx(.1)


def test_gaap_needs_source_date_reviewer_to_mark_identified(tmp_path):
    p=tmp_path/'accounting_issuer_evidence.csv'
    p.write_text('ticker,reported_standard,source_url,filing_date,verified_by\nA.T,IFRS,,,\nB.T,IFRS,https://issuer.example/report,2026-09-01,Analyst\n')
    evidence=accounting.issuer_evidence(p)
    assert 'A.T' not in evidence
    a=accounting.accounting_basis('A.T','Japan',evidence)
    assert a['reported_accounting_standard'].startswith('UNKNOWN')
    b=accounting.accounting_basis('B.T','Japan',evidence)
    assert b['reported_accounting_standard']=='IFRS'
    assert 'NOT_RESTATED' in b['gaap_comparability_status']


def test_discovery_parses_only_real_table_codes():
    s='<table><thead><tr><th>Code</th><th>Company Name</th></tr></thead><tbody>'
    for n in range(7000,7040):s+=f'<tr><td>{n}</td><td>Company {n}</td></tr>'
    s+='</tbody></table>'
    r=discovery.parse_nikkei_html(s)
    assert len(r)==40
    assert r[0]['ticker']=='7000.T'
    assert r[0]['is_new_discovery']
    assert discovery.parse_nikkei_html('<table><tr><td>3</td></tr></table>')==[]


def test_discovery_source_failure_audited_not_guessed(monkeypatch):
    def fail():raise ConnectionError('provider unavailable')
    monkeypatch.setattr(discovery,'source_nikkei225',fail)
    base=pd.DataFrame([{'ticker':'2330.TW','company':'TSMC','market':'Taiwan','peer_group':'chip_manufacturing','industry_thesis':'test'}])
    combined,log=discovery.discover_universe(base,'nikkei')
    assert len(combined)==1 and log.loc[0,'status']=='FAILED_NO_FALLBACK'


def test_v03_full_synthetic_no_network(tmp_path,monkeypatch):
    universe=pd.read_csv('data/universe.csv').head(12)
    ufile=tmp_path/'universe.csv';universe.to_csv(ufile,index=False)
    def synthetic(ticker):
        return {'revenue_growth':.17,'earnings_growth':.25,'operating_margin':.20,'roe':.22,
          'forward_pe':19,'price_to_sales':3,'fcf_yield':.04,
          'debt_to_equity_ratio':.2,'price_change_52w':.15,
          'currency':'USD','financial_currency':'USD','market_cap':2e9,'current_price':100,
          'forward_eps':100/19,'free_cashflow_raw':80e6,
          'revenue_growth_period':'VENDOR_UNCONFIRMED',
          'reported_accounting_standard':'UNKNOWN_PRIMARY_FILING_REQUIRED',
          'data_source':'SYNTHETIC_UNIT_TEST','source_url':'https://example.org/not-real',
          'last_split_date_utc':''}
    monkeypatch.setattr(v03,'_fetch_vendor',synthetic)
    meta=v03.run(ufile,tmp_path/'out',max_symbols=0,discover_mode='off',fx_mode='off',delay_seconds=0)
    assert meta['fetched_n']==12 and meta['discovery_sources_failed']==0
    assert meta['shortlist_n']>0 and meta['actual_trades']=='NONE'
    for i in range(1,18):
        assert list((tmp_path/'out').glob(f'{i:02d}_*'))
    s=pd.read_csv(tmp_path/'out'/'15_cross_industry_scores.csv')
    assert 'sector_weights_used' in s.columns
    assert all(s.cross_industry_score_100.dropna().between(0,100))
    m=(tmp_path/'out'/'03_research_report.md').read_text()
    assert 'NOT buy recommendations' in m and 'unvalidated' in m


def test_v03_historical_replay_disables_live_fx(tmp_path,monkeypatch):
    universe=pd.read_csv('data/universe.csv').head(3)
    ufile=tmp_path/'universe.csv';universe.to_csv(ufile,index=False)
    snap=pd.DataFrame([{'ticker':v,'revenue_growth':.2,'earnings_growth':.1,'operating_margin':.2,'roe':.2,
        'forward_pe':20,'price_to_sales':3,'fcf_yield':.05,'currency':'HKD','financial_currency':'CNY',
        'data_quality_flags':'','fetch_error':''} for v in universe.ticker])
    sp=tmp_path/'snap.csv';snap.to_csv(sp,index=False)
    monkeypatch.setattr(v03,'YahooFX',lambda: (_ for _ in ()).throw(Exception('NO LIVE FX IN REPLAY')))
    meta=v03.run(ufile,tmp_path/'out',0,'off','live',0,sp)
    assert meta['data_mode']=='SNAPSHOT_REPLAY_NOT_LIVE'
    assert pd.read_csv(tmp_path/'out'/'13_fx_normalization_audit.csv')['fx_status'].eq('SNAPSHOT_REPLAY_CURRENT_FX_NOT_APPLIED').all()


def test_v03_discovered_candidates_stay_in_research_queue_not_final_shortlist(tmp_path,monkeypatch):
    curated=pd.read_csv('data/universe.csv').head(2)
    curfile=tmp_path/'universe.csv';curated.to_csv(curfile,index=False)
    def discover(base,mode,per_region):
        additions=pd.DataFrame([{'ticker':'9999.T','company':'Synthetic Inc','market':'Japan',
          'peer_group':'unclassified','industry_thesis':'DISCOVERED_UNREVIEWED',
          'is_new_discovery':True,'discovery_source':'SYNTHETIC_TEST_SOURCE'}])
        b=base.copy();b['is_new_discovery']=False;b['discovery_source']='CURATED'
        return pd.concat([b,additions],ignore_index=True),pd.DataFrame([{'source':'SYNTHETIC_TEST_SOURCE','status':'OK','received':1,'error':''}])
    monkeypatch.setattr(v03,'discover_universe',discover)
    def info(ticker):
        return {'revenue_growth':.2,'earnings_growth':.3,'operating_margin':.2,'roe':.2,
          'fcf_yield':.06,'forward_pe':15,'price_to_sales':2,
          'debt_to_equity_ratio':.3,'price_change_52w':.2,
          'vendor_industry':'Industrial Automation','currency':'USD','financial_currency':'USD',
          'source_url':'https://example.org/issuer','fetch_error':''}
    monkeypatch.setattr(v03,'_fetch_vendor',info)
    meta=v03.run(curfile,tmp_path/'out',max_symbols=0,discover_mode='nikkei',fx_mode='off',delay_seconds=0)
    assert meta['new_discovered_n']==1
    all_data=pd.read_csv(tmp_path/'out'/'01_all_research_candidates.csv').set_index('ticker')
    assert all_data.loc['9999.T','is_new_discovery']
    assert not all_data.loc['9999.T','v03_shortlist_eligible']


def test_bad_forward_pe_and_extreme_roe_are_review_flags():
    base={'ticker':'A','currency':'USD','financial_currency':'USD',
      'forward_pe':2,'roe':1.35,'operating_margin':.21,'revenue_growth':.2,
      'current_price':100,'forward_eps':10,'reported_accounting_standard':'UNKNOWN_PRIMARY_FILING_REQUIRED'}
    fl,limits=v03.audit_flags(base,set())
    assert 'EXTREME_PE' in fl
    assert 'EXTREME_ROE' in fl
    assert 'FORWARD_PE_EPS_PRICE_INCONSISTENCY' in fl
    assert 'ACCOUNTING_STANDARD_UNCONFIRMED' in limits
