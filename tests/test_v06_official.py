"""Publisher protocol and parsing regressions using synthetic source bytes."""
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
import subprocess
from pathlib import Path
from zipfile import ZipFile

import pandas as pd
import pytest
import requests

from src.edinet_filings import EDINETError, fetch_edinet, parse_xbrl
from src.filing_evidence import reconcile
from src.filing_statements import parse_statement
from src.official_filings import FilingRequest, SourceUnavailable, acquire_sources, download
from src.v06 import gemini_report


CUTOFF = date(2026, 11, 19)
EDINET = {
    'venue': 'JPX', 'ticker': '7203.T', 'issuer_id': 'E02144',
    'issuer_name': 'Example Automobile Corporation', 'document_id': 'S100TXYZ',
    'period_start': '2024-04-01', 'period_end': '2025-03-31', 'publication_date': '2025-06-18',
}
PUBLICATIONS = [
    ('SSE_MAIN', '600000.SS', 'static.sse.com.cn'),
    ('SSE_STAR', '688001.SS', 'static.sse.com.cn'),
    ('SZSE_MAIN', '000001.SZ', 'disc.static.szse.cn'),
    ('SZSE_CHINEXT', '300001.SZ', 'static.cninfo.com.cn'),
    ('BSE', '920001.BJ', 'www.bse.cn'),
    ('HKEX', '00001.HK', 'www1.hkexnews.hk'),
    ('TWSE', '2330.TW', 'doc.twse.com.tw'),
    ('TPEX', '6488.TWO', 'mops.twse.com.tw'),
]


def xbrl_archive(*, scope='true', context='CurrentYearDuration', namespace='jppfs',
                 identifier='E02144-000', scheme='http://disclosure.edinet-fsa.go.jp',
                 scope_namespace='jpdei', scope_context='FilingDateInstant', filing_date='2025-06-18',
                 fiscal_end='2025-03-31', scope_identifier=None, scenario=''):
    xml = f'''<x:xbrl xmlns:x="http://www.xbrl.org/2003/instance"
    xmlns:iso="http://www.xbrl.org/2003/iso4217"
    xmlns:jppfs="http://disclosure.edinet-fsa.go.jp/taxonomy/jppfs/2024-11-01/jppfs_cor"
    xmlns:jpdei="http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/2013-08-31/jpdei_cor"
    xmlns:custom="https://unrecognized.example/concepts">
    <x:context id="FilingDateInstant"><x:entity><x:identifier scheme="{scheme}">{scope_identifier or identifier}</x:identifier></x:entity>
      <x:period><x:instant>{filing_date}</x:instant></x:period>
    </x:context>
    <x:context id="{context}"><x:entity><x:identifier scheme="{scheme}">{identifier}</x:identifier></x:entity>
      <x:period><x:startDate>2024-04-01</x:startDate><x:endDate>{fiscal_end}</x:endDate></x:period>{scenario}
    </x:context>
    <x:unit id="JPY"><x:measure>iso:JPY</x:measure></x:unit>
    <{scope_namespace}:WhetherConsolidatedFinancialStatementsArePreparedDEI contextRef="{scope_context}">{scope}</{scope_namespace}:WhetherConsolidatedFinancialStatementsArePreparedDEI>
    <{namespace}:NetSales contextRef="{context}" unitRef="JPY" decimals="-6">1000000</{namespace}:NetSales>
    </x:xbrl>'''
    result = BytesIO()
    with ZipFile(result, 'w') as archive:
        archive.writestr('XBRL/PublicDoc/jpcrp-example.xbrl', xml)
    return result.getvalue()


