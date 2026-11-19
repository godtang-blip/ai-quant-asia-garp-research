from hashlib import sha256
from types import SimpleNamespace
import json

import pandas as pd
import pytest

from src.filing_evidence import reconcile
from src.gemini_filing import BudgetExceeded, Gemini
from src.official_filings import acquire_sources
from src.v06 import main


def test_official_snapshot_replay_uses_exact_hash_and_does_not_count_as_live(tmp_path, monkeypatch):
    import datetime as dt

    url = 'https://www1.hkexnews.hk/annual.htm'
    source = b'''<h1>Example Finance Holdings</h1><h2>Consolidated Income Statement</h2>
    <p>Year ended 31 December 2024</p><p>HKD thousands</p>
    <table><tr><th></th><th>2024</th><th>2023</th></tr>
    <tr><td>Revenue</td><td>1500</td><td>1300</td></tr></table>'''
    digest = sha256(source).hexdigest()
    permissions = tmp_path / 'approved'
    permissions.mkdir()
    (permissions / digest).write_bytes(source)
    notes = tmp_path / 'requests.csv'
    pd.DataFrame([dict(venue='HKEX', ticker='0001.HK', issuer_id='HK:1234', issuer_name='Example Finance Holdings',
                       period_start='2024-01-01', period_end='2024-12-31', publication_date='2025-06-18',
                       source_url=url, expected_sha256=digest)]).to_csv(notes, index=False)

    def no_network(*args, **kwargs):
        pytest.fail('Replay must not call the official publisher')

    monkeypatch.setattr('src.official_filings.download', no_network)
    raw = tmp_path / 'retained'
    cutoff = dt.date(2026, 11, 1)
    rows, attempts = acquire_sources(notes, None, raw, cutoff, 1, 0, {}, replay_dir=permissions)
    item, = rows
    assert item['acquisition'] == 'OFFICIAL_REPLAY'
    assert attempts[0]['status'] == 'REPLAY_PARSED' and not attempts[0]['attempted']
    comparable = dict(item, value='1490')
    assert reconcile(rows, [comparable], raw, cutoff)[0]['status'] == 'MACHINE_RECONCILED'
    (permissions / digest).write_bytes(b'changed')
    rows, attempts = acquire_sources(notes, None, raw, cutoff, 1, 0, {}, replay_dir=permissions)
    assert not rows and attempts[0]['reason'] == 'REPLAY_ORIGINAL_CHECKSUM_MISMATCH'


def test_gemini_response_cache_and_reservations(monkeypatch, tmp_path):
    from google import genai
    from google.genai import types

    hits = []

    def generate(**request):
        hits.append(request['contents'])
        return types.GenerateContentResponse(
            model_version='gemini-testing', usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=100, candidates_token_count=20),
            candidates=[types.Candidate(content=types.Content(parts=[types.Part(text='{"observations":[]}')]))])

    monkeypatch.setattr(genai, 'Client', lambda **kwargs: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    tracker = Gemini('test', 'test-model', 2, 0, max_output_tokens=100, total_output_budget=100,
                     cache_path=tmp_path / 'cache.sqlite', input_price=2, output_price=4)
    tracker.document_sha256 = 'a' * 64
    assert tracker.generate('prompt').text == '{"observations":[]}'
    assert tracker.generate('prompt').text == '{"observations":[]}'
    assert tracker.cache_hits == 1 and tracker.requests == 1 and tracker.responses_received == 1
    assert tracker.estimated_cost == pytest.approx(.00028)
    with pytest.raises(BudgetExceeded, match='reservation'):
        tracker.generate('new prompt')
    tracker.document_sha256 = 'b' * 64
    with pytest.raises(BudgetExceeded, match='reservation'):
        tracker.generate('prompt')
    assert hits == ['prompt']


def test_gemini_quota_and_unknown_model_use_expected_retry_budget(monkeypatch):
    from google import genai
    from google.genai.errors import ClientError

    seen = []
    reason = 429

    def generate(**request):
        seen.append(request['model'])
        raise ClientError(reason, {'error': {'message': 'test provider error'}})

    monkeypatch.setattr(genai, 'Client', lambda **kwargs: SimpleNamespace(models=SimpleNamespace(generate_content=generate)))
    monkeypatch.setattr('src.gemini_filing.time.sleep', lambda seconds: None)
    quota = Gemini('test', 'test-model', 2, 1)
    with pytest.raises(ClientError):
        quota.generate('prompt')
    assert quota.requests == 2 and quota.responses_received == 0
    reason = 404
    missing = Gemini('test', 'unknown-model', 2, 1)
    with pytest.raises(ClientError):
        missing.generate('prompt')
    assert missing.requests == 1 and seen[-1] == 'unknown-model'


def test_snapshot_explicit_retrieval_date_cannot_pass_historical_cutoff(tmp_path):
    snapshot = tmp_path / 'future.csv'
    snapshot.write_text('ticker,retrieved_at_utc\n005930.KS,2026-11-19T00:00:00Z\n')
    output = tmp_path / 'results'
    with pytest.raises(ValueError, match='after the as-of date'):
        main(['--snapshot-csv', str(snapshot), '--discover-mode', 'off', '--asof-date', '2026-11-18',
              '--output', str(output)])
    result = json.loads((output / '67_v06_run_manifest.json').read_text())
    assert result['run_status'] == 'FAILED_INTERNAL_ERROR'
    assert result['trade_orders'] == 'NONE'
