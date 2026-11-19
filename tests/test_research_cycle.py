from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

import pandas as pd
import pytest

from src import research_cycle as cycle
from src.industry_classification import classify, issuer_representatives, load_registry, vendor_security_type
from src.scoring_v03 import SUBMETRICS


ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 6, 1, 12, tzinfo=timezone.utc)


def make_plan(directory, count=10, *, shard_size=3, cycle_id='test-123'):
    discovered = directory / 'discovered'
    discovered.mkdir(parents=True)
    rows = [{
        'ticker': f'{index:06d}.{("SZ", "HK", "T", "KS", "TW")[index % 5]}',
        'company': f'Example {index}', 'market': cycle.MARKETS[index % 5],
        'peer_group': 'unclassified', 'industry_thesis': '', 'is_new_discovery': 'True',
        'discovery_source': 'TEST_FIXTURE', 'security_type_status': 'VERIFIED_EQUITY_VENDOR',
    } for index in range(count)]
    pd.DataFrame(rows + [{**rows[0], 'discovery_source': 'ADDITIONAL_VENUE_EVIDENCE'}]).to_csv(
        discovered / '11_discovery_universe.csv', index=False)
    pd.DataFrame([{'source': 'fixture', 'status': 'OK', 'market': market, 'source_kind': 'TEST_FIXTURE',
                   'out_n': 1, 'error': ''} for market in cycle.MARKETS]).to_csv(
        discovered / '12_discovery_sources_log.csv', index=False)
    path = directory / 'plan'
    cycle.freeze(discovered, path, cycle_id, shard_size, cutoff=NOW.date())
    return path, cycle.load_plan(path)


def financial(ticker):
    return {**dict.fromkeys((field for fields in SUBMETRICS.values() for field in fields), .16),
            'vendor_quote_type': 'EQUITY', 'provider_financial_period_end': '2026-03-31',
            'forward_pe': 15, 'price_to_sales': 2, 'source_url': f'https://example.org/{ticker}',
            'currency': 'USD', 'financial_currency': 'USD'}


def test_all_16671_securities_sharded_once_and_raw_provenance_kept(tmp_path):
    _, plan = make_plan(tmp_path, 16671, shard_size=100)
    union = [ticker for shard in plan['shards'].values() for ticker in shard['tickers']]
    assert len(union) == len(set(union)) == 16671
    assert set(union) == {item['ticker'] for item in plan['discovered']}
    assert len(plan['listings']) == 16672
    assert all(len(shard['tickers']) <= 100 for shard in plan['shards'].values())


def test_interrupted_attempt_and_success_restore_without_refetch(tmp_path):
    _, plan = make_plan(tmp_path)
    shard, spec = next(iter(plan['shards'].items()))
    original, restored = tmp_path / 'original', tmp_path / 'restored'
    cycle.run_shard(plan, shard, original, 1, 0, fetch=financial, clock=lambda: NOW)
    with closing(cycle.connect_checkpoint(cycle.checkpoint_path(original, shard), plan, shard)) as db:
        interrupted = cycle.claim(db, NOW)
    cycle.restore(plan, original, restored)
    called = []

    def vendor(ticker):
        called.append(ticker)
        return financial(ticker)

    cycle.run_shard(plan, shard, restored, 3, 0, fetch=vendor, clock=lambda: NOW + timedelta(minutes=1))
    assert called == []
    cycle.run_shard(plan, shard, restored, 3, 0, fetch=vendor, clock=lambda: NOW + timedelta(minutes=16))
    assert called == [interrupted[0]]
    _, rows = cycle.summaries(plan, restored)
    assert [rows[ticker]['attempt_count'] for ticker in spec['tickers']] == [1, 2]
    assert [rows[ticker]['requests_completed'] for ticker in spec['tickers']] == [1, 1]
    cycle.restore(plan, original, restored)
    assert cycle.summaries(plan, restored)[1][interrupted[0]]['attempt_count'] == 2


