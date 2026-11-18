import pandas as pd
import pytest
from src.ranking import METRICS, rate_peer_universe

def fixture():
    rows = []
    for ticker, pe, growth in [("A", 10, 0.30), ("B", 20, 0.20), ("C", 30, 0.10)]:
        rows.append({"ticker":ticker,"peer_group":"semiconductors","revenue_growth":growth,
            "earnings_growth":growth,"operating_margin":0.20,"roe":0.20,"fcf_yield":0.05,
            "forward_pe":pe,"price_to_sales":5})
    return pd.DataFrame(rows)

def test_lower_price_and_higher_growth_score_better():
    r = rate_peer_universe(fixture()).set_index('ticker')
    assert r.loc['A','exploratory_score_100'] > r.loc['B','exploratory_score_100'] > r.loc['C','exploratory_score_100']
    assert r.loc['A','rankable']

def test_missing_fields_never_pass():
    df=fixture()
    df.loc[0,['revenue_growth','earnings_growth','roe','fcf_yield']] = None
    r=rate_peer_universe(df).set_index('ticker')
    assert not bool(r.loc['A','rankable'])
    assert pd.isna(r.loc['A','exploratory_score_100'])

def test_peer_groups_under_three_not_scored():
    df=fixture().iloc[:2].copy()
    assert not rate_peer_universe(df)['rankable'].any()

def test_duplicate_ticker_rejected():
    df=fixture(); df.loc[1,'ticker']='A'
    with pytest.raises(ValueError):rate_peer_universe(df)

def test_negative_pe_not_rewarded():
    df=fixture(); df.loc[0,'forward_pe']=-4
    r=rate_peer_universe(df).set_index('ticker')
    assert pd.isna(r.loc['A','forward_pe'])
