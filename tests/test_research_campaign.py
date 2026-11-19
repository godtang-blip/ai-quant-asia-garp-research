from collections import Counter
from datetime import timedelta
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pandas as pd
import pytest

from src import research_campaign as campaign, research_cycle as cycle, v06
from src.industry_classification import campaign_classify, classify
from src.official_universe import JPX_JAPANESE_XLS, parse_jpx_table
from test_research_cycle import ROOT, financial, make_plan


def settings(monkeypatch, *, total=10, daily=50):
    monkeypatch.setenv('GARP_CYCLE_DAILY_BUDGET', str(daily))
    monkeypatch.setenv('GARP_CYCLE_JOB_BUDGET', '5')
    monkeypatch.setenv('GARP_CAMPAIGN_TOTAL_BUDGET', str(total))
    monkeypatch.setenv('GARP_FILING_BUDGET', '1')
    for key in ('GARP_ENABLE_MODEL', 'DART_API_KEY', 'EDINET_API_KEY', 'GEMINI_API_KEY'):
        monkeypatch.delenv(key, raising=False)
    return campaign.config_from_environment('research-now')


def fetch(ticker):
    return {**financial(ticker), 'vendor_industry': 'Semiconductor Foundry', 'provider_name': ticker}


def test_restored_batch_two_waves_classify_aggregate_and_trigger_dossiers(tmp_path, monkeypatch):
    _, plan = make_plan(tmp_path, count=225, shard_size=20, cycle_id='44456766424')
    now = cycle.utcnow()
    batch, state = tmp_path / 'completed-batch', tmp_path / 'cycle-state'
    # Simulate the previous code's ticker-order calls and immutable checkpoint export.
    remaining = 200
    for shard, spec in plan['shards'].items():
        budget = min(remaining, len(spec['tickers']))
        cycle.run_shard(plan, shard, batch, budget, 0, fetch=fetch, clock=lambda: now)
        remaining -= budget
        if not remaining:
            break
    cycle.restore(plan, batch, state)
    baseline = {ticker: row['response_sha256'] for ticker, row in cycle.summaries(plan, state, now)[1].items()
                if row.get('payload')}
    published = dict(plan_sha256=plan['plan_sha256'], cycle_id=plan['cycle_id'],
                     market_coverage={'test': {'provider_attempts': 200}})
    campaign.verify_handoff(plan, state, published, now)
    with pytest.raises(ValueError, match='does not contain'):
        campaign.verify_handoff(plan, tmp_path / 'missing', published, now)

    config = settings(monkeypatch, daily=300)
    first = campaign.prepare(plan, state, '912', 'abc', 'pr-branch', 'research-now', '911',
                             config=config, reserved_today=200, now=now)
    assert len(first['jobs']) == 5
    assert not set(baseline).intersection(row['ticker'] for row in first['jobs'])
    official_calls = []
    original = v06.prepare_inputs

    def record_preparation(*args, **kwargs):
        official_calls.append(args[2])
        return original(*args, **kwargs)

    monkeypatch.setattr(v06, 'prepare_inputs', record_preparation)
    first_progress = campaign.collect(plan, state, first, clock=lambda: now, sleep=lambda _: None, fetch=fetch)
    first_output = tmp_path / 'wave1'
    first_result = campaign.publish_report(plan, state, first, first_progress, first_output,
                                           tmp_path / 'private', ROOT / 'data/universe.csv', now=now)
    assert first_result['status'] == 'CONTINUE_READY' and not official_calls
    # A fresh job restores the legacy-format state from the previous wave.
    next_state = tmp_path / 'wave2-state'
    cycle.restore(plan, state, next_state)
    second = campaign.prepare(plan, next_state, '913', 'abc', 'pr-branch', 'continue', '912',
                              previous=first_result, previous_lease=first, reserved_today=205, now=now)
    assert not {row['ticker'] for row in first['jobs']}.intersection(row['ticker'] for row in second['jobs'])
    with pytest.raises(ValueError, match='revision'):
        campaign.prepare(plan, next_state, '914', 'changed', 'pr-branch', 'continue', '912',
                         previous=first_result, previous_lease=first, now=now)
    second_progress = campaign.collect(plan, next_state, second, clock=lambda: now, sleep=lambda _: None, fetch=fetch)
    output = tmp_path / 'final'
    result = campaign.publish_report(plan, next_state, second, second_progress, output,
                                     tmp_path / 'private', ROOT / 'data/universe.csv', now=now, parent_report=first_output)
    _, items = cycle.summaries(plan, next_state, now)
    assert {ticker: items[ticker]['response_sha256'] for ticker in baseline} == baseline
    assert sum(row['attempt_count'] for row in items.values()) == 210
    assert result['status'] == 'COMPLETE' and result['reason'] == 'RESEARCH_NOW_SAMPLE_LIMIT'
    assert result['evidence_run_id'] == '913' and len(official_calls) == 1 and official_calls[0]
    assert (output / 'research/71_research_dossiers/index.json').is_file()
    assert (output / '74_campaign_summary.md').is_file()
    audit = pd.read_csv(output / '75_campaign_security_audit.csv')
    assert audit.industry_confidence.eq('AUTO_CLASSIFIED').sum() == 210
    assert audit.loc[audit.selected, 'operating_peer_group'].eq('chip_manufacturing').all()
    assert audit.loc[audit.selected, 'legacy_peer_group'].eq('chip_components').all()
    assert result['research_evidence']['gemini']['api_responses_received'] == 0
    assert sum(market['discovered'] for market in result['market_coverage'].values()) == 225
    expanded = campaign.prepare(
        plan, next_state, '914', 'abc', 'pr-branch', 'full-sweep', '913',
        previous=result, previous_lease=second, reserved_today=210, now=now,
        config={**config, 'mode': 'full-sweep', 'total': 15})
    assert expanded['campaign_id'] == '914' and expanded['checkpoint_attempts_before'] == 210
    assert expanded['evidence_run_id'] == '913' and not expanded['evidence_allowed']
    assert len(expanded['jobs']) == expanded['financial_reserved_total'] == 5
    assert all(items[row['ticker']]['status'] == 'NOT_STARTED' for row in expanded['jobs'])


