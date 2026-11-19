"""Freeze, resume, and aggregate a bounded five-market financial research cycle."""
from collections import Counter, defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from importlib.metadata import version
import json
import math
from pathlib import Path
import re
import secrets
import sqlite3
import time

import pandas as pd

from .industry_classification import EXCLUDED, load_registry, vendor_security_type
from .scoring_v03 import SUBMETRICS, number
from .v031 import _fetch_vendor


SCHEMA = 2
PROVIDER = 'yfinance'
RETRIES = 3
TERMINAL = {'SUCCESS', 'SUCCESS_INCOMPLETE_DATA', 'PERMANENT_FAILURE', 'EXCLUDED_SECURITY_TYPE'}
READY = {'SUCCESS', 'SUCCESS_INCOMPLETE_DATA'}
INSTRUMENT_EXCLUSIONS = {'NON_EQUITY_VENDOR_EXCLUDED', 'REJECT_NON_EQUITY'}
MARKETS = ('China', 'Hong Kong', 'Japan', 'Korea', 'Taiwan')


def utcnow():
    return datetime.now(timezone.utc)


def packed(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()


def checksum(raw):
    return sha256(raw).hexdigest()


def freeze(discovery, target, cycle_id, shard_size, *, cutoff=None, classification=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', cycle_id) or not 1 <= shard_size <= 250:
        raise ValueError('Invalid cycle ID or shard size (1–250)')
    cutoff = cutoff or utcnow().date()
    raw = pd.read_csv(discovery / '11_discovery_universe.csv', dtype=str, keep_default_na=False)
    logs = pd.read_csv(discovery / '12_discovery_sources_log.csv', dtype=str, keep_default_na=False)
    listings = raw.to_dict('records')
    listings.sort(key=packed)
    by_ticker = {}
    for row in listings:
        ticker = row['ticker'].strip().upper()
        if not re.fullmatch(r'[A-Z0-9.^=-]{1,32}', ticker) or row['market'] not in MARKETS:
            raise ValueError('Invalid discovered ticker or market')
        existing = by_ticker.setdefault(ticker, {**row, 'ticker': ticker})
        if existing['market'] != row['market']:
            raise ValueError(f'Cross-market duplicate ticker: {ticker}')
        # Keep every original row. For the financial schedule prefer a classified listing.
        if existing.get('peer_group') == 'unclassified' and row.get('peer_group') != 'unclassified':
            by_ticker[ticker] = {**row, 'ticker': ticker}
    if not by_ticker:
        raise ValueError('Empty discovery cannot initialize a cycle')
    discovered = sorted(by_ticker.values(), key=lambda row: (row['market'], row['ticker']))
    eligible = defaultdict(list)
    registry = load_registry(classification, cutoff)
    for row in discovered:
        reviewed = registry.get(row['ticker'], {})
        if row.get('security_type_status') not in INSTRUMENT_EXCLUSIONS and not (
                reviewed.get('reviewed') and reviewed['security_type'] in EXCLUDED):
            eligible[row['market']].append(row['ticker'])
    shards = {}
    for market, tickers in sorted(eligible.items()):
        for start in range(0, len(tickers), shard_size):
            identifier = f'{market.lower().replace(" ", "-")}-{start // shard_size:04d}'
            shards[identifier] = {'market': market, 'tickers': tickers[start:start + shard_size]}
    if not shards:
        raise ValueError('No eligible securities')
    discovered_markets = sorted({row['market'] for row in discovered
                                 if str(row.get('is_new_discovery', '')).lower() in {'true', '1'}})
    plan = dict(schema=SCHEMA, cycle_id=cycle_id, asof_date=str(cutoff), provider=PROVIDER,
                expanded_discovery_markets=discovered_markets,
                planning_classification_sha256=checksum(classification.read_bytes()) if classification else None,
                provider_version=version(PROVIDER), universe_sha256=checksum(packed(listings)),
                listings=listings, discovered=discovered, discovery_sources=logs.to_dict('records'), shards=shards)
    raw_plan = packed(plan)
    target.mkdir(parents=True, exist_ok=False)
    (target / 'plan.json').write_bytes(raw_plan)
    (target / 'plan.sha256').write_text(checksum(raw_plan) + '\n')
    return plan


def load_plan(directory):
    raw = (directory / 'plan.json').read_bytes()
    digest = checksum(raw)
    if (directory / 'plan.sha256').read_text().strip() != digest:
        raise ValueError('Cycle plan checksum mismatch')
    plan = json.loads(raw)
    if (plan['schema'] != SCHEMA or plan['provider'] != PROVIDER
            or plan['universe_sha256'] != checksum(packed(plan['listings']))):
        raise ValueError('Incompatible cycle schema, provider or universe')
    plan['plan_sha256'] = digest
    return plan


def checkpoint_path(directory, shard):
    return directory / f'{shard}.sqlite'


def connect_checkpoint(path, plan, shard, *, create=False):
    spec = plan['shards'][shard]
    scope = packed({key: plan[key] for key in
                    ('schema', 'cycle_id', 'asof_date', 'universe_sha256', 'plan_sha256', 'provider', 'provider_version')})
    scope += shard.encode()
    if not create and not path.is_file():
        raise ValueError(f'Missing checkpoint: {shard}')
    if create:
        path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=30)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA trusted_schema=OFF')
    try:
        with db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('CREATE TABLE IF NOT EXISTS identity (scope TEXT PRIMARY KEY)')
            saved = db.execute('SELECT scope FROM identity').fetchall()
            if not saved and create:
                db.execute('INSERT INTO identity VALUES (?)', (checksum(scope),))
                db.execute('''CREATE TABLE work (ticker TEXT PRIMARY KEY, status TEXT NOT NULL, attempt_count INTEGER NOT NULL,
                    lease TEXT, retry_after TEXT, retrieved_at TEXT, data_date TEXT, payload TEXT, response_sha256 TEXT, error TEXT)''')
                db.execute('''CREATE TABLE attempts (ticker TEXT NOT NULL, attempt INTEGER NOT NULL, started_at TEXT NOT NULL,
                    reservation TEXT NOT NULL UNIQUE, completed_at TEXT, outcome TEXT,
                    PRIMARY KEY (ticker, attempt), FOREIGN KEY (ticker) REFERENCES work(ticker))''')
                db.executemany("INSERT INTO work VALUES (?, 'NOT_STARTED', 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL)",
                               [(ticker,) for ticker in spec['tickers']])
            elif [item[0] for item in saved] != [checksum(scope)]:
                raise ValueError(f'Incompatible checkpoint: {shard}')
        validate_checkpoint(db, spec['tickers'])
    except (sqlite3.Error, ValueError):
        db.close()
        raise
    return db


def validate_checkpoint(db, tickers):
    if [row[0] for row in db.execute('PRAGMA quick_check')] != ['ok']:
        raise ValueError('Corrupt checkpoint SQLite database')
    work = db.execute('SELECT * FROM work ORDER BY ticker').fetchall()
    if [row['ticker'] for row in work] != sorted(tickers):
        raise ValueError('Checkpoint security set mismatch')
    attempts = defaultdict(list)
    for row in db.execute('SELECT ticker, attempt FROM attempts ORDER BY ticker, attempt'):
        attempts[row['ticker']].append(row['attempt'])
    for row in work:
        if attempts.pop(row['ticker'], []) != list(range(1, row['attempt_count'] + 1)):
            raise ValueError('Checkpoint attempt history mismatch')
        if (row['status'] in READY or row['payload'] is not None) and (
                row['payload'] is None or checksum(row['payload'].encode()) != row['response_sha256']):
            raise ValueError('Checkpoint response checksum mismatch')
        if row['status'] not in TERMINAL | {'NOT_STARTED', 'IN_PROGRESS', 'RETRYABLE_FAILURE', 'BLOCKED_PROVIDER'}:
            raise ValueError('Unknown checkpoint state')
    if attempts:
        raise ValueError('Foreign checkpoint attempt history')


def claim(db, now):
    with db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute("SELECT 1 FROM work WHERE status='BLOCKED_PROVIDER' AND retry_after>? LIMIT 1",
                      (now.isoformat(),)).fetchone():
            return None
        row = db.execute("""SELECT ticker, attempt_count FROM work WHERE
            (status='NOT_STARTED' OR (status IN ('IN_PROGRESS','BLOCKED_PROVIDER','RETRYABLE_FAILURE') AND retry_after<=?))
            ORDER BY attempt_count, ticker LIMIT 1""", (now.isoformat(),)).fetchone()
        while row is not None and row['attempt_count'] >= RETRIES:
            db.execute("UPDATE work SET status='PERMANENT_FAILURE', lease=NULL, retry_after=NULL, "
                       "error=COALESCE(error,'INTERRUPTED_RETRY_LIMIT') WHERE ticker=?", (row['ticker'],))
            row = db.execute("""SELECT ticker, attempt_count FROM work WHERE
                (status='NOT_STARTED' OR (status IN ('IN_PROGRESS','BLOCKED_PROVIDER','RETRYABLE_FAILURE') AND retry_after<=?))
                ORDER BY attempt_count, ticker LIMIT 1""", (now.isoformat(),)).fetchone()
        if row is None:
            return None
        ticker, attempt = row['ticker'], row['attempt_count'] + 1
        token = secrets.token_hex(16)
        db.execute("UPDATE work SET status='IN_PROGRESS', attempt_count=?, lease=?, retry_after=? WHERE ticker=?",
                   (attempt, token, (now + timedelta(minutes=15)).isoformat(), ticker))
        db.execute('INSERT INTO attempts (ticker, attempt, started_at, reservation) VALUES (?,?,?,?)', (ticker, attempt, now.isoformat(), token))
        return ticker, attempt, token


def clean_payload(row):
    return {key: value if not isinstance(value, float) or math.isfinite(value) else None
            for key, value in row.items()}


def classify_response(payload):
    if vendor_security_type(payload) in EXCLUDED:
        return 'EXCLUDED_SECURITY_TYPE'
    metrics = [field for category in SUBMETRICS.values() for field in category]
    observed = sum(math.isfinite(number(payload.get(name))) for name in metrics)
    return 'SUCCESS' if observed >= 7 and all(
        math.isfinite(number(payload.get(name))) for name in ('operating_margin', 'roe')) else 'SUCCESS_INCOMPLETE_DATA'


def run_shard(plan, shard, directory, budget, delay, *, quota_date=None, fetch=_fetch_vendor, clock=utcnow, sleep=time.sleep):
    if not 0 <= budget <= 500 or delay < 0:
        raise ValueError('Invalid shard dispatch budget or delay')
    if plan['provider_version'] != version(PROVIDER):
        raise ValueError('Incompatible provider version; install the version pinned by the plan')
    with closing(connect_checkpoint(checkpoint_path(directory, shard), plan, shard, create=True)) as db:
        for index in range(budget):
            if index:
                sleep(delay)
            now = clock()
            if quota_date is not None and now.date() != quota_date:
                break
            reservation = claim(db, now)
            if reservation is None:
                break
            ticker, attempt, token = reservation
            timestamp = clock()
            payload = data_date = error = retry = None
            try:
                raw = clean_payload(fetch(ticker))
                status = classify_response(raw)
                data_date = raw.get('provider_financial_period_end') or None
                if data_date and date.fromisoformat(data_date) > timestamp.date():
                    status, error = 'PERMANENT_FAILURE', 'LOOKAHEAD_PROVIDER_PERIOD'
                payload = packed(raw).decode()
            except Exception as exc:
                error = type(exc).__name__
                response = getattr(exc, 'response', None)
                code = getattr(response, 'status_code', None)
                if error == 'YFRateLimitError' or code in {401, 403, 429}:
                    status = 'BLOCKED_PROVIDER'
                    retry = timestamp + timedelta(hours=24)
                elif code in {404, 410} or attempt >= RETRIES:
                    status = 'PERMANENT_FAILURE'
                else:
                    status = 'RETRYABLE_FAILURE'
                    retry = timestamp + timedelta(minutes=5 * 2 ** (attempt - 1))
            with db:
                update = db.execute('''UPDATE work SET status=?, lease=NULL, retry_after=?, retrieved_at=?, data_date=?,
                                    payload=?, response_sha256=?, error=? WHERE ticker=? AND lease=?''',
                                    (status, retry.isoformat() if retry else None, clock().isoformat() if payload else None,
                                     data_date, payload, checksum(payload.encode()) if payload else None, error, ticker, token))
                if update.rowcount != 1:
                    raise ValueError('Expired worker reservation prevented a stale write')
                db.execute('UPDATE attempts SET completed_at=?, outcome=? WHERE reservation=?',
                           (clock().isoformat(), status, token))
            if status == 'BLOCKED_PROVIDER':
                break


def summaries(plan, directory, now=None):
    now = now or utcnow()
    shards, items = {}, {}
    for shard, spec in plan['shards'].items():
        path = checkpoint_path(directory, shard)
        rows = {ticker: {'ticker': ticker, 'status': 'NOT_STARTED', 'attempt_count': 0} for ticker in spec['tickers']}
        daily = 0
        if path.is_file():
            with closing(connect_checkpoint(path, plan, shard)) as db:
                rows = {row['ticker']: dict(row) for row in db.execute('''SELECT w.*,
                        (SELECT COUNT(*) FROM attempts a WHERE a.ticker=w.ticker AND a.completed_at IS NOT NULL)
                        AS requests_completed FROM work w''')}
                daily = db.execute('SELECT COUNT(*) FROM attempts WHERE started_at LIKE ?',
                                   (now.date().isoformat() + '%',)).fetchone()[0]
        for row in rows.values():
            eligible = row['status'] == 'NOT_STARTED' or (row['status'] not in TERMINAL and
                row['attempt_count'] < RETRIES and bool(row.get('retry_after')) and row['retry_after'] <= now.isoformat())
            items[row['ticker']] = dict(row, shard=shard, market=spec['market'],
                                        retry_eligible_now=eligible, requests_completed=row.get('requests_completed', 0))
        pending = [row for row in rows.values() if row['status'] not in TERMINAL]
        runnable = [row for row in pending if row['status'] == 'NOT_STARTED' or
                    (row['retry_after'] and row['retry_after'] <= now.isoformat())]
        blocked_until = max((row['retry_after'] for row in pending if row['status'] == 'BLOCKED_PROVIDER'
                             and row['retry_after'] > now.isoformat()), default=None)
        shards[shard] = dict(market=spec['market'], scheduled=len(rows), pending=len(pending),
                             runnable=len(runnable), calls_today=daily, provider_blocked_until=blocked_until,
                             statuses=dict(Counter(r['status'] for r in rows.values())))
    return shards, items


def dispatch(plan, directory, market, max_shards, job_budget, daily_budget, reserved=0):
    if not 1 <= max_shards <= 20 or not 1 <= job_budget <= 500 or not 1 <= daily_budget <= 10000:
        raise ValueError('Configure bounded dispatch and daily budgets')
    shards, _ = summaries(plan, directory)
    if any(row['provider_blocked_until'] for row in shards.values()):
        return []
    remaining = max(0, daily_budget - max(reserved, sum(row['calls_today'] for row in shards.values())))
    jobs = []
    for shard in sorted(shards, key=lambda name: (name.rsplit('-', 1)[1], name)):
        row = shards[shard]
        count = min(row['runnable'], job_budget, remaining)
        if count and (not market or row['market'] == market):
            jobs.append({'shard': shard, 'budget': count})
            remaining -= count
        if len(jobs) >= max_shards or remaining == 0:
            break
    return jobs


def restore(plan, incoming, directory):
    """Accept immutable shard artifacts only when their histories extend local state."""
    directory.mkdir(parents=True, exist_ok=True)
    for path in sorted(incoming.rglob('*.sqlite')):
        shard = path.stem
        if shard not in plan['shards']:
            raise ValueError(f'Unknown checkpoint shard: {shard}')
        target = checkpoint_path(directory, shard)
        with closing(connect_checkpoint(path, plan, shard)) as candidate:
            if target.is_file():
                with closing(connect_checkpoint(target, plan, shard)) as existing:
                    old = dict(existing.execute('SELECT reservation, started_at FROM attempts').fetchall())
                    new = dict(candidate.execute('SELECT reservation, started_at FROM attempts').fetchall())
                    if not old.items() <= new.items() and not new.items() <= old.items():
                        raise ValueError(f'Forked shard checkpoint: {shard}')
                    if not old.items() <= new.items():
                        continue
                    old_rows = {row['ticker']: dict(row) for row in existing.execute('SELECT * FROM work')}
                    new_rows = {row['ticker']: dict(row) for row in candidate.execute('SELECT * FROM work')}
                    for ticker, row in old_rows.items():
                        updated = new_rows[ticker]
                        if row['status'] in TERMINAL and row != updated:
                            raise ValueError(f'Previously terminal checkpoint result changed: {shard}')
                    if old == new:
                        decreases = any(old_rows[t]['status'] != 'IN_PROGRESS' and new_rows[t]['status'] == 'IN_PROGRESS' for t in old_rows)
                        if decreases:
                            continue
            temporary = target.with_suffix('.restoring')
            with closing(sqlite3.connect(temporary)) as output:
                candidate.backup(output)
            temporary.replace(target)


def aggregate(plan, directory, output, universe, classification=None, evidence_options=()):
    """Apply the unchanged scoring and quality gates once to the restored batch union."""
    from .v06 import main as research_main
    shards, items = summaries(plan, directory)
    output.mkdir(parents=True, exist_ok=False)
    manifest = output / '67_v06_run_manifest.json'
    research_dir = output / 'research'
    review_asof = utcnow().date()
    registry = load_registry(classification, review_asof)
    state = {'cycle_id': plan['cycle_id'], 'cycle_start_asof': plan['asof_date'], 'report_asof': str(review_asof),
             'plan_sha256': plan['plan_sha256'], 'universe_sha256': plan['universe_sha256'],
             'provider': plan['provider'], 'provider_version': plan['provider_version'], 'shards': shards,
             'expanded_discovery_markets': plan['expanded_discovery_markets'],
             'planning_classification_sha256': plan.get('planning_classification_sha256'),
             'provider_blocked_until': max((row['provider_blocked_until'] for row in shards.values()
                                            if row['provider_blocked_until']), default=None),
             'coverage_scope': 'FROZEN_DISCOVERY_ONLY', 'universe_census_verified': False,
             'trade_orders': 'NONE'}
    rows = []
    coverage = []
    for row in plan['discovered']:
        item = items.get(row['ticker'], {'status': 'EXCLUDED_SECURITY_TYPE', 'attempt_count': 0})
        if item.get('payload') and item['status'] in READY | {'EXCLUDED_SECURITY_TYPE'}:
            if date.fromisoformat(item['retrieved_at'][:10]) > review_asof:
                raise ValueError('Checkpoint contains observations collected after report cutoff')
            row_payload = json.loads(item['payload'])
            rows.append(dict(row_payload, ticker=row['ticker'], retrieved_at_utc=item['retrieved_at']))
        identity = registry.get(row['ticker'], {})
        coverage.append({'reviewed_issuer_id': identity.get('issuer_id', '') if identity.get('reviewed') else '',
                         'reviewed_share_class': identity.get('share_class', '') if identity.get('reviewed') else '',
                         'reviewed_listing_counter': identity.get('counter', '') if identity.get('reviewed') else '',
                         **{key: row.get(key, '') for key in ('ticker', 'market', 'venue', 'exchange', 'share_class',
                                                               'listing_source_ids', 'discovery_source')},
                         **{key: value for key, value in item.items() if key not in {'payload', 'lease'}}})
    status = 'FULL_CYCLE_IN_PROGRESS' if any(row['pending'] for row in shards.values()) else (
        'PARTIAL_PROVIDER_FAILURE' if any(row['status'] in {'PERMANENT_FAILURE', 'SUCCESS_INCOMPLETE_DATA'}
                                          for row in coverage) else 'FULL_CYCLE_COMPLETE')
    if state['provider_blocked_until'] or (
            status == 'FULL_CYCLE_COMPLETE' and set(plan['expanded_discovery_markets']) != set(MARKETS)):
        status = 'BLOCKED_EXTERNAL_DEPENDENCY'
    state['run_status'] = status
    pd.DataFrame(coverage).to_csv(output / '68_cycle_security_status.csv', index=False)
    pd.DataFrame(plan['listings']).to_csv(output / '69_cycle_original_listings.csv', index=False)
    if rows:
        replay = output / '.cycle-financial-replay.csv'
        pd.DataFrame(rows).to_csv(replay, index=False)
        try:
            args = ['--universe', str(universe), '--output', str(research_dir), '--snapshot-csv', str(replay),
                    '--frozen-cycle-plan', str(output / '.cycle-plan.json'), '--discover-mode', 'off',
                    '--asof-date', str(review_asof), '--full-universe']
            if classification:
                args += ['--classification', str(classification)]
            (output / '.cycle-plan.json').write_bytes(packed(plan))
            research_main(args + list(evidence_options))
            replay_summary = json.loads((research_dir / manifest.name).read_text())
            state['bounded_research'] = replay_summary
        except Exception as exc:
            state.update(run_status='FAILED_INTERNAL_ERROR', reporting_error=type(exc).__name__)
            raise
        finally:
            replay.unlink(missing_ok=True)
            (output / '.cycle-plan.json').unlink(missing_ok=True)
            manifest.write_bytes(packed(state) + b'\n')
    else:
        (output / '66_candidate_briefs.md').write_text('No financial observations are available for research review.\n')
    attempts = pd.DataFrame(coverage)
    results = pd.read_csv(research_dir / '01_all_research_candidates.csv') if (
        research_dir / '01_all_research_candidates.csv').exists() else pd.DataFrame()
    metrics = {}
    for market in MARKETS:
        subset = attempts[attempts.market.eq(market)]
        scored = results[results.market.eq(market)] if not results.empty else results
        metrics[market] = {'discovered': len(subset), 'eligible': int(subset.ticker.isin(items).sum()),
                           'scheduled': int(subset.ticker.isin(items).sum()),
                           'provider_attempts': int(subset.attempt_count.sum()),
                           'provider_requests_finished': int(subset.requests_completed.fillna(0).sum()),
                           'retrieved': int(subset.status.isin(READY).sum()), 'sufficient': int(subset.status.eq('SUCCESS').sum()),
                           'scored': int(scored.cross_industry_score_100.notna().sum()) if not scored.empty else 0,
                           'screened': int(scored.v031_research_eligible.sum()) if not scored.empty else 0,
                           'failed_or_pending': int((~subset.status.isin(READY | {'EXCLUDED_SECURITY_TYPE'})).sum())}
    state['market_coverage'] = metrics
    manifest.write_bytes(packed(state) + b'\n')


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=('freeze', 'dispatch', 'work', 'restore', 'aggregate'))
    parser.add_argument('--plan', required=True, type=Path)
    parser.add_argument('--state', type=Path, default=Path('cycle-state'))
    parser.add_argument('--input', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cycle-id')
    parser.add_argument('--shard-size', type=int, default=100)
    parser.add_argument('--market', choices=MARKETS)
    parser.add_argument('--max-shards', type=int, default=1)
    parser.add_argument('--budget', type=int, default=25)
    parser.add_argument('--daily-budget', type=int, default=25)
    parser.add_argument('--shard')
    parser.add_argument('--delay', type=float, default=2)
    parser.add_argument('--reserved', type=int, default=0)
    parser.add_argument('--quota-date', type=date.fromisoformat)
    parser.add_argument('--universe', type=Path, default=Path('data/universe.csv'))
    parser.add_argument('--classification', type=Path)
    # Only these options are forwarded. The input snapshot, market scope, and
    # report cutoff remain owned by the cycle.
    path_flags = ('official-filing-requests', 'opendart-requests', 'vendor-export', 'approved-sources',
                  'source-dir', 'gemini-cache')
    integer_flags = ('filing-budget', 'max-documents', 'max-requests',
                     'gemini-total-input-budget', 'gemini-total-output-budget')
    boolean_flags = ('enable-gemini', 'gemini-approved-only')
    for flag in path_flags:
        parser.add_argument('--' + flag, type=Path)
    for flag in integer_flags:
        parser.add_argument('--' + flag, type=int)
    for flag in boolean_flags:
        parser.add_argument('--' + flag, action='store_true')
    args = parser.parse_args()
    if args.mode == 'freeze':
        freeze(args.input, args.plan, args.cycle_id, args.shard_size, classification=args.classification)
        return
    plan = load_plan(args.plan)
    if args.mode == 'dispatch':
        print(json.dumps(dispatch(plan, args.state, args.market, args.max_shards, args.budget, args.daily_budget, args.reserved)))
    elif args.mode == 'work':
        if args.delay < 1:
            parser.error('Live workers need a delay of at least one second')
        run_shard(plan, args.shard, args.state, args.budget, args.delay, quota_date=args.quota_date)
    elif args.mode == 'restore':
        restore(plan, args.input, args.state)
    elif args.mode == 'aggregate':
        evidence = []
        for flag in (*path_flags, *integer_flags):
            value = getattr(args, flag.replace('-', '_'))
            if value is not None:
                evidence.extend(('--' + flag, str(value)))
        evidence.extend('--' + flag for flag in boolean_flags if getattr(args, flag.replace('-', '_')))
        aggregate(plan, args.state, args.output, args.universe, args.classification, evidence)


if __name__ == '__main__':
    main()