def test_edinet_index_filters_and_retrieves_original():
    filing = FilingRequest.from_row(EDINET, CUTOFF)
    item = dict(docID='S100TXYZ', edinetCode='E02144', secCode='72030', docTypeCode='120',
                xbrlFlag='1', periodStart='2024-04-01', periodEnd='2025-03-31',
                submitDateTime='2025-06-18 13:00', withdrawalStatus='0', disclosureStatus='0')
    payload = json.dumps({'metadata': {'status': '200'},
                          'results': [dict(item, docID='S100TABC', secCode='12340'), item]}).encode()

    def fetch(url, *, params, limit=None):
        assert params.pop('Subscription-Key') == 'credential-placeholder'
        if url.endswith('.json'):
            assert params == {'date': '2025-06-18', 'type': '2'}
            return payload, 'application/json'
        assert params == {'type': '1'} and url.endswith('/S100TXYZ')
        return xbrl_archive(), 'application/zip'

    raw, url, parse = fetch_edinet(fetch, filing, 'credential-placeholder')
    result, = parse(raw, filing)
    assert result['currency'] == 'JPY' and result['value'] == '1000000'
    assert result['source_locator'].startswith('XBRL/PublicDoc/')
    assert url.endswith('/S100TXYZ?type=1')
    assert 'credential-placeholder' not in url


@pytest.mark.parametrize('context,namespace', [('CurrentYearDuration_NonConsolidatedMember', 'jppfs'),
                                               ('CurrentYearDuration', 'custom')])
def test_edinet_blocks_parent_and_custom_facts(context, namespace):
    filing = FilingRequest.from_row(EDINET, CUTOFF)
    assert parse_xbrl(xbrl_archive(context=context, namespace=namespace), filing) == []
    with pytest.raises(EDINETError, match='CONSOLIDATED_SCOPE_UNCONFIRMED'):
        parse_xbrl(xbrl_archive(scope='false'), filing)


@pytest.mark.parametrize('overrides', [
    {'scope_identifier': 'E02144-001'}, {'scope_identifier': 'E09999-000'},
    {'scheme': 'https://unrecognized.example'}, {'scope_namespace': 'custom'},
    {'scope_context': 'CurrentYearDuration'}, {'filing_date': '2025-06-17'},
])
def test_edinet_scope_requires_official_issuer_scheme_taxonomy_and_filing_context(overrides):
    # Public EDINET annual specimens such as S100YBXA use E-code-000,
    # jpdei_cor dated 2013-08-31, and the FilingDateInstant context for DEI.
    filing = FilingRequest.from_row(EDINET, CUTOFF)
    with pytest.raises(EDINETError, match='EDINET_CONSOLIDATED_SCOPE_UNCONFIRMED'):
        parse_xbrl(xbrl_archive(**overrides), filing)


@pytest.mark.parametrize('overrides', [
    {'identifier': 'E02144-001', 'scope_identifier': 'E02144-000'},
    {'fiscal_end': '2025-04-01'}, {'scenario': '<x:scenario/>'},
])
def test_edinet_independently_checks_financial_context(overrides):
    filing = FilingRequest.from_row(EDINET, CUTOFF)
    assert parse_xbrl(xbrl_archive(**overrides), filing) == []


def test_edinet_records_download_even_when_scope_parsing_fails(monkeypatch, tmp_path):
    request = tmp_path / 'edinet.csv'
    pd.DataFrame([EDINET]).to_csv(request, index=False)
    raw = xbrl_archive(scope='false')
    monkeypatch.setattr('src.official_filings.fetch_edinet',
                        lambda *args: (raw, 'https://api.edinet-fsa.go.jp/api/v2/documents/S100TXYZ?type=1', parse_xbrl))
    rows, attempts = acquire_sources(request, None, tmp_path / 'originals', CUTOFF, 1, 0,
                                     {'EDINET_API_KEY': 'fixture'})
    assert not rows
    attempt, = attempts
    assert attempt['source_response_received'] and attempt['document_retrieved']
    assert attempt['source_sha256'] == sha256(raw).hexdigest()
    assert (attempt['status'], attempt['reason'], attempt['observations']) == (
        'PARSE_FAILED', 'EDINET_CONSOLIDATED_SCOPE_UNCONFIRMED', 0)