def test_concurrent_local_workers_claim_each_ticker_once(tmp_path):
    _, plan = make_plan(tmp_path, 50, shard_size=30)
    shard, spec = next(iter(plan['shards'].items()))
    state = tmp_path / 'state'
    called = []

    def vendor(ticker):
        called.append(ticker)
        return financial(ticker)

    def run():
        cycle.run_shard(plan, shard, state, 10, 0, fetch=vendor, clock=lambda: NOW)

    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = [executor.submit(run) for _ in range(3)]
        for future in futures:
            future.result()
    assert sorted(called) == spec['tickers']


def test_corruption_wrong_snapshot_and_independent_fork_are_rejected(tmp_path):
    plan_path, plan = make_plan(tmp_path / 'one')
    _, other = make_plan(tmp_path / 'two', cycle_id='other')
    shard = next(iter(plan['shards']))
    first, fork = tmp_path / 'first', tmp_path / 'fork'
    for directory in (first, fork):
        cycle.run_shard(plan, shard, directory, 1, 0, fetch=financial, clock=lambda: NOW)
    with pytest.raises(ValueError, match='Forked'):
        cycle.restore(plan, fork, first)
    with pytest.raises(ValueError, match='Incompatible'):
        cycle.restore(other, first, tmp_path / 'wrong')
    with sqlite3.connect(cycle.checkpoint_path(first, shard)) as db:
        db.execute("UPDATE work SET payload='{}' WHERE payload IS NOT NULL")
    with pytest.raises(ValueError, match='checksum'):
        cycle.restore(plan, first, tmp_path / 'broken')
    (plan_path / 'plan.json').write_text('{}')
    with pytest.raises(ValueError, match='checksum'):
        cycle.load_plan(plan_path)


def test_rate_limit_stops_shard_and_budget_is_bounded(tmp_path, monkeypatch):
    _, plan = make_plan(tmp_path)
    shard, spec = next(iter(plan['shards'].items()))
    state = tmp_path / 'state'
    monkeypatch.setattr(cycle, 'utcnow', lambda: NOW)
    called = []

    class YFRateLimitError(Exception):
        pass

    def refused(ticker):
        called.append(ticker)
        raise YFRateLimitError()

    cycle.run_shard(plan, shard, state, 2, 0, fetch=refused, clock=lambda: NOW)
    _, rows = cycle.summaries(plan, state)
    assert called == spec['tickers'][:1]
    assert rows[called[0]]['status'] == 'BLOCKED_PROVIDER'
    assert rows[called[0]]['retry_eligible_now'] is False
    assert cycle.dispatch(plan, state, '', 10, 50, 10, reserved=10) == []
    jobs = cycle.dispatch(plan, state, spec['market'], 10, 50, 10, reserved=9)
    assert jobs == [{'shard': shard, 'budget': 1}]
    cycle.run_shard(plan, shard, state, 2, 0, quota_date=(NOW - timedelta(days=1)).date(),
                    fetch=refused, clock=lambda: NOW)
    assert len(called) == 1


def test_aggregation_uses_frozen_union_and_never_promotes_pending_run(tmp_path, monkeypatch):
    _, plan = make_plan(tmp_path, count=10)
    state = tmp_path / 'state'
    first = next(iter(plan['shards']))
    cycle.run_shard(plan, first, state, 2, 0, fetch=financial, clock=lambda: NOW)
    output = tmp_path / 'report'
    cycle.aggregate(plan, state, output, ROOT / 'data/universe.csv')
    manifest = json.loads((output / '67_v06_run_manifest.json').read_text())
    assert manifest['run_status'] == 'FULL_CYCLE_IN_PROGRESS'
    assert sum(row['scheduled'] for row in manifest['market_coverage'].values()) == 10
    assert sum(row['retrieved'] for row in manifest['market_coverage'].values()) == 2
    assert manifest['trade_orders'] == 'NONE'
    assert len(pd.read_csv(output / 'research/08_selected_universe.csv')) == 10
    assert not (output / '.cycle-financial-replay.csv').exists()
    for shard in plan['shards']:
        cycle.run_shard(plan, shard, state, 10, 0, fetch=financial, clock=lambda: NOW)
    cycle.aggregate(plan, state, tmp_path / 'complete', ROOT / 'data/universe.csv')
    complete = json.loads((tmp_path / 'complete/67_v06_run_manifest.json').read_text())
    assert complete['run_status'] == 'FULL_CYCLE_COMPLETE'
    assert sum(row['retrieved'] for row in complete['market_coverage'].values()) == 10
    assert complete['universe_census_verified'] is False


