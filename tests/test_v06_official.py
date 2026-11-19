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


def xbrl_archive(*, scope='true', context='CurrentYearDuration', namespace='jppfs'):
    xml = f'''<x:xbrl xmlns:x="http://www.xbrl.org/2003/instance"
    xmlns:iso="http://www.xbrl.org/2003/iso4217"
    xmlns:jppfs="http://disclosure.edinet-fsa.go.jp/taxonomy/jppfs/2024-11-01/jppfs_cor"
    xmlns:jpdei="http://disclosure.edinet-fsa.go.jp/taxonomy/jpdei/2024-11-01/jpdei_cor"
    xmlns:custom="https://unrecognized.example/concepts">
    <x:context id="{context}"><x:entity><x:identifier scheme="http://disclosure.edinet-fsa.go.jp">E02144</x:identifier></x:entity>
      <x:period><x:startDate>2024-04-01</x:startDate><x:endDate>2025-03-31</x:endDate></x:period>
    </x:context>
    <x:unit id="JPY"><x:measure>iso:JPY</x:measure></x:unit>
    <jpdei:WhetherConsolidatedFinancialStatementsArePreparedDEI contextRef="{context}">{scope}</jpdei:WhetherConsolidatedFinancialStatementsArePreparedDEI>
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
