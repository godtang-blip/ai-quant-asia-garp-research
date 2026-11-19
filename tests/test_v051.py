"""v0.5.1 regression tests. All external sources are mocked; no live-coverage claim."""
from __future__ import annotations
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
import pandas as pd
import pytest
from src import official_universe as off
from src.v031 import vendor_industry_group
from src.quality_v051 import (headline_entity_audit, coverage_audit,
                              enhance_v051, produce_research_queues)


def test_jpx_headers_english():
    frame=pd.DataFrame({'Code':['6758','7203','1343','9999','1301'],
         'Name (English)':['Sony','Toyota','ETF','Foreign Co','REIT Co'],
         'Market/Products':['Prime Market','Standard Market','ETF','Foreign Growth','REIT']})
    got=off.parse_jpx_table(frame)
    assert set(x['ticker'] for x in got)=={'6758.T','7203.T'}
    assert all(x['peer_group']=='unclassified' for x in got)


def test_jpx_headers_after_title_rows():
    raw=pd.DataFrame([
        ['List of TSE-listed issues',None,None],
        ['as of Oct 2026',None,None],
        ['Local Code','Company Name','Market Segment'],
        ['6758','Sony Group','Prime'],
        ['7203','Toyota','Standard'],
        ['9999','X','ETF']])
    got=off.parse_jpx_table(raw)
    assert [x['ticker'] for x in got]==['6758.T','7203.T']


def test_jpx_headers_japanese():
    frame=pd.DataFrame({'コード':['6758','7203'],'銘柄名':['ソニー','トヨタ'],
                        '市場・商品区分':['プライム','スタンダード']})
    assert len(off.parse_jpx_table(frame))==2


def test_jpx_unknown_schema_fails_closed():
    with pytest.raises(ValueError,match='schema/header unrecognized'):
        off.parse_jpx_table(pd.DataFrame({'id':[6758],'label':['Sony'],'kind':['Prime']}))


def test_jpx_download_parses_excel_preamble():
    buf=BytesIO()
    pd.DataFrame([['Date',None,None],['Code','Company Name','Market/Products'],
                  ['6758','Sony','Prime'],['1343','ETF','ETF']]).to_excel(buf,index=False,header=False)
    class Session:
        def get(self,*args,**kwargs):
            return SimpleNamespace(content=buf.getvalue(),raise_for_status=lambda:None)
    got=off.source_jpx_list(Session())
    assert [row['ticker'] for row in got]==['6758.T']


def test_umbrella_components_not_electrification():
    assert vendor_industry_group('Electronic Components','Technology')=='unclassified'
    assert vendor_industry_group('Electrical Components','Industrials')=='unclassified'
    assert vendor_industry_group('Industrial Automation','Industrials')=='industrial_electrification'
    assert vendor_industry_group('Semiconductor Equipment','Technology')=='chip_equipment'


def test_news_other_company_ticker_is_quarantined():
    verdict,reason=headline_entity_audit('9911.HK','Newborn Town Inc',
              'Huitongda Network Co., Ltd. (9878.HK) returns chart')
    assert verdict.startswith('QUARANTINE')
    assert '9878.HK' in reason


def test_news_title_name_does_not_verify_article():
    verdict,_=headline_entity_audit('9911.HK','Newborn Town Inc',
              'Newborn Town first-half earnings increase')
    assert verdict=='PROVISIONAL_NAME_MATCH'


def test_news_unrelated_keyword_not_entity_evidence():
    verdict,_=headline_entity_audit('9911.HK','Newborn Town Inc',
              'Asian internet companies report revenue')
    assert verdict=='QUARANTINE_NAME_UNCONFIRMED'