def test_cross_run_restore_shell_uses_artifact_state_and_quota(tmp_path):
    plan_path, plan = make_plan(tmp_path / 'initial', cycle_id='123')
    shard = next(iter(plan['shards']))
    artifact = tmp_path / 'saved'
    cycle.run_shard(plan, shard, artifact, 1, 0, fetch=financial)
    mock = tmp_path / 'bin'
    mock.mkdir()
    exe = mock / 'gh'
    exe.write_text('''#!/usr/bin/env bash
set -e
if [[ "$1" == api ]]; then
  printf 'garp-cycle-123-state-1\t124\t2026-01-01T00:00:00Z\t50\n'
  printf 'garp-cycle-123-quota-%s-6-124-1\t124\t2026-01-01T00:00:00Z\t51\n' "$(date -u +%F)"
else
  mkdir -p "$7"
  case "$5" in
    *-plan) cp "$MOCK_PLAN"/* "$7";;
    *-state-1) cp "$MOCK_STATE"/*.sqlite "$7";;
    *) exit 2;;
  esac
fi
''')
    exe.chmod(0o755)
    runner = tmp_path / 'runner'
    runner.mkdir()
    environment = dict(os.environ, PATH=os.pathsep.join([str(mock), str(Path(sys.executable).parent), os.environ['PATH']]),
                       PYTHONPATH=str(ROOT), RUNNER_TEMP=str(runner), GITHUB_REPOSITORY='test/project',
                       GITHUB_OUTPUT=str(tmp_path / 'outputs.txt'), MOCK_PLAN=str(plan_path), MOCK_STATE=str(artifact),
                       GARP_CYCLE='123', GARP_CYCLE_ARTIFACTS='1', GARP_CYCLE_MODE='batch',
                       GARP_CYCLE_EXPLICIT='true', GARP_CYCLE_MARKET='All', GARP_CYCLE_DAILY_BUDGET='6',
                       GARP_CYCLE_MAX_SHARDS='2', GARP_CYCLE_JOB_BUDGET='3')
    subprocess.run(['bash', str(ROOT / '.github/scripts/restore-research-cycle.sh')], cwd=tmp_path,
                   env=environment, check=True)
    assert (tmp_path / 'cycle-working/state' / f'{shard}.sqlite').exists()
    assert 'jobs=0' in (tmp_path / 'outputs.txt').read_text()