def test_stable_sampling_spreads_markets_and_industries_beyond_first_shards(tmp_path):
    _, plan = make_plan(tmp_path, count=100, shard_size=2)
    _, items = cycle.summaries(plan, tmp_path / 'empty')
    groups = {ticker: ('chip_components' if int(ticker.split('.')[0]) % 2 else 'consumer_brands') for ticker in items}
    exclusions = {next(iter(items)): 'FUND'}
    jobs, markets, industries = campaign.schedule(plan, items, exclusions, groups, {}, 20)
    assert campaign.schedule(plan, items, exclusions, groups, {}, 20)[0] == jobs
    assert set(markets) == set(cycle.MARKETS)
    assert sorted(markets.values()) == [4] * 5
    assert industries == {'chip_components': 10, 'consumer_brands': 10}
    assert len({row['shard'] for row in jobs}) > 10
    assert not set(exclusions).intersection(row['ticker'] for row in jobs)
    assert len({row['ticker'] for row in jobs}) == 20


def test_rate_limit_pause_and_resume_without_duplicate_reservations(tmp_path, monkeypatch):
    _, plan = make_plan(tmp_path, count=20)
    cfg = settings(monkeypatch, daily=6)
    now = cycle.utcnow()
    state = tmp_path / 'state'
    first = campaign.prepare(plan, state, '921', 'abc', 'pr', 'research-now', '920',
                             config=cfg, reserved_today=4, now=now)
    assert len(first['jobs']) == 2
    calls = []
    def limited(ticker):
        calls.append(ticker)
        raise campaign.FinancialRateLimit()
    result = campaign.collect(plan, state, first, clock=lambda: now, sleep=lambda _: None, fetch=limited)
    assert len(calls) == 1
    assert result['stop_reason'] == 'FINANCIAL_PROVIDER_RATE_LIMIT_OR_AUTH'
    report = campaign.publish_report(plan, state, first, result, tmp_path / 'paused',
                                     tmp_path / 'private', ROOT / 'data/universe.csv', now=now)
    assert report['status'] == 'PAUSED'
    common = dict(previous=report, previous_lease=first)
    before = campaign.prepare(plan, state, '922', 'abc', 'pr', 'resume', '921', now=now, **common)
    assert not before['jobs'] and before['reason'] == 'FINANCIAL_PROVIDER_RATE_LIMIT_OR_AUTH'
    tmr = now + timedelta(hours=25)
    resumed = campaign.prepare(plan, state, '922', 'abc', 'pr', 'resume', '921', now=tmr, **common)
    assert len(resumed['jobs']) == 5 and resumed['financial_reserved_total'] == 7
    stopped = campaign.prepare(plan, state, '923', 'abc', 'pr', 'resume', '921', now=tmr, control='cancel', **common)
    assert stopped['status'] == 'CANCELLED' and not stopped['jobs']
    # A stale reservation cannot claim the same ticker or increment its attempt history.
    repeated = campaign.collect(plan, state, first, clock=lambda: now, sleep=lambda _: None, fetch=limited)
    assert repeated['stop_reason'] == 'RESERVATION_CHANGED_BEFORE_CALL' and len(calls) == 1