def _fixture_outputs(tmp_path:Path):
    outputs=tmp_path/'outputs';outputs.mkdir()
    listed=pd.DataFrame([
        {'ticker':'2330.TW','company':'TSMC','market':'Taiwan','peer_group':'chip_components',
         'v031_research_eligible':True,'cross_industry_score_100':83,'fetch_error':'',
         'sector_mapping_status':'VENDOR_HEURISTIC_NEEDS_REVIEW'},
        {'ticker':'7203.T','company':'Toyota','market':'Japan','peer_group':'automakers',
         'v031_research_eligible':True,'cross_industry_score_100':80,'fetch_error':'',
         'sector_mapping_status':'CURATED_HUMAN_TAXONOMY_UNVERIFIED'},
        {'ticker':'9911.HK','company':'Newborn Town','market':'Hong Kong','peer_group':'platforms',
         'v031_research_eligible':False,'cross_industry_score_100':98,'fetch_error':'',
         'sector_mapping_status':'VENDOR_HEURISTIC_NEEDS_REVIEW'},
    ])
    listed.to_csv(outputs/'01_all_research_candidates.csv',index=False)
    listed[['ticker','company','market']].to_csv(outputs/'11_discovery_universe.csv',index=False)
    listed[['ticker','company','market']].to_csv(outputs/'08_selected_universe.csv',index=False)
    pd.DataFrame([{'source':'official_twse_listed_companies','status':'OK','accepted_pattern':1093},
                  {'source':'official_jpx_full_listing','status':'FAILED_NO_FALLBACK','accepted_pattern':0}]).to_csv(
                      outputs/'12_discovery_sources_log.csv',index=False)
    pd.DataFrame([{'ticker':'9911.HK','identifier':'9911|bad','title':'Huitongda Network (9878.HK) shares gain',
                   'source_url':'https://example.com','published_date':'','source_name':'Newswire'}]).to_csv(
                       outputs/'19_news_headlines.csv',index=False)
    pd.DataFrame([{'ticker':'9911.HK','company':'Newborn Town','market':'Hong Kong',
                   'evidence_type':'NEWS_HEADLINE','identifier':'9911|bad',
                   'verification_status':'HEADLINE_COLLECTED_ARTICLE_UNREAD','title':'Huitongda Network (9878.HK) shares gain',
                   'source_url':'https://example.com','claim_supported':'','analyst_note':'','published_date':''}]).to_csv(
                       outputs/'18_evidence_ledger.csv',index=False)
    listed[['ticker','company','market']].head(0).to_csv(outputs/'02_research_shortlist.csv',index=False)
    (outputs/'34_research_quality_v05.json').write_text(json.dumps({'memo_ready_n':0}))
    data=tmp_path/'data';data.mkdir()
    pd.DataFrame(columns=['ticker','company','decision','decision_date','initial_thesis','key_counterevidence',
        'decision_reason','evidence_urls','revisit_trigger','analyst_reviewed_by']).to_csv(data/'research_decisions.csv',index=False)
    return outputs,data


def test_coverage_status_and_no_fake_five_market_census(tmp_path):
    outputs,data=_fixture_outputs(tmp_path)
    frame,stats=coverage_audit(outputs,'all5_official')
    assert stats['market_coverage_status']=='PARTIAL_COVERAGE'
    assert 'Japan' in stats['markets_without_retrieved_official_issuer_list']
    assert stats['full_five_market_census_verified'] is False
    assert frame.loc[frame.market.eq('Taiwan'),'official_rows_received'].iat[0]==1093


def test_global_and_market_queues_are_separate(tmp_path):
    outputs,data=_fixture_outputs(tmp_path)
    original = (outputs/'01_all_research_candidates.csv').read_bytes()
    produce_research_queues(outputs,per_market=1,global_top=2)
    assert (outputs/'01_all_research_candidates.csv').read_bytes() == original
    market_only = pd.read_csv(outputs/'46_market_stratified_research_queue.csv')
    assert set(market_only.lane) == {'MARKET_COVERAGE_REVIEW'}
    assert set(market_only.market_group) == {'Korea', 'Japan', 'China', 'Hong Kong', 'Taiwan'}
    queue=pd.read_csv(outputs/'39_market_research_queue.csv')
    assert queue[queue.lane.eq('GLOBAL_UNQUOTED_SCORE')].ticker.tolist()==['2330.TW','7203.T']
    assert 'Hong Kong' in set(queue[queue.priority_interpretation.eq('NO_ELIGIBLE_ISSUER_MANUAL_CHECK')].market_group)
    assert '9911.HK' not in set(queue.ticker.dropna())


