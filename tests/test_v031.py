"""v0.3.1 offline regression tests. No Yahoo/Google/DART network calls."""
from __future__ import annotations
import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from src import discovery_v031 as d
from src import evidence as e
from src import quality_v031 as q
from src.v031 import run


def test_five_market_symbol_validation():
    assert d.ticker_market_valid('005930.KS', 'Korea')
    assert d.ticker_market_valid('300750.SZ', 'China')
    assert d.ticker_market_valid('600519.SS', 'China')
    assert d.ticker_market_valid('2330.TW', 'Taiwan')
    assert d.ticker_market_valid('6758.T', 'Japan')
    assert d.ticker_market_valid('0700.HK', 'Hong Kong')
    assert not d.ticker_market_valid('BABA', 'Hong Kong')
    assert not d.ticker_market_valid('70600001.KS', 'Korea')
    assert not d.ticker_market_valid('300750.SZ', 'Japan')


def test_security_type_filters():
    assert d.equity_type_status({'quoteType': 'EQUITY'}) == 'VERIFIED_EQUITY_VENDOR'
    assert d.equity_type_status({'quoteType': 'ETF'}) == 'REJECT_NON_EQUITY'
    assert d.equity_type_status({}) == 'TYPE_UNCONFIRMED'


def test_screener_pagination_market_rejection_and_type_guard(monkeypatch):
    calls=[]
    def fake_screen(query, offset, size):
        calls.append((offset,size))
        if offset == 0:
            return {'quotes':[{'symbol':'300750.SZ','quoteType':'EQUITY','longName':'CATL'},
                              {'symbol':'BABA','quoteType':'EQUITY','longName':'ADR'}]}
        return {'quotes':[{'symbol':'600519.SS','quoteType':'EQUITY','shortName':'Moutai'},
                          {'symbol':'510300.SS','quoteType':'ETF','shortName':'ETF'}]}
    import sys
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(EquityQuery=lambda *a: a,screen=fake_screen))
    rows,log=d.source_region('China', max_rows=4,page_size=2)
    assert [r['ticker'] for r in rows]==['300750.SZ','600519.SS']
    assert calls==[(0,2),(2,2)]
    assert log['rejected_non_equity']==1 and log['rejected_bad_symbol']==1


def test_balanced_sample_avoids_country_monopoly():
    rows=[]
    for market,tickers in {'Japan':['1111.T','2222.T','3333.T'],
                           'Korea':['005930.KS','000660.KS'],
                           'China':['600519.SS','300750.SZ']}.items():
        rows.extend({'market':market,'ticker':t,'is_new_discovery':i>0} for i,t in enumerate(tickers))
    result=d.select_market_balanced(pd.DataFrame(rows),6)
    assert result.market.value_counts().to_dict()=={'Japan':2,'Korea':2,'China':2}
    assert len(d.select_market_balanced(pd.DataFrame(rows),0))==7


def test_discovery_sources_report_actual_failures_no_guessed_fallback(monkeypatch):
    base=pd.DataFrame([{'ticker':'005930.KS','company':'Samsung','market':'Korea','peer_group':'chip_manufacturing','industry_thesis':'curated'}])
    monkeypatch.setattr(d,'source_nikkei225',lambda: [{'ticker':'6758.T','company':'Sony','market':'Japan','peer_group':'unclassified','discovery_source':'https://indexes.nikkei.co.jp/'}])
    def vendor(market,max_rows):
        if market=='China':raise RuntimeError('vendor unavailable')
        return ([{'ticker':'005930.KS','company':'dupe','market':'Korea','peer_group':'unclassified','discovery_source':'Yahoo fixture'}] if market=='Korea' else []),{'market':market}
    monkeypatch.setattr(d,'source_region',vendor)
    combined,log=d.discover_five_markets(base,'all5',20)
    assert len(combined)==2 and '6758.T' in set(combined.ticker)
    assert log.loc[log.source.eq('yahoo_screener_China'),'status'].iat[0]=='FAILED_NO_FALLBACK'
    assert combined.ticker.is_unique


