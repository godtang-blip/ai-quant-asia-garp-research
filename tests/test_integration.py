import json
import pandas as pd
from src import screen


def test_offline_full_pipeline_24(tmp_path, monkeypatch):
    def fake_pull(ticker):
        # Clearly synthetic test values, NOT to be used as live research results.
        n=sum(map(ord,ticker))%5
        return dict(revenue_growth=.14+.02*n,earnings_growth=.13+.02*n,
            operating_margin=.15+.01*n,roe=.17+.01*n,fcf_yield=.025+.005*n,
            forward_pe=13+n*2,price_to_sales=3+n*.3,market_cap=1000000000,
            currency='KRW',financial_currency='KRW',current_price=100,
            forward_eps=100/(13+n*2),trailing_pe=13+n*2,
            info_warning='',provider_name='SYNTHETIC TEST',metric_period='SYNTHETIC',)
    monkeypatch.setattr(screen, 'pull_ticker', fake_pull)
    meta=screen.run(universe_file=screen.Path('data/universe.csv'), outputs=tmp_path, max_symbols=24, delay_seconds=0)
    assert meta['industry_groups_selected']==8
    assert meta['universe_n']==24
    assert meta['data_errors_n']==0
    assert meta['shortlist_n']>0
    for name in ['01_all_research_candidates.csv','02_research_shortlist.csv','03_research_report.md',
                 '04_run_metadata.json','05_data_quality_review.csv','06_peer_coverage.csv',
                 '07_investment_memo_TEMPLATE.md','08_balanced_selection.csv']:
        assert (tmp_path/name).exists(),name
    ranked=pd.read_csv(tmp_path/'01_all_research_candidates.csv')
    assert ranked['source_verification'].eq('VENDOR_SNAPSHOT_NOT_VERIFIED_AGAINST_FILINGS').all()
    assert 'NOT intrinsic value' in (tmp_path/'03_research_report.md').read_text()
    assert meta['filing_level_verification']=='NOT_PERFORMED'


def test_replay_marks_old_data(tmp_path):
    # Re-using a trusted local synthetic snapshot must not masquerade as live data.
    universe=pd.read_csv('data/universe.csv').iloc[:6].copy()
    ufile=tmp_path/'universe.csv';universe.to_csv(ufile,index=False)
    rows=[]
    for t in universe.ticker:
        rows.append(dict(ticker=t,revenue_growth=.2,earnings_growth=.2,
                        operating_margin=.2,roe=.2,fcf_yield=.04,forward_pe=15,price_to_sales=3,
                        info_warning='',fetch_error='',retrieved_at_utc='2025-01-01T00:00:00Z'))
    snap=tmp_path/'snap.csv';pd.DataFrame(rows).to_csv(snap,index=False)
    meta=screen.run(ufile,tmp_path/'outputs',max_symbols=0,snapshot_csv=snap)
    assert meta['data_mode']=='SNAPSHOT_REPLAY_NOT_LIVE'
    assert meta['universe_n']==6


def test_prior_open_review_blocks_shortlist_not_manual_research(tmp_path, monkeypatch):
    # Existing concern must remain visible, without pretending to know actual accuracy.
    uni = pd.DataFrame([{'ticker':x,'company':x,'market':'KR','peer_group':'A','industry_thesis':'test'}
                       for x in ['AA','BB','CC']])
    ufile=tmp_path/'universe.csv';uni.to_csv(ufile,index=False)
    pd.DataFrame([{'ticker':'BB','observation':'unreconciled YoY basis','required_manual_check':'filing','status':'OPEN'}]).to_csv(
        tmp_path/'prior_discrepancies_to_review.csv',index=False)
    def fake_pull(ticker):
        return dict(revenue_growth=.2,earnings_growth=.2,operating_margin=.2,roe=.2,
                    fcf_yield=.05,forward_pe=15,price_to_sales=3,
                    info_warning='',currency='KRW',financial_currency='KRW')
    monkeypatch.setattr(screen,'pull_ticker',fake_pull)
    screen.run(ufile,tmp_path/'output',max_symbols=0,delay_seconds=0)
    out=pd.read_csv(tmp_path/'output'/'01_all_research_candidates.csv').set_index('ticker')
    assert not out.loc['BB','shortlist_eligible']
    assert 'PRIOR_VENDOR_DISCREPANCY' in out.loc['BB','data_quality_flags']
    assert out.loc['BB','rankable']