def test_daily_cap_full_sweep_and_forged_parent(tmp_path, monkeypatch):
    _, plan = make_plan(tmp_path)
    cfg = {**settings(monkeypatch, daily=5), 'mode': 'full-sweep'}
    now = cycle.utcnow()
    first = campaign.prepare(plan, tmp_path, '100', 'abc', 'pr', 'full-sweep', '90',
                             config=cfg, reserved_today=5, now=now)
    assert not first['jobs'] and first['reason'] == 'DAILY_FINANCIAL_BUDGET'
    report = {'status': 'PAUSED', 'lease_sha256': 'forged'}
    with pytest.raises(ValueError, match='lease'):
        campaign.prepare(plan, tmp_path, '101', 'abc', 'pr', 'resume', '100',
                         previous=report, previous_lease=first, now=now)


def test_transport_cap_blocks_sdk_retry_and_preserves_status():
    now = cycle.utcnow()
    responses = []
    session = SimpleNamespace(request=lambda *args, **kwargs: responses.pop(0))
    reserved = {}

    def sdk(ticker, *, session):
        for _ in range(10):
            session.request('GET', 'https://example.org', timeout=999)
        return {}

    target = campaign.bounded_vendor(session, sdk, reserved, now + timedelta(seconds=1), lambda: now)
    responses.extend([SimpleNamespace(status_code=200)] * 10)
    with pytest.raises(campaign.FinancialTransportLimit):
        target('123.T')
    assert len(responses) == 2 and reserved == {'123.T': 8}
    responses[:] = [SimpleNamespace(status_code=429), SimpleNamespace(status_code=200)]
    with pytest.raises(campaign.FinancialRateLimit):
        target('456.T')
    assert len(responses) == 1 and reserved['456.T'] == 1