def test_news_headline_rss_has_date_and_url_not_full_text():
    xml=b'''<rss><channel><item><title>Results released</title>
       <link>https://example.com/earnings</link><pubDate>Tue, 17 Nov 2026 05:00:00 GMT</pubDate>
       <source>Example Newspaper</source><description>Unverified commentary</description></item></channel></rss>'''
    class Session:
        def get(self,*a,**kw):
            assert kw.get('timeout')
            return SimpleNamespace(content=xml,raise_for_status=lambda:None)
    res=e.news_rss('Test Co','1111.T',session=Session())
    assert len(res)==1 and res[0]['published_date']=='2026-11-17'
    assert res[0]['source_url']=='https://example.com/earnings'
    assert 'Unverified commentary' not in str(res)


def test_dart_corp_mapping_and_filing_metadata():
    xml=b'<result><list><corp_code>00126380</corp_code><corp_name>Samsung</corp_name><stock_code>005930</stock_code></list></result>'
    mem=io.BytesIO()
    with zipfile.ZipFile(mem,'w') as z:z.writestr('CORPCODE.xml',xml)
    class Session:
        def get(self,url,**kw):
            if url.endswith('corpCode.xml'):return SimpleNamespace(content=mem.getvalue(),raise_for_status=lambda:None)
            return SimpleNamespace(json=lambda:{'status':'000','list':[{'rcept_no':'20261117000001','rcept_dt':'20261117','report_nm':'Quarter report'}]},raise_for_status=lambda:None)
    mapping=e.dart_stock_code_map('TEST',session=Session())
    docs=e.dart_recent_filings('005930',mapping,'TEST',session=Session())
    assert mapping['005930']['corp_code']=='00126380'
    assert len(docs)==1 and docs[0]['published_date']=='2026-11-17'
    assert docs[0]['source_url'].startswith('https://dart.fss.or.kr/')


def test_manual_rejected_thesis_requires_evidence(tmp_path):
    file=tmp_path/'decisions.csv'
    fields=['ticker','company','decision','decision_date','initial_thesis','key_counterevidence',
            'decision_reason','evidence_urls','revisit_trigger','analyst_reviewed_by']
    row=dict.fromkeys(fields,'')
    row.update(ticker='9999.HK',company='Test',decision='REJECTED',decision_date='2026-11-18',
               initial_thesis='Strong pricing power',key_counterevidence='Confirmed margin compression',
               decision_reason='Original pricing thesis disproven',
               evidence_urls='https://example.org/disclosure',revisit_trigger='Two quarters of pricing recovery',
               analyst_reviewed_by='Analyst')
    pd.DataFrame([row]).to_csv(file,index=False)
    got=e.read_manual_decisions(file)
    assert got.iloc[0].decision=='REJECTED'
    row['evidence_urls']=''
    pd.DataFrame([row]).to_csv(file,index=False)
    with pytest.raises(ValueError,match='requires'):
        e.read_manual_decisions(file)


def test_evidence_off_safely_returns_named_empty_tables():
    res=e.collect_evidence(pd.DataFrame(),mode='off')
    assert set(res)=={'news','earnings','filings','ledger','log'}
    assert 'ticker' in res['news'].columns and 'ticker' in res['ledger'].columns
    assert all(df.empty for df in res.values())


def test_vendor_quarterly_values_no_fake_filing(monkeypatch):
    import sys
    cols=[pd.Timestamp('2026-09-30'),pd.Timestamp('2026-06-30')]
    rows=['Total Revenue','Operating Income','Diluted EPS']
    stmt=pd.DataFrame([[100,90],[20,17],[1.2,1.0]],index=rows,columns=cols)
    monkeypatch.setitem(sys.modules,'yfinance',SimpleNamespace(Ticker=lambda ticker:SimpleNamespace(quarterly_income_stmt=stmt)))
    got=e.quarterly_vendor_rows('1111.T')
    assert got[0]['quarter_ending']=='2026-09-30' and got[0]['operating_income']==20
    assert 'net_income' not in got[0]  # unavailable is NOT fabricated