def schedule(venue, ticker, host, **extra):
    return dict(venue=venue, ticker=ticker, issuer_id=ticker.split('.')[0], issuer_name='Example Issuer Holdings',
                period_start='2024-01-01', period_end='2024-12-31', publication_date='2025-06-19',
                source_url=f'https://{host}/report.html', **extra)


def statement(heading='Consolidated Income Statement', date_phrase='Year ended 31 December 2024'):
    return f'''<h1>Example Issuer Holdings</h1><h2>{heading}</h2>
    <p>{date_phrase}</p><p>HKD thousands</p><table>
    <tr><th></th><th>2024</th><th>2023</th></tr>
    <tr><td>Revenue</td><td>1,500</td><td>1,300</td></tr>
    <tr><td>Operating profit</td><td>(75)</td><td>120</td></tr></table>'''.encode()


@pytest.mark.parametrize('venue,ticker,host', PUBLICATIONS, ids=[item[0] for item in PUBLICATIONS])
def test_public_venues_fetch_parse_and_reconcile(monkeypatch, tmp_path, venue, ticker, host):
    raw = statement()
    digest = sha256(raw).hexdigest()
    request = schedule(venue, ticker, host, expected_sha256=digest)
    manifest = tmp_path / 'requests.csv'
    pd.DataFrame([request]).to_csv(manifest, index=False)

    def get(session, url):
        assert url == request['source_url']
        return raw, 'text/html'

    monkeypatch.setattr('src.official_filings.download', get)
    rows, attempts = acquire_sources(manifest, None, tmp_path / 'raw', CUTOFF, 1, 0, {})
    assert attempts == [dict(venue=venue, ticker=ticker, attempted=True, source_response_received=True, document_retrieved=True,
                             status='PARSED', observations=2, source_sha256=digest)]
    assert {r['value'] for r in rows} == {'1500', '-75'}
    assert (tmp_path / 'raw' / digest).read_bytes() == raw
    result = reconcile(rows, rows, tmp_path / 'raw', CUTOFF)
    assert all(row['status'] == 'MACHINE_RECONCILED' for row in result)


def test_mops_localized_statement_and_roc_year():
    raw = '''<h1>台灣測試股份有限公司</h1><h2>合併綜合損益表</h2>
    <p>113年度 民國113年12月31日</p><p>單位：新台幣仟元</p>
    <table><tr><th></th><th>113年度</th><th>112年度</th></tr>
    <tr><td>營業收入合計</td><td>1,500</td><td>1,300</td></tr></table>'''.encode()
    request = schedule('TWSE', '2330.TW', 'mops.twse.com.tw')
    request['issuer_name'] = '台灣測試股份有限公司'
    item, = parse_statement(raw, 'text/html', FilingRequest.from_row(request, CUTOFF))
    assert item['metric'] == 'revenue'
    assert item['currency'] == 'TWD' and item['scale'] == '1000'


def test_pdf_route_extracts_a_real_pdf_container():
    fixture = Path(__file__).parent / 'fixtures' / 'v06-public-statement.pdf'
    filing = FilingRequest.from_row(schedule('HKEX', '00001.HK', 'www1.hkexnews.hk'), CUTOFF)
    rows = parse_statement(fixture.read_bytes(), 'application/pdf', filing)
    assert [(row['metric'], row['value']) for row in rows] == [('revenue', '1500')]
    assert rows[0]['source_locator'].startswith('PDF page 1')


@pytest.mark.parametrize('heading,period', [('Income Statement', 'Year ended 31 December 2024'),
                                           ('Consolidated Income Statement', 'Half-year ended 31 December 2024')])
def test_unqualified_statement_context_is_not_parsed(heading, period):
    filing = FilingRequest.from_row(schedule('HKEX', '00001.HK', 'www1.hkexnews.hk'), CUTOFF)
    assert parse_statement(statement(heading, period), 'text/html', filing) == []