def test_industry_conflicts_excluded_instruments_and_official_issuer_matching(tmp_path):
    row = dict(ticker='1111.T', company='Example Co.', market='Japan', vendor_quote_type='EQUITY',
               vendor_industry='Pharmaceuticals', peer_group='consumer_brands',
               sector_mapping_status='CURATED_HUMAN_TAXONOMY_UNVERIFIED')
    result = campaign_classify(row, classify(row, None), None, '2026-11-19')
    assert result['industry_confidence'] == 'CONFLICTED' and result['operating_peer_group'] == 'unclassified'
    excluded = {**row, 'security_type': 'Preferred Stock'}
    result = campaign_classify(excluded, classify(excluded, None), None, '2026-11-19')
    assert result['industry_confidence'] == 'EXCLUDED_INSTRUMENT' and result['instrument_class'] == 'PREFERRED'
    for kind in ('ETF', 'FUND', 'REIT', 'SPAC'):
        excluded = {**row, 'security_type': kind}
        assert campaign_classify(excluded, classify(excluded, None), None, '')['instrument_class'] == kind
    unreviewed = {**row, 'peer_group': 'unclassified', 'vendor_industry': 'Electronic Components'}
    assert campaign_classify(unreviewed, classify(unreviewed, None), None, '')['industry_confidence'] == 'UNRESOLVED'
    frame = pd.DataFrame([['1111', 'Example Co.', 'プライム', '医薬品', '20261101'],
                          ['1112', 'Different Legal Entity', 'プライム', '食料品', '20261101']],
                         columns=['コード', '銘柄名', '市場・商品区分', '33業種区分', '日付'])
    plan = {'listings': [{**row, 'discovery_source': JPX_JAPANESE_XLS},
                         {**row, 'ticker': '1112.T', 'discovery_source': JPX_JAPANESE_XLS}]}
    result = campaign.exchange_metadata(plan, cycle.utcnow(),
                                        fetch=lambda **kw: parse_jpx_table(frame, JPX_JAPANESE_XLS, **kw))
    assert result['status'] == 'MATCHED_FROZEN_ISSUERS'
    assert result['rows'] == {'1111.T': {'exchange_industry': '医薬品',
                                        'listing_source_url': JPX_JAPANESE_XLS, 'listing_source_date': '2026-11-01'}}


def test_same_workflow_continuation_targets_pr_branch_and_does_not_replace_pending_run(tmp_path):
    mock = tmp_path / 'gh'
    mock.write_text("""#!/usr/bin/env bash
set -e
case "$*" in
  *git/ref/heads/*) printf '%s\\n' "$MOCK_SHA";;
  *status=queued*) printf '%s' "$MOCK_QUEUED";;
  *status=*) ;;
  *dispatches*) cat > "$MOCK_DISPATCH";;
  *) exit 3;;
esac
""")
    mock.chmod(0o755)
    env = dict(os.environ, GITHUB_REF_NAME='codex/garp-v06-integrated-research',
               GITHUB_REF='refs/heads/codex/garp-v06-integrated-research', GITHUB_RUN_ID='932',
               GITHUB_SHA='test-sha', GITHUB_REPOSITORY='example/repo', GITHUB_RUN_ATTEMPT='1',
               GARP_CYCLE='44456766424', MOCK_SHA='test-sha', MOCK_DISPATCH=str(tmp_path / 'dispatch'),
               MOCK_QUEUED='', PATH=f'{tmp_path}{os.pathsep}{os.environ["PATH"]}')
    script = ['bash', str(ROOT / '.github/scripts/campaign-transition.sh'), 'continue']
    subprocess.run(script, env=env, check=True)
    body = json.loads((tmp_path / 'dispatch').read_text())
    assert body == {'ref': 'codex/garp-v06-integrated-research',
                    'inputs': {'cycle_mode': 'autopilot-continue', 'cycle_state': '44456766424',
                               'max_symbols': '932'}}
    (tmp_path / 'dispatch').unlink()
    assert subprocess.run(script, env={**env, 'MOCK_QUEUED': '933'}).returncode == 2
    assert subprocess.run(script, env={**env, 'MOCK_SHA': 'changed'}).returncode == 2
    assert not (tmp_path / 'dispatch').exists()


def test_resume_failed_wave_blocks_uncertain_calls_and_keeps_completed_observations(tmp_path, monkeypatch):
    _, plan = make_plan(tmp_path, count=20)
    config = settings(monkeypatch)
    now = cycle.utcnow()
    state = tmp_path / 'state'
    first = campaign.prepare(plan, state, '961', 'abc', 'pr', 'research-now', '960',
                             config=config, now=now)
    complete = first['jobs'][0]
    cycle.run_shard(plan, complete['shard'], state, 1, 0, selected_ticker=complete['ticker'],
                    fetch=fetch, clock=lambda: now)
    recovered = campaign.prepare(plan, state, '962', 'abc', 'pr', 'resume', '961',
                                 previous_lease=first, recover=True, reserved_today=5, now=now)
    uncertain = {row['ticker'] for row in first['jobs'][1:]}
    assert set(recovered['uncertain_attempts']) == uncertain
    assert recovered['evidence_uncertain'] and not recovered['evidence_allowed']
    assert len(recovered['jobs']) == 5
    assert not (uncertain | {complete['ticker']}).intersection(row['ticker'] for row in recovered['jobs'])
    assert cycle.summaries(plan, state)[1][complete['ticker']]['status'] == 'SUCCESS'