def test_sensitivity_does_not_claim_alpha():
    frame=pd.DataFrame([{'ticker':f'{n}.T','company':f'Company {n}','market':'Japan','peer_group':'chip_components',
                        'cross_industry_score_100':50+n,'v031_research_eligible':True,
                        **{f'{cat}_score_100':40+n for cat in q.CATEGORY_WEIGHTS},
                        **{f'{cat}_coverage':1.0 for cat in q.CATEGORY_WEIGHTS}} for n in range(4)])
    output,meta=q.sensitivity_report(frame)
    assert len(output)==4 and meta['scenarios']==10
    assert meta['not_predictive_validation'] is True
    assert (output['rank_range']==0).all()


def test_provisional_new_discovery_can_enter_research_gate(monkeypatch,tmp_path):
    from src import v031 as v
    inputs=tmp_path/'data'
    inputs.mkdir()
    (inputs/'universe.csv').write_text('ticker,company,market,peer_group,industry_thesis\n'
                                      '005930.KS,Samsung,Korea,chip_manufacturing,curated\n',encoding='utf-8')
    def discover(base,mode,per_region):
        new=pd.DataFrame([{'ticker':'300750.SZ','company':'Example new','market':'China',
                           'peer_group':'chip_components','industry_thesis':'new',
                           'is_new_discovery':True,'discovery_source':'Vendor China',
                           'security_type_status':'VERIFIED_EQUITY_VENDOR'}])
        out=base.assign(is_new_discovery=False,discovery_source='CURATED',
                        security_type_status='CURATED_NEEDS_VERIFICATION')
        return pd.concat([out,new],ignore_index=True),pd.DataFrame(columns=['status','source'])
    def vendor(ticker):
        return {'revenue_growth':.25,'earnings_growth':.26,'operating_margin':.2,'roe':.18,
                'forward_pe':22,'price_to_sales':2.5,'debt_to_equity_ratio':.4,
                'price_change_52w':.15,'fcf_yield':.04,
                'currency':'CNY','financial_currency':'CNY',
                'vendor_quote_type':'EQUITY','vendor_industry':'semiconductors',
                'revenue_growth_period':'VENDOR_UNCONFIRMED',
                'earnings_growth_period':'VENDOR_UNCONFIRMED',
                'source_url':'https://finance.yahoo.com/quote/'+ticker}
    monkeypatch.setattr(v,'discover_five_markets',discover)
    monkeypatch.setattr(v,'_fetch_vendor',vendor)
    out=tmp_path/'result'
    meta=v.run(inputs/'universe.csv',out,0,'all5','off',0,None,90,'off',0)
    assert meta['new_discovered_n']==1 and meta['new_research_eligible_n']==1
    shortlist=pd.read_csv(out/'02_research_shortlist.csv')
    entry=shortlist.set_index('ticker').loc['300750.SZ']
    assert entry['v031_research_status']=='PROVISIONAL_NEW_DISCOVERY'
    assert not bool(entry['v031_memo_ready'])


def test_snap_replay_creates_quality_evidence_and_decision_files(tmp_path):
    base=Path(__file__).resolve().parents[1]
    snap=tmp_path/'synthetic_vendor_snapshot.csv'
    pd.DataFrame([{'ticker':'005930.KS','revenue_growth':.12,'earnings_growth':.14,
                   'operating_margin':.2,'roe':.17,'forward_pe':18,'price_to_sales':2.1,
                   'debt_to_equity_ratio':.45,'price_change_52w':.09,
                   'currency':'KRW','financial_currency':'KRW','vendor_quote_type':'EQUITY',
                   'fx_status':'SNAPSHOT_NO_LIVE_FX'}]).to_csv(snap,index=False)
    output=tmp_path/'outputs'
    meta=run(base/'data/universe.csv',output,0,'off','off',0.0,snap,90,'full',8)
    assert meta['data_mode']=='SNAPSHOT_REPLAY_NOT_LIVE'
    assert meta['evidence_mode']=='off'
    assert len(list(output.iterdir()))==29
    quality=json.loads((output/'24_research_quality_audit.json').read_text(encoding='utf-8'))
    assert quality['primary_filing_financial_values_verified_n']==0
    assert (output/'27_evidence_book.md').exists()
    assert (output/'23_same_input_weight_sensitivity.csv').exists()