def test_v051_uses_unrelated_headline_quarantine_and_recheck(tmp_path):
    outputs,data=_fixture_outputs(tmp_path)
    audit=enhance_v051(outputs,data)
    assert audit['news_quarantined_n']==1
    assert audit['high_score_recheck_queue_n']==1
    assert audit['official_financial_figures_machine_verified_n']==0
    assert audit['reviewed_investment_memo_n']==0
    ledger=pd.read_csv(outputs/'18_evidence_ledger.csv')
    assert 'QUARANTINE' in ledger.verification_status.iat[0]
    assert (outputs/'43_quality_diagnostics_v051.md').exists()


def test_snapshot_replay_explicitly_not_live_coverage(tmp_path):
    outputs,_=_fixture_outputs(tmp_path)
    _,stats=coverage_audit(outputs,'off')
    assert stats['market_coverage_status']=='SNAPSHOT_COVERAGE_NOT_AUDITED'


def test_single_v051_wrapper_preserves_v05_and_adds_manifest(tmp_path,monkeypatch):
    from src import v051 as wrapper
    called=[]
    def previous(*args):
        called.append('v05')
        return {'pipeline_revision':'0.5','trade_orders':'NONE'}
    def audit(out,data,mode):
        assert called==['v05']
        called.append('v051_audit')
        return {'market_coverage_status':'PARTIAL_COVERAGE','dominant_market':'Taiwan',
                'dominant_market_share_pct':65.1,'news_quarantined_n':4,
                'reviewed_investment_memo_n':0}
    monkeypatch.setattr(wrapper,'run_v05',previous)
    monkeypatch.setattr(wrapper,'enhance_v051',audit)
    inputs=tmp_path/'data';inputs.mkdir()
    outputs=tmp_path/'out';outputs.mkdir()
    m=wrapper.run(inputs/'universe.csv',outputs)
    assert called==['v05','v051_audit']
    assert m['pipeline_revision']=='0.5.1'
    assert json.loads((outputs/'44_v051_run_manifest.json').read_text())['trade_orders']=='NONE'


@pytest.mark.parametrize('mode', ['news', 'off'])
def test_empty_collected_evidence_preserves_output_schema(tmp_path, monkeypatch, mode):
    from src.evidence import EVIDENCE_COLUMNS, collect_evidence
    from src.quality_v051 import audit_news

    outputs,data=_fixture_outputs(tmp_path)
    calls=[]
    monkeypatch.setattr('src.evidence.news_rss', lambda *args: calls.append(args) or [])
    evidence=collect_evidence(pd.read_csv(outputs/'01_all_research_candidates.csv'), mode=mode)
    assert len(calls)==(3 if mode=='news' else 0)
    assert {key:list(value.columns) for key,value in evidence.items()}==EVIDENCE_COLUMNS
    for key,filename in [('news','19_news_headlines.csv'),('ledger','18_evidence_ledger.csv')]:
        evidence[key].to_csv(outputs/filename,index=False)
    assert audit_news(outputs,data)['news_headlines_n']==0
    audit=pd.read_csv(outputs/'40_news_relevance_audit.csv')
    assert audit.empty and 'issuer_match_status' in audit.columns


def test_legacy_blank_news_and_malformed_news_are_distinct(tmp_path):
    from src.quality_v051 import audit_news

    outputs,data=_fixture_outputs(tmp_path)
    path=outputs/'19_news_headlines.csv'
    path.write_text('\ufeff\n', encoding='utf-8')
    assert audit_news(outputs,data)['news_headlines_n']==0
    for malformed in ('wrong,header\n', 'ticker,title,source_url,published_date,source_name,identifier\n001,short\n'):
        path.write_text(malformed)
        with pytest.raises(ValueError,match='19_news_headlines.csv'):
            audit_news(outputs,data)