def test_classification_security_and_issuer_identity_are_independent(tmp_path):
    assert vendor_security_type({'vendor_quote_type': 'EQUITY', 'vendor_industry': 'Shell Companies'}) == 'SHELL_OR_SPAC'
    assert vendor_security_type({'vendor_quote_type': 'ETF'}) == 'ETF'
    evidence = {'issuer_id': 'CN:registry-company-123', 'security_type': 'OPERATING_EQUITY',
                'source_kind': 'OFFICIAL_ISSUER', 'peer_group': 'chip_equipment',
                'source_url': 'https://example.org/issuer/statement', 'source_date': '2026-02-01',
                'reviewed_by': 'Analyst 1', 'review_date': '2026-02-05', 'counter': ''}
    path = tmp_path / 'review.csv'
    pd.DataFrame([dict(evidence, ticker='600000.SS', share_class='A'),
                  dict(evidence, ticker='900000.SS', share_class='B'),
                  dict(evidence, ticker='001.HK', share_class='Ordinary', counter='HKD',
                       source_kind='SOURCE_GROUNDED_GEMINI', reviewed_by='', review_date='')]).to_csv(path, index=False)
    registry = load_registry(path, NOW.date())
    baseline = {'vendor_quote_type': 'EQUITY', 'peer_group': 'unclassified'}
    a = classify(baseline, registry['600000.SS'])
    b = classify(baseline, registry['900000.SS'])
    unresolved = classify(baseline, registry['001.HK'])
    assert a['industry_confidence'] == 'HUMAN_REVIEWED'
    assert b['classification_share_class'] == 'B'
    assert a['classification_issuer_id'] == b['classification_issuer_id']
    assert unresolved['operating_peer_group'] == 'unclassified'
    assert unresolved['industry_confidence'] == 'PROPOSED_NEEDS_REVIEW'
    assert len(issuer_representatives(pd.DataFrame([a, b, unresolved]))) == 2
    assert load_registry(path, (NOW - timedelta(days=200)).date()) == {}


def test_classification_before_after_changes_only_supported_mappings(tmp_path):
    _, plan = make_plan(tmp_path, count=10)
    state = tmp_path / 'state'
    tickers = [row['ticker'] for row in plan['discovered']]
    first, second, shell = tickers[:3]

    def vendor(ticker):
        row = financial(ticker)
        row['vendor_industry'] = 'Shell Companies' if ticker == shell else ''
        return row

    for shard in plan['shards']:
        cycle.run_shard(plan, shard, state, 5, 0, fetch=vendor, clock=lambda: NOW)
    registry = tmp_path / 'classification.csv'
    pd.DataFrame([
        {'ticker': ticker, 'issuer_id': 'CN:12345', 'security_type': 'OPERATING_EQUITY',
         'share_class': share_kind, 'counter': share_kind, 'peer_group': 'chip_equipment',
         'source_kind': 'OFFICIAL_ISSUER', 'source_url': 'https://example.org/filing',
         'source_date': '2026-03-01', 'reviewed_by': 'Example reviewer', 'review_date': '2026-04-01'}
        for ticker, share_kind in ((first, 'A'), (second, 'B'))
    ]).to_csv(registry, index=False)
    output = tmp_path / 'compared'
    cycle.aggregate(plan, state, output, ROOT / 'data/universe.csv', registry)
    audit = pd.read_csv(output / 'research/70_industry_classification_audit_v1.csv').set_index('ticker')
    assert audit.loc[[first, second], 'legacy_peer_group'].eq('unclassified').all()
    assert audit.loc[[first, second], 'eligibility_changed'].all()
    assert audit.loc[[first, second], 'industry_confidence'].eq('HUMAN_REVIEWED').all()
    assert audit.loc[[first, second], 'issuer_research_representative'].sum() == 1
    assert audit.loc[shell, 'v031_research_status'] == 'REJECT_NON_EQUITY_INSTRUMENT'
    assert audit['industry_confidence'].eq('UNRESOLVED').sum() == 8
    result = pd.read_csv(output / 'research/32_research_stage_gate.csv')
    assert not result.research_stage.eq('MEMO_READY').any()


def test_future_provider_period_is_recorded_without_scoring(tmp_path):
    _, plan = make_plan(tmp_path)
    shard = next(iter(plan['shards']))
    state = tmp_path / 'state'
    cycle.run_shard(plan, shard, state, 1, 0, clock=lambda: NOW,
                    fetch=lambda ticker: {**financial(ticker), 'provider_financial_period_end': '2030-01-01'})
    _, items = cycle.summaries(plan, state)
    first = items[plan['shards'][shard]['tickers'][0]]
    assert (first['status'], first['error']) == ('PERMANENT_FAILURE', 'LOOKAHEAD_PROVIDER_PERIOD')
