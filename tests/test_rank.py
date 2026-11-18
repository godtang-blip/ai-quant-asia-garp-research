import pandas as pd
import pytest
from src.ranking import rate_peer_universe, diversified_shortlist
from src.universe import balanced_sample


def fixture():
    rows=[]
    for group in ['A','B']:
        for ticker,pe,growth in [('a',10,.30),('b',20,.20),('c',30,.10)]:
            rows.append(dict(ticker=group+ticker,peer_group=group,
                revenue_growth=growth,earnings_growth=growth,
                operating_margin=.2,roe=.2,fcf_yield=.05,
                forward_pe=pe,price_to_sales=5,fetch_error='',info_warning=''))
    return pd.DataFrame(rows)


def test_performance_and_price():
    r=rate_peer_universe(fixture()).set_index('ticker')
    assert r.loc['Aa','exploratory_score_100'] > r.loc['Ab','exploratory_score_100'] > r.loc['Ac','exploratory_score_100']
    assert r.loc['Aa','shortlist_eligible']


def test_no_missing_metric_pass():
    d=fixture()
    d.loc[0,['revenue_growth','earnings_growth','roe','fcf_yield']]=None
    r=rate_peer_universe(d).set_index('ticker')
    assert not r.loc['Aa','rankable']
    assert pd.isna(r.loc['Aa','exploratory_score_100'])


def test_peer_group_under_three():
    d=fixture().iloc[:2]
    assert not rate_peer_universe(d)['rankable'].any()


def test_duplicate_symbol():
    d=fixture();d.loc[1,'ticker']='Aa'
    with pytest.raises(ValueError):rate_peer_universe(d)


def test_invalid_pe_not_rewarded():
    d=fixture();d.loc[0,'forward_pe']=-4
    r=rate_peer_universe(d).set_index('ticker')
    assert pd.isna(r.loc['Aa','forward_pe'])


def test_extreme_PE_is_review_only():
    d=fixture();d['forward_pe']=d['forward_pe'].astype(float);d.loc[0,'forward_pe']=2.1
    r=rate_peer_universe(d).set_index('ticker')
    assert r.loc['Aa','rankable']
    assert not r.loc['Aa','shortlist_eligible']
    assert r.loc['Aa','screen_status']=='REVIEW_SUSPECT_METRICS'


def test_high_growth_flag_is_not_silent():
    d=fixture();d.loc[0,'revenue_growth']=1.268
    r=rate_peer_universe(d).set_index('ticker')
    assert 'VERIFY_PERIOD' in r.loc['Aa','data_quality_flags']
    assert not r.loc['Aa','shortlist_eligible']


def test_forward_pe_eps_crosscheck():
    d=fixture();d.loc[0,'current_price']=100;d.loc[0,'forward_eps']=2
    r=rate_peer_universe(d).set_index('ticker')
    assert 'PE_EPS_PRICE_INCONSISTENCY' in r.loc['Aa','data_quality_flags']


def test_diversified_top():
    r=rate_peer_universe(fixture())
    top=diversified_shortlist(r,max_items=4)
    assert len(top)==4
    assert top.iloc[0].peer_group!=top.iloc[1].peer_group
    assert top.peer_group.value_counts().max()<=2


def test_balanced_12_and_24_from_curated():
    u=pd.read_csv('data/universe.csv',dtype=str)
    a=balanced_sample(u,12)
    assert len(a)==12 and a.peer_group.nunique()==4
    assert sorted(a.peer_group.value_counts())==[3,3,3,3]
    assert a.peer_group.nunique()>1
    b=balanced_sample(u,24)
    assert len(b)==24 and b.peer_group.nunique()==8
    assert sorted(b.peer_group.value_counts())==[3]*8
    c=balanced_sample(u,0)
    assert len(c)==len(u)


def test_negative_limit_rejected():
    u=pd.read_csv('data/universe.csv',dtype=str)
    with pytest.raises(ValueError):balanced_sample(u,-1)