def test_proxy_refusal_and_missing_key_are_not_tests(monkeypatch, tmp_path):
    manifest = tmp_path / 'requests.csv'
    pd.DataFrame([EDINET, schedule('HKEX', '00001.HK', 'www1.hkexnews.hk')]).fillna('').to_csv(manifest, index=False)

    def refuse(*args, **kwargs):
        raise requests.exceptions.ProxyError('Tunnel connection failed: 403 Forbidden')

    monkeypatch.setattr('requests.Session.get', refuse)
    rows, attempts = acquire_sources(manifest, None, tmp_path / 'raw', CUTOFF, 1, 0, {})
    assert rows == []
    assert [(row['status'], row['reason'], row['attempted']) for row in attempts] == [
        ('NOT_TESTED', 'EDINET_API_KEY_MISSING', False), ('NOT_TESTED', 'PROXY_CONNECT_403', True)]


def test_official_host_is_not_a_redirect_endpoint(monkeypatch):
    request = schedule('HKEX', '00001.HK', 'www1.hkexnews.hk.example.org')
    with pytest.raises(SourceUnavailable, match='OFFICIAL_DELIVERY_HOST'):
        FilingRequest.from_row(request, CUTOFF)

    def get(session, url, **kwargs):
        assert kwargs['allow_redirects'] is False
        response = requests.Response()
        response.status_code = 302
        response.raw = BytesIO()
        return response

    monkeypatch.setattr('requests.Session.get', get)
    with requests.Session() as session, pytest.raises(SourceUnavailable, match='ORIGIN_HTTP_302'):
        download(session, 'https://www1.hkexnews.hk/report.pdf')


def test_actions_shell_passes_dispatch_settings(tmp_path):
    path = Path('.github/workflows/run-research-v05.yml')
    script = path.read_text()
    step = script.split('      - name: Integrated three-stage research / no orders')[1]
    step = step.split('      - name: Listing discovery only')[0]
    assert 'secrets.GEMINI_API_KEY' in step and 'secrets.EDINET_API_KEY' in step
    run = step.split('        run: |\n')[1]
    commands = '\n'.join(line.removeprefix('          ') for line in run.splitlines())
    for file in ('approvals.csv', 'official.csv', 'vendor.csv'):
        (tmp_path / file).touch()
    # Exercise the exact workflow shell; replace the engine with an argv recorder.
    env = dict(GITHUB_WORKSPACE=str(tmp_path), RUNNER_TEMP=str(tmp_path), GARP_INPUT_LEGACY='false',
               GARP_INPUT_GEMINI='true', GARP_INPUT_GEMINI_APPROVED_ONLY='true',
               GARP_INPUT_GEMINI_APPROVALS='approvals.csv', GARP_INPUT_FILING_REQUESTS='official.csv',
               GARP_INPUT_VENDOR_EXPORT='vendor.csv', GARP_INPUT_FILING_BUDGET='3',
               GARP_INPUT_GEMINI_MAX_DOCUMENTS='1', GARP_INPUT_GEMINI_MAX_REQUESTS='2')
    result = subprocess.run(['bash', '-e', '-c', 'python() { printf "%s\\n" "$@"; }\n' + commands],
                            cwd=tmp_path, env=env, check=True, capture_output=True, text=True)
    args = result.stdout.splitlines()
    assert args[:2] == ['-m', 'src.v06']
    assert args[args.index('--approved-sources') + 1] == str(tmp_path / 'approvals.csv')
    assert args[args.index('--official-filing-requests') + 1] == str(tmp_path / 'official.csv')
    assert args[args.index('--vendor-export') + 1] == str(tmp_path / 'vendor.csv')
    assert args[args.index('--max-requests') + 1] == '2'
    assert '--enable-gemini' in args and '--gemini-approved-only' in args