def test_workflow_restore_accepts_completed_batch_and_rejects_in_progress_handoff(tmp_path):
    plan_path, plan = make_plan(tmp_path / 'frozen', count=20, cycle_id='123')
    run = '940'
    now = cycle.utcnow()
    batch_state = tmp_path / 'batch-state'
    shard = next(iter(plan['shards']))
    cycle.run_shard(plan, shard, batch_state, 1, 0, fetch=fetch, clock=lambda: now)
    quota = tmp_path / 'batch-quota'
    report = tmp_path / 'batch-report'
    campaign.write(quota / 'cycle-quota.json', {'items': [{'shard': shard, 'budget': 1}]})
    campaign.write(report / '67_v06_run_manifest.json', dict(
        cycle_id='123', plan_sha256=plan['plan_sha256'], market_coverage={'market': {'provider_attempts': 1}}))
    artifacts = {
        'garp-cycle-123-plan': plan_path, 'garp-cycle-123-state-1': batch_state,
        'garp-cycle-123-report-1': report, f'garp-cycle-123-quota-{now.date()}-1-{run}-1': quota,
    }
    metadata = tmp_path / 'artifact-paths.json'
    metadata.write_text(json.dumps({name: str(path) for name, path in artifacts.items()}))
    fake = tmp_path / 'bin' / 'gh'
    fake.parent.mkdir()
    fake.write_text(f"""#!{sys.executable}
import json, os, shutil, sys
from pathlib import Path
args = sys.argv[1:]
artifacts = json.loads(Path(os.environ['MOCK_ARTIFACTS']).read_text())
if args[0] == 'run':
    shutil.copytree(artifacts[args[4]], args[6], dirs_exist_ok=True)
elif args[1] == '--paginate':
    for artifact in artifacts:
        print(artifact, '940', '2026-11-19T00:00:00Z', '100', sep='\\t')
else:
    print(json.dumps(dict(status=os.environ['MOCK_RUN_STATUS'], conclusion='success',
                          head_branch='pr', path='.github/workflows/run-research-v05.yml', run_attempt=1)))
""")
    fake.chmod(0o755)
    # The production script invokes the existing restore script by its repo path.
    (tmp_path / '.github').symlink_to(ROOT / '.github', target_is_directory=True)
    script = ['bash', str(ROOT / '.github/scripts/campaign-transition.sh'), 'restore']
    for status in ('in_progress', 'completed'):
        cwd = tmp_path / status
        cwd.mkdir()
        (cwd / '.github').symlink_to(ROOT / '.github', target_is_directory=True)
        temp = cwd / 'runner'
        temp.mkdir()
        env = dict(os.environ, PATH=os.pathsep.join([str(fake.parent), str(Path(sys.executable).parent), os.environ['PATH']]),
                   GITHUB_REF='refs/heads/pr', GITHUB_REF_NAME='pr', GITHUB_RUN_ATTEMPT='1',
                   GITHUB_RUN_ID='941', GITHUB_REPOSITORY='test/garp', PYTHONPATH=str(ROOT),
                   RUNNER_TEMP=str(temp), GITHUB_OUTPUT=str(cwd / 'out'), MOCK_ARTIFACTS=str(metadata),
                   MOCK_RUN_STATUS=status, GARP_CYCLE='123', GARP_CYCLE_ARTIFACTS='1',
                   GARP_CAMPAIGN_CHECKPOINT=run, GARP_CAMPAIGN_MODE='research-now')
        result = subprocess.run(script, cwd=cwd, env=env)
        if status == 'in_progress':
            assert result.returncode == 2 and not (cwd / 'campaign-batch-report').exists()
        else:
            assert result.returncode == 0
            assert (cwd / 'cycle-working/state' / f'{shard}.sqlite').is_file()
            assert (cwd / 'campaign-batch-report/67_v06_run_manifest.json').is_file()
