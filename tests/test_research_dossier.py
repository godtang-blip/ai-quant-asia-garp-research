from hashlib import sha256
import json
from types import SimpleNamespace

from google import genai
import pandas as pd
import pytest

from src.research_quality import DCF_FIELDS
from src.v06 import main


def test_screened_candidate_dossier_reuses_approved_original(monkeypatch, tmp_path):
    ticker = '0981.HK'
    issuer = 'Semiconductor Manufacturing International Corporation'
    url = 'https://www1.hkexnews.hk/annual.htm'
    quote = 'Competitive position relies on a limited set of suppliers.'
    original = f'''<h1>{issuer}</h1><h2>Business overview</h2><p>{quote}</p>
    <h2>Consolidated Income Statement</h2><p>Year ended 31 December 2024</p><p>HKD thousands</p>
    <table><tr><th></th><th>2024</th><th>2023</th></tr>
    <tr><td>Revenue</td><td>1500</td><td>1300</td></tr></table>'''.encode()
    digest = sha256(original).hexdigest()
    vendor = tmp_path / 'vendor.csv'
    pd.DataFrame([dict(ticker=ticker, company='SMIC', market='Hong Kong', vendor_quote_type='EQUITY',
                       operating_margin=.15, roe=.15, revenue_growth=.2, earnings_growth=.2,
                       forward_pe=20, price_to_sales=2, debt_to_equity_ratio=.3, price_change_52w=.2,
                       fcf_yield=.03, currency='HKD', financial_currency='HKD')]).to_csv(vendor, index=False)
    filing_input = tmp_path / 'official.csv'
    filing = dict(venue='HKEX', ticker=ticker, issuer_id='HK:0981', issuer_name=issuer,
                  period_start='2024-01-01', period_end='2024-12-31', publication_date='2025-06-18',
                  source_url=url, expected_sha256=digest)
    pd.DataFrame([dict(filing, ticker='9999.HK'), filing]).to_csv(filing_input, index=False)
    comparable = tmp_path / 'comparable.csv'
    pd.DataFrame([dict(ticker=ticker, issuer_id=filing['issuer_id'], metric='revenue', definition='revenue',
                       period_start='2024-01-01', period_end='2024-12-31', period_kind='FY', scope='CONSOLIDATED',
                       statement='IS', currency='HKD', unit='CURRENCY', value='1490000', scale='1',
                       publication_date='2025-06-18')]).to_csv(comparable, index=False)
    approval = tmp_path / 'approved.csv'
    pd.DataFrame([dict(ticker=ticker, source_url=url, issuer_name=issuer, document_date='2025-06-18',
                       date_source_url='https://www1.hkexnews.hk/search', document_title='Annual report',
                       expected_sha256=digest)]).to_csv(approval, index=False)

    requests = []

    def official_download(session, source, **kwargs):
        requests.append(source)
        return original, 'text/html'

    def unexpected(*args, **kwargs):
        pytest.fail('Gemini should reuse the official original')

    calls = []

    def generate(**kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return SimpleNamespace(function_calls=[SimpleNamespace(name='read_passage', args={'id': 0})])
        assert quote in kwargs['contents']
        return SimpleNamespace(text=json.dumps({'observations': [], 'excerpts': [
            {'category': 'risk', 'quote': quote},
            {'category': 'growth_driver', 'quote': 'This statement was invented and never appears in the source.'},
        ]}))

    monkeypatch.setattr('src.official_filings.download', official_download)
    monkeypatch.setattr('src.gemini_filing.retrieve', unexpected)
    monkeypatch.setattr(genai, 'Client', lambda **kwargs: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-key')
    output = tmp_path / 'output'
    main(['--research-dossier', '--discover-mode', 'off', '--markets', 'Hong Kong', '--max-symbols', '1',
          '--asof-date', '2026-11-01', '--report-limit', '1', '--snapshot-csv', str(vendor),
          '--official-filing-requests', str(filing_input), '--filing-budget', '1', '--source-dir', str(tmp_path / 'private'),
          '--vendor-export', str(comparable), '--approved-sources', str(approval), '--enable-gemini',
          '--gemini-max-cost-usd', '.05', '--gemini-input-price', '1', '--gemini-output-price', '2',
          '--max-documents', '1', '--max-requests', '2', '--output', str(output)])
    assert requests == [url] and len(calls) == 2
    root = output / '71_research_dossiers'
    index = json.loads((root / 'index.json').read_text())
    item, = index['dossiers']
    assert item['ticker'] == pd.read_csv(output / '02_research_shortlist.csv').ticker.iat[0] == ticker
    dossier = json.loads((root / item['manifest']).read_text())
    observation, = dossier['primary_observations']
    assert observation['evidence_state'] == 'MACHINE_RECONCILED'
    excerpt, = dossier['gemini']['excerpts']
    assert excerpt['supporting_text'] == quote and excerpt['document_sha256'] == observation['source_sha256'] == digest
    assert excerpt['classification_status'] == 'PROVISIONAL_MODEL_LABEL'
    assert dossier['gemini']['execution']['rejected_excerpt_proposals'] == 1
    assert dossier['gemini']['execution']['document_origin'] == 'PINNED_OFFICIAL_ORIGINAL'
    assert not dossier['valuation']['scenarios']
    assert pd.read_csv(root / 'valuation_inputs.csv').columns.tolist() == DCF_FIELDS
    assert 'The investment thesis and approval belong to the analyst.' in (root / item['markdown']).read_text()


def test_valuation_sensitivity_uses_reviewed_assumptions_without_copying_thesis(tmp_path):
    from src.research_dossier import valuation_workspace

    inputs = dict(ticker='0981.HK', asof_date='2026-01-01', currency='HKD', fcff_year0=100,
                  shares_outstanding=10, net_debt=0, current_price=20, growth_bear=.01, growth_base=.03,
                  growth_bull=.05, discount_rate=.10, terminal_growth=.01, forecast_years=5,
                  thesis='Private analyst prose', valuation_status='MODELED_MANUAL_INPUT_REVIEWED')
    pd.DataFrame([inputs]).to_csv(tmp_path / '31_valuation_scenario_audit.csv', index=False)
    editable, valuation = valuation_workspace(tmp_path, '0981.HK', '2026-11-01')
    assert editable['thesis'] == ''
    assert [row['discount_rate'] for row in valuation['sensitivity']] == [.09, .10, .11]
    assert valuation['sensitivity'][0]['intrinsic_base'] > valuation['scenarios']['intrinsic_base']
    assert valuation['sensitivity'][-1]['intrinsic_base'] < valuation['scenarios']['intrinsic_base']


def test_dart_annual_search_uses_official_mapping_cutoff_and_budget(monkeypatch):
    from datetime import date
    from src.official_filings import locate_dart_annual_filings

    issued = {'005930': {'corp_code': '00126380', 'corp_name': 'Samsung Electronics'}}
    requested = []

    def recent(code, mapping, key, session, **kwargs):
        requested.append(code)
        assert mapping == issued and kwargs['annual_only'] and kwargs['cutoff'] == date(2026, 11, 1)
        return [{'identifier': '20260318000001', 'title': 'Annual report'}]

    monkeypatch.setattr('src.official_filings.dart_stock_code_map', lambda key, session: issued)
    monkeypatch.setattr('src.official_filings.dart_recent_filings', recent)
    result = locate_dart_annual_filings(['005930.KS', '000660.KS'], 'fixture', date(2026, 11, 1), 1)
    assert requested == ['005930']
    assert result[0]['status'] == 'METADATA_ONLY' and result[0]['official_issuer'] == issued['005930']
    assert result[1]['reason'] == 'FILING_BUDGET_EXHAUSTED'