def test_gemini_approved_only_distinguishes_no_key_from_api_reply(monkeypatch, tmp_path):
    from types import SimpleNamespace

    approval = tmp_path / 'approved.csv'
    pd.DataFrame([{'ticker': '00001.HK', 'source_url': 'https://www1.hkexnews.hk/annual.pdf',
                   'date_source_url': 'https://www1.hkexnews.hk/search/titlesearch.xhtml',
                   'document_date': '2025-06-19', 'issuer_name': 'Example Issuer Holdings',
                   'document_title': '2024 Annual Report'}]).to_csv(approval, index=False)
    args = SimpleNamespace(model='example-model', enable_gemini=True, gemini_preflight=False,
                           gemini_approved_only=True, approved_sources=approval, output=tmp_path,
                           asof_date=CUTOFF, max_documents=1, max_requests=2, gemini_input_bytes=24000,
                           gemini_output_tokens=1024, gemini_replay_dir=None)
    monkeypatch.delenv('GEMINI_API_KEY', raising=False)
    no_key = gemini_report(args)
    assert (no_key['status'], no_key['reason'], no_key['api_responses_received']) == (
        'NOT_TESTED', 'GEMINI_API_KEY_MISSING', 0)

    monkeypatch.setenv('GEMINI_API_KEY', 'testing-placeholder')
    agent = SimpleNamespace(responses_received=0, input_tokens=0, output_tokens=0)
    monkeypatch.setattr('src.v06.Gemini', lambda *args, **kwargs: agent)

    def remote(selected, filings, model, **kwargs):
        assert selected == ['00001.HK'] and '00001.HK' in filings
        assert kwargs['mode'] == 'live' and model is agent
        model.responses_received = 1
        return {'gemini_requests': 2, 'observations': []}

    monkeypatch.setattr('src.v06.research', remote)
    live = gemini_report(args)
    assert (live['status'], live['gemini_requests'], live['api_responses_received']) == ('LIVE_RESPONSE_RECEIVED', 2, 1)


def test_native_filing_failure_does_not_count_as_verification(tmp_path, monkeypatch):
    from src.v06 import main

    manifest = tmp_path / 'official.csv'
    pd.DataFrame([schedule('HKEX', '00001.HK', 'www1.hkexnews.hk')]).to_csv(manifest, index=False)
    monkeypatch.setattr('src.official_filings.download', lambda *args: (b'not a supported document', 'text/plain'))
    output = tmp_path / 'outputs'
    monkeypatch.setattr('sys.argv', ['v06', '--discover-mode', 'off', '--max-symbols', '1',
                                    '--financial-budget', '0', '--official-filing-requests', str(manifest),
                                    '--source-dir', str(tmp_path / 'raw'), '--filing-budget', '1',
                                    '--output', str(output)])
    main()
    result = json.loads((output / '67_v06_run_manifest.json').read_text())
    assert result['outcomes']['live_financial_responses']['rate'] is None
    assert result['outcomes']['official_source_responses']['rate'] == 1
    assert result['outcomes']['official_document_retrieval']['rate'] == 0
    assert result['outcomes']['official_statement_parsing']['rate'] is None
    assert result['outcomes']['official_documents_with_numeric_reconciliation']['rate'] is None
    assert result['outcomes']['research_report_files']['rate'] == 1


def test_blank_current_html_cell_cannot_turn_note_into_amount():
    raw = b'''<h1>Example Issuer Holdings</h1><h2>Consolidated Income Statement</h2>
    <p>Year ended 31 December 2024</p><p>HKD thousands</p>
    <table><tr><th></th><th>Note</th><th>2024</th><th>2023</th></tr>
    <tr><td>Revenue</td><td>12</td><td></td><td>1300</td></tr></table>'''
    filing = FilingRequest.from_row(schedule('HKEX', '00001.HK', 'www1.hkexnews.hk'), CUTOFF)
    assert parse_statement(raw, 'text/html', filing) == []


def test_restored_aggregate_prepares_and_consumes_edinet_inputs(tmp_path, monkeypatch):
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from google import genai
    from google.genai.errors import APIError

    from src import research_cycle as cycle
    from src.scoring_v03 import SUBMETRICS

    ticker = EDINET['ticker']
    discovery = tmp_path / 'discovery'
    discovery.mkdir()
    universe = Path('data/universe.csv')
    ranked_origin = pd.read_csv(universe).loc[lambda rows: rows.ticker.eq(ticker)]
    ranked_origin.assign(is_new_discovery=False, discovery_source='CURATED_TICKER',
                         security_type_status='CURATED_TICKER_TYPE_NEEDS_CONFIRMATION').to_csv(
        discovery / '11_discovery_universe.csv', index=False)
    pd.DataFrame([dict(source='fixture', status='OK', market='Japan', source_kind='TEST_FIXTURE')]).to_csv(
        discovery / '12_discovery_sources_log.csv', index=False)
    frozen = tmp_path / 'plan'
    cycle.freeze(discovery, frozen, 'fixture', 5, cutoff=CUTOFF)
    plan = cycle.load_plan(frozen)
    shard = next(iter(plan['shards']))
    checkpoint = tmp_path / 'checkpoint'
    cycle.run_shard(plan, shard, checkpoint, 1, 0, clock=lambda: datetime(2026, 11, 1, tzinfo=timezone.utc),
                    fetch=lambda _: {**dict.fromkeys((f for group in SUBMETRICS.values() for f in group), .15),
                                     'vendor_quote_type': 'EQUITY', 'forward_pe': 15, 'price_to_sales': 2,
                                     'currency': 'JPY', 'financial_currency': 'JPY'})
    restored = tmp_path / 'restored'
    cycle.restore(plan, checkpoint, restored)

    item = dict(docID=EDINET['document_id'], edinetCode=EDINET['issuer_id'], secCode='72030', docTypeCode='120',
                filerName='Example Issuer Holdings', xbrlFlag='1', pdfFlag='1', periodStart=EDINET['period_start'],
                periodEnd=EDINET['period_end'], submitDateTime='2025-06-18 13:00',
                withdrawalStatus='0', disclosureStatus='0')
    pdf = Path('tests/fixtures/v06-public-statement.pdf').read_bytes()
    def publisher(session, url, *, params, **kwargs):
        assert params['Subscription-Key'] == 'fixture-edinet'
        if url.endswith('.json'):
            return json.dumps({'metadata': {'status': '200'}, 'results': [item]}).encode(), 'application/json'
        if params['type'] == '1':
            return xbrl_archive(), 'application/zip'
        assert params['type'] == '2'
        return pdf, 'application/pdf'

    monkeypatch.setattr('src.official_filings.download', publisher)
    monkeypatch.setattr('src.filing_preparation.download', publisher)
    cover = 'Example Issuer Holdings\n有価証券報告書\n【事業年度】2024年4月1日 2025年3月31日'
    monkeypatch.setattr('src.filing_preparation.PdfReader',
                        lambda _: SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda: cover)]))
    monkeypatch.setattr('src.gemini_filing.retrieve', lambda *_: pytest.fail('Private original should be reused'))
    calls = []

    def response(**kwargs):
        calls.append(kwargs)
        assert kwargs['config'].response_mime_type == 'application/json'
        assert not kwargs['config'].tools
        if len(calls) == 1:
            raise APIError(504, {'error': {'message': 'fixture gateway timeout'}})
        observation = {'metric_label': 'Revenue', 'value_text': '1,500', 'currency': 'HKD',
                       'unit': 'thousands', 'period_start': '', 'period_end': '2024-12-31',
                       'quote': 'Revenue 1,500 1,300'}
        return SimpleNamespace(text=json.dumps({'observations': [observation], 'excerpts': []}))
    models = SimpleNamespace(generate_content=response, get=lambda **kwargs: SimpleNamespace(
        supported_actions=['generateContent']))
    def client(**kwargs):
        assert kwargs['http_options'].timeout == 120_000
        assert kwargs['http_options'].retry_options.attempts == 1
        return SimpleNamespace(models=models)

    monkeypatch.setattr(genai, 'Client', client)
    monkeypatch.setattr('src.gemini_filing.time.sleep', lambda _: None)
    monkeypatch.setenv('GARP_GEMINI_TIMEOUT_SECONDS', '120')
    monkeypatch.setenv('EDINET_API_KEY', 'fixture-edinet')
    monkeypatch.setenv('GEMINI_API_KEY', 'fixture-model')
    monkeypatch.setenv('GARP_EDINET_INDEX_DATES', '2025-06-18')
    out = tmp_path / 'aggregate'
    comparable = tmp_path / 'vendor.csv'
    pd.DataFrame([dict(ticker=ticker, issuer_id=EDINET['issuer_id'], metric='revenue', definition='NetSales',
                       period_start=EDINET['period_start'], period_end=EDINET['period_end'], period_kind='FY',
                       scope='CONSOLIDATED', statement='IS', currency='JPY', unit='CURRENCY', value='1000000',
                       scale='1', publication_date=EDINET['publication_date'])]).to_csv(comparable, index=False)
    monkeypatch.setattr('sys.argv', ['research_cycle', 'aggregate', '--plan', str(frozen), '--state', str(restored),
        '--output', str(out), '--universe', str(universe), '--vendor-export', str(comparable),
        '--research-dossier', '--prepare-filing-inputs', '--filing-budget', '1', '--report-limit', '1',
        '--source-dir', str(tmp_path / 'private'), '--enable-gemini', '--max-requests', '2',
        '--gemini-max-cost-usd', '.05', '--gemini-input-price', '1', '--gemini-output-price', '2'])
    cycle.main()
    evidence = out / 'research'
    prepared = evidence / '72_filing_preparation'
    lead, = json.loads((prepared / 'review.json').read_text())['outcomes']
    assert lead['status'] == 'AUTO_VERIFIED_OFFICIAL_ORIGINAL'
    approval = pd.read_csv(prepared / 'gemini_approved_sources.csv').iloc[0]
    assert approval.ticker == ticker and approval.source_url.endswith('?type=2')
    assert 'fixture-edinet' not in (prepared / 'gemini_approved_sources.csv').read_text()
    assert approval.expected_sha256 == sha256(pdf).hexdigest()
    assert pd.read_csv(prepared / 'official_filing_requests.csv').source_url.iat[0].endswith('?type=1')
    manifest = json.loads((evidence / '67_v06_run_manifest.json').read_text())
    assert manifest['vendor_requests'] == 0 and manifest['filing_attempts'][0]['document_retrieved']
    assert manifest['verification_states'] == {'MACHINE_RECONCILED': 1}
    assert manifest['gemini']['model_preflight'] == 'MODEL_SUPPORTS_GENERATE_CONTENT'
    assert manifest['gemini']['api_responses_received'] == 1 and len(calls) == 2
    assert manifest['gemini']['transient_failures'] == {'HTTP_504': 1}
    assert manifest['gemini']['generation_timeout_seconds'] == 120
    model_report = json.loads((evidence / '63_gemini_evidence.json').read_text())
    company, = model_report['companies']
    observation, = model_report['observations']
    assert company['passage_selection_method'] == 'DETERMINISTIC_FINANCIAL_PASSAGE'
    assert company['selected_location'].startswith('PDF page 1')
    assert observation['document_sha256'] == sha256(pdf).hexdigest()
    assert observation['verification_status'] == 'PROVISIONAL_CONTEXT_UNRESOLVED'
    assert observation['filing_verified'] is False
    assert manifest['research_dossiers']['dossiers'][0]['ticker'] == ticker


def test_edinet_pdf_without_verified_annual_period_requires_review():
    from src.filing_preparation import verify_pdf

    with pytest.raises(SourceUnavailable, match='GEMINI_PDF_ISSUER_NEEDS_REVIEW'):
        verify_pdf(Path('tests/fixtures/v06-public-statement.pdf').read_bytes(), EDINET)
