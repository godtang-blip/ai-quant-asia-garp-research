"""Bounded campaign progression over the existing frozen financial cycle."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta
import json
import math
import os
from pathlib import Path
import re
import time
import unicodedata

import pandas as pd

from . import research_cycle as cycle
from .industry_classification import (AMBIGUOUS_VENDOR_LABELS, CAMPAIGN_LABELS, EXCHANGE_LABELS, EXCLUDED,
                                     campaign_classify, classify, listing_instrument, load_registry)
from .official_universe import source_jpx_list
from .research_dossier import records


REPORT = '74_campaign_manifest.json'
EXCHANGE_EVIDENCE = '79_campaign_exchange_evidence.json'
SCHEMA = 1
TRANSPORT_LIMIT = 8
REDIRECT_LIMIT = 2
WORKING = Path('cycle-working')
LEASE = Path('cycle-campaign/lease.json')
OUTPUT = Path('cycle-report')
REUSABLE = {'CONTINUE_READY', 'PAUSED'}


class FinancialTransportLimit(Exception):
    pass


class FinancialRateLimit(Exception):
    status_code = 429


class FinancialAuthenticationFailure(Exception):
    status_code = 403


def bounded_vendor(session, fetch, transport_counts, deadline, clock):
    """Bound the pinned provider's existing session, including its internal retries."""
    request = session.request
    curl = type(session).__module__.startswith('curl_cffi.')
    session.max_redirects = REDIRECT_LIMIT

    def lookup(ticker):
        calls = 0
        last_status = None
        rate_limited = False

        def bounded_request(method, url, *args, **kwargs):
            nonlocal calls, last_status, rate_limited
            if rate_limited:
                raise FinancialRateLimit()
            remaining = (deadline - clock()).total_seconds()
            if calls >= TRANSPORT_LIMIT or remaining <= 0:
                raise FinancialTransportLimit()
            calls += 1
            kwargs['timeout'] = min(20, remaining)
            if curl:
                kwargs['max_redirects'] = REDIRECT_LIMIT
            response = request(method, url, *args, **kwargs)
            last_status = response.status_code
            if last_status == 429:
                rate_limited = True
                raise FinancialRateLimit()
            return response

        session.request = bounded_request
        try:
            result = fetch(ticker, session=session)
            if rate_limited:
                raise FinancialRateLimit()
            return result
        except Exception:
            if rate_limited:
                raise FinancialRateLimit() from None
            if last_status in {401, 403}:
                raise FinancialAuthenticationFailure() from None
            raise
        finally:
            transport_counts[ticker] = calls
            session.request = request

    return lookup


def verify_handoff(plan, state, published, now):
    if published['plan_sha256'] != plan['plan_sha256'] or published['cycle_id'] != plan['cycle_id']:
        raise ValueError('Batch report does not match the frozen plan')
    minimum = 200 if plan['cycle_id'] == '44456766424' else 1
    totals = sum(row['provider_attempts'] for row in published['market_coverage'].values())
    _, items = cycle.summaries(plan, state, now)
    if totals < minimum or sum(row['attempt_count'] for row in items.values()) < totals:
        raise ValueError('The restored checkpoint does not contain the completed cumulative financial Batch')


def exchange_metadata(plan, now, fetch=source_jpx_list):
    # The workbook is industry evidence only. Match existing official listing
    # identities; its security population never participates in scheduling.
    def identity(name):
        return ''.join(unicodedata.normalize('NFKC', name).casefold().split())

    names = {}
    for row in plan['listings']:
        source = row.get('discovery_source', '')
        if row['market'] == 'Japan' and source.startswith('https://www.jpx.co.jp/'):
            names.setdefault(row['ticker'], set()).add(identity(row['company']))
    if not names:
        return {'status': 'NO_FROZEN_JPX_ISSUER_IDENTITIES', 'rows': {}}
    try:
        current = fetch(include_industries=True)
    except ValueError:
        return {'status': 'JPX_INDUSTRY_WORKBOOK_UNAVAILABLE', 'rows': {}}
    rows = {}
    for row in current:
        if (names.get(row['ticker']) != {identity(row['company'])} or not row.get('exchange_industry')
                or row.get('listing_source_date', '') > now.date().isoformat()):
            continue
        rows[row['ticker']] = {field: row[field] for field in (
            'exchange_industry', 'listing_source_url', 'listing_source_date')}
    return {'status': 'MATCHED_FROZEN_ISSUERS' if rows else 'NO_VERIFIED_ISSUER_MATCHES',
            'retrieved_at': now.isoformat(), 'rows': rows}


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def number_setting(name, default, low, high):
    raw = os.environ.get(name) or str(default)
    if not re.fullmatch(r'[0-9]{1,8}', raw) or not low <= int(raw) <= high:
        raise ValueError(f'{name} must be between {low} and {high}')
    return int(raw)


def config_from_environment(mode):
    full = mode == 'full-sweep'
    configuration = dict(
        mode=mode,
        per_run=number_setting('GARP_CYCLE_JOB_BUDGET', 5, 1, 100),
        daily=number_setting('GARP_CYCLE_DAILY_BUDGET', 0, 1, 10000),
        total=number_setting('GARP_CAMPAIGN_TOTAL_BUDGET', 0 if full else 10, 1, 75000),
        max_runs=number_setting('GARP_CAMPAIGN_MAX_RUNS', 500 if full else 12, 1, 500),
        max_hours=number_setting('GARP_CAMPAIGN_MAX_HOURS', 2160 if full else 48, 1, 2160),
        delay=number_setting('GARP_CYCLE_REQUEST_DELAY', 2, 1, 30),
        report_limit=number_setting('GARP_REPORT_LIMIT', 3, 1, 5),
        filing_budget=number_setting('GARP_FILING_BUDGET', 0, 0, 5),
        max_documents=number_setting('GARP_MAX_DOCS', 1, 1, 3),
        max_requests=number_setting('GARP_MAX_CALLS', 2, 1, 9),
        input_budget=number_setting('GARP_GEMINI_TOTAL_INPUT_BUDGET', 250000, 1, 250000),
        output_budget=number_setting('GARP_GEMINI_TOTAL_OUTPUT_BUDGET', 9216, 1, 9216),
        gemini=os.environ.get('GARP_ENABLE_MODEL') == 'true',
        classification=os.environ.get('GARP_CLASSIFICATION', ''),
    )
    for name in ('GARP_GEMINI_MODEL', 'GARP_GEMINI_INPUT_PRICE', 'GARP_GEMINI_OUTPUT_PRICE',
                 'GARP_GEMINI_MAX_COST_USD', 'GARP_GEMINI_TIMEOUT_SECONDS',
                 'GARP_GEMINI_DIAGNOSTIC_CANARY', 'GARP_EDINET_INDEX_DATES'):
        configuration[name] = os.environ.get(name, '')
    if configuration['gemini']:
        if not configuration['filing_budget'] or not configuration['GARP_GEMINI_MODEL']:
            raise ValueError('Gemini requires a filing budget and an explicit GARP_GEMINI_MODEL')
        for name in ('GARP_GEMINI_INPUT_PRICE', 'GARP_GEMINI_OUTPUT_PRICE', 'GARP_GEMINI_MAX_COST_USD'):
            try:
                value = float(configuration[name])
            except ValueError:
                value = float('nan')
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f'Set a positive finite {name} for Gemini')
        if configuration['GARP_GEMINI_DIAGNOSTIC_CANARY'] == '1' and configuration['max_requests'] < 3:
            raise ValueError('Gemini canaries plus extraction require at least three generation requests')
    return configuration


def classification_path(config):
    if not config['classification']:
        return None
    path = Path(config['classification']).resolve(strict=True)
    if not path.is_relative_to(Path.cwd()) or path.suffix != '.csv' or not path.is_file():
        raise ValueError('Campaign classification must be a CSV in the checked-out repository')
    return path


def scheduling_metadata(plan, registry, exchange=None):
    exclusions, groups = {}, {}
    for row in plan['listings']:
        ticker = row['ticker'].strip().upper()
        exclusion = listing_instrument(row)
        if exclusion:
            exclusions[ticker] = exclusion
    for row in plan['discovered']:
        ticker = row['ticker']
        evidence = registry.get(ticker, {})
        if evidence.get('reviewed') and evidence['security_type'] in EXCLUDED:
            exclusions[ticker] = evidence['security_type']
        listing_group = row.get('peer_group') or 'unclassified'
        exchange_group = EXCHANGE_LABELS.get((exchange or {}).get(ticker, {}).get('exchange_industry'))
        groups[ticker] = ((evidence.get('peer_group') if evidence.get('reviewed') else None)
                          or (listing_group if listing_group != 'unclassified' else exchange_group)
                          or 'unclassified')
    return exclusions, groups


def pending_reason(item):
    if item['status'] in cycle.TERMINAL:
        return None
    if item['attempt_count'] >= cycle.RETRIES:
        return 'RETRY_LIMIT_REACHED'
    return item['status']


def schedule(plan, items, exclusions, groups, previous, budget):
    """Preserve shard membership while stratifying security priority across markets."""
    available = {}
    for ticker, item in items.items():
        if ticker in exclusions or not item['retry_eligible_now']:
            continue
        market = item['market']
        group = groups[ticker]
        priority = cycle.checksum(f"{plan['universe_sha256']}:{ticker}".encode())
        available.setdefault((market, group), []).append((item['attempt_count'], priority, ticker))
    for bucket in available.values():
        bucket.sort(reverse=True)
    market_counts = Counter(previous.get('market_reservations', {}))
    industry_counts = Counter(previous.get('industry_reservations', {}))
    market_order = {market: cycle.checksum(f"{plan['plan_sha256']}:{market}".encode()) for market in cycle.MARKETS}
    jobs = []
    while available and len(jobs) < budget:
        market, group = min(available, key=lambda key: (
            market_counts[key[0]], market_order[key[0]], available[key][-1][0],
            key[1] == 'unclassified', industry_counts[key[1]], available[key][-1][1]))
        count, _, ticker = available[market, group].pop()
        if not available[market, group]:
            del available[market, group]
        jobs.append(dict(ticker=ticker, shard=items[ticker]['shard'], attempt=count + 1, market=market,
                         planning_peer_group=group))
        market_counts[market] += 1
        industry_counts[group] += 1
    return jobs, dict(market_counts), dict(industry_counts)


def eligibility(shards, items, exclusions):
    pending = [item for ticker, item in items.items() if ticker not in exclusions and
               pending_reason(item) not in {None, 'RETRY_LIMIT_REACHED'}]
    provider_wait = max((row['provider_blocked_until'] for row in shards.values()
                         if row['provider_blocked_until']), default=None)
    return pending, provider_wait


def prepare(plan, state, run, revision, ref, mode, handoff, *, previous=None, previous_lease=None,
            config=None, reserved_today=0, control='', now=None, exchange=None, recover=False):
    now = now or cycle.utcnow()
    if control not in {'', 'run', 'pause', 'cancel'}:
        raise ValueError('GARP_CAMPAIGN_CONTROL must be empty, run, pause or cancel')
    uncertain, evidence_uncertain = {}, False
    promote = (mode == 'full-sweep' and previous and previous_lease and previous['status'] in {'COMPLETE', 'EXHAUSTED'}
               and previous_lease['configuration']['mode'] == 'research-now')
    if previous_lease:
        if not promote and (mode not in {'continue', 'resume'} or (recover and mode != 'resume') or
                (not recover and (not previous or previous['status'] not in REUSABLE or
                 (mode == 'continue' and previous['status'] != 'CONTINUE_READY')))):
            raise ValueError('Campaign is not ready for this continuation')
        if (previous_lease.get('schema') != SCHEMA or
                (previous and previous['lease_sha256'] != cycle.checksum(cycle.packed(previous_lease))) or
                previous_lease['run_id'] != handoff or
                any(previous_lease[key] != value for key, value in (
                    ('revision', revision), ('ref', ref), ('plan_sha256', plan['plan_sha256']),
                    ('cycle_id', plan['cycle_id'])))):
            raise ValueError('Prior campaign lease, revision or frozen cycle mismatch')
        prior = previous_lease
        if recover and prior['status'] == 'CANCELLED':
            control = 'cancel'
        config = config if promote else prior['configuration']
        current_day_cap = number_setting('GARP_CYCLE_DAILY_BUDGET', config['daily'], 1, 10000)
        day_cap = min(config['daily'], current_day_cap)
        started = now if promote else datetime.fromisoformat(prior['started'])
        round_number = 1 if promote else prior['round'] + 1
        campaign_id = run if promote else prior['campaign_id']
        handoff = prior['batch_run_id']
        campaign_reserved = 0 if promote else prior['financial_reserved_total']
        evidence_run = previous.get('evidence_run_id') if previous else prior['evidence_run_id']
        uncertain = dict(prior.get('uncertain_attempts', {}))
        evidence_uncertain = prior.get('evidence_uncertain', False) or (recover and not evidence_run)
    else:
        prior = {}
        started, round_number, campaign_id = now, 1, run
        campaign_reserved, evidence_run = 0, None
        day_cap = config['daily']
    shards, items = cycle.summaries(plan, state, now)
    # A continuation must still contain the previous wave's checkpoint work.
    attempt_total = sum(row['attempt_count'] for row in items.values())
    if previous_lease and (previous['checkpoint_attempts_after'] if previous else
                           prior['checkpoint_attempts_before']) > attempt_total:
        raise ValueError('Restored cycle is behind the previous campaign checkpoint')
    if recover:
        for job in prior['jobs']:
            item = items[job['ticker']]
            if item['attempt_count'] < job['attempt'] or item['status'] == 'IN_PROGRESS':
                uncertain[job['ticker']] = job['attempt']
    registry = load_registry(classification_path(config), now.date())
    exclusions, groups = scheduling_metadata(plan, registry, exchange)
    skipped = exclusions.keys() | uncertain.keys()
    pending, provider_wait = eligibility(shards, items, skipped)
    day_used = max(reserved_today, sum(row['calls_today'] for row in shards.values()))
    capacity = max(0, min(config['per_run'], config['total'] - campaign_reserved, day_cap - day_used))
    status, reason = 'RUNNING', ''
    if control == 'cancel':
        status, reason = 'CANCELLED', 'OPERATOR_CANCELLED'
    elif control == 'pause':
        status, reason = 'PAUSED', 'OPERATOR_PAUSED'
    elif now >= started + timedelta(hours=config['max_hours']) or round_number > config['max_runs']:
        status, reason = 'EXHAUSTED', 'CAMPAIGN_RUNTIME_OR_ROUND_LIMIT'
    elif provider_wait:
        status, reason = 'PAUSED', 'FINANCIAL_PROVIDER_RATE_LIMIT_OR_AUTH'
    elif pending and not capacity and campaign_reserved < config['total']:
        status, reason = 'PAUSED', 'DAILY_FINANCIAL_BUDGET'
    jobs, markets, industries = schedule(plan, items, skipped, groups, prior, capacity if status == 'RUNNING' else 0)
    at_target = campaign_reserved + len(jobs) >= config['total']
    # Research-now samples its bounded allocation first. Full-sweep uses the first eligible
    # shortlist and carries that evidence forward without sending the same documents again.
    evidence_allowed = (status == 'RUNNING' and not evidence_run and not evidence_uncertain and
                        (config['mode'] == 'full-sweep' or at_target or not pending
                         or round_number == config['max_runs']))
    return dict(
        schema=SCHEMA, cycle_id=plan['cycle_id'], plan_sha256=plan['plan_sha256'], universe_sha256=plan['universe_sha256'],
        provider_version=plan['provider_version'], batch_run_id=handoff, campaign_id=campaign_id,
        run_id=run, revision=revision, ref=ref, started=started.isoformat(), round=round_number,
        configuration=config, status=status, reason=reason, quota_date=now.date().isoformat(),
        reserved_before_today=day_used, daily_cap=day_cap,
        jobs=jobs, financial_reserved_total=campaign_reserved + len(jobs), evidence_allowed=evidence_allowed,
        market_reservations=markets, industry_reservations=industries, evidence_run_id=evidence_run,
        uncertain_attempts=uncertain, evidence_uncertain=evidence_uncertain,
        checkpoint_attempts_before=attempt_total,
    )


def collect(plan, state, lease, *, clock=cycle.utcnow, sleep=time.sleep, fetch=None):
    start = clock()
    cutoff = min(start + timedelta(minutes=20),
                 datetime.fromisoformat(lease['started']) + timedelta(hours=lease['configuration']['max_hours']))
    transport = {}
    if fetch is None and lease['jobs']:
        from yfinance import data
        if hasattr(data, 'new_session'):
            session = data.new_session()
        else:
            options = {'impersonate': 'chrome'} if data.requests.__name__ == 'curl_cffi.requests' else {}
            session = data.requests.Session(**options)
        with session:
            worker = bounded_vendor(session, cycle._fetch_vendor, transport, cutoff, clock)
            return collect_wave(plan, state, lease, worker, transport, cutoff, clock, sleep)
    return collect_wave(plan, state, lease, fetch, transport, cutoff, clock, sleep)


def collect_wave(plan, state, lease, fetch, transport, cutoff, clock, sleep):
    quota_date = date.fromisoformat(lease['quota_date'])
    outcomes = []
    reason = ''
    for job in lease['jobs']:
        if outcomes:
            sleep(lease['configuration']['delay'])
        if clock() >= cutoff or clock().date() != quota_date:
            reason = 'FINANCIAL_WINDOW_ENDED'
            break
        status = cycle.run_shard(
            plan, job['shard'], state, 1, 0, quota_date=quota_date, selected_ticker=job['ticker'],
            expected_attempt=job['attempt'], clock=clock, **({'fetch': fetch} if fetch else {}))
        if not status:
            reason = 'RESERVATION_CHANGED_BEFORE_CALL'
            break
        outcomes.append({**job, 'outcome': status, 'transport_operations': transport.get(job['ticker'])})
        if status == 'BLOCKED_PROVIDER':
            reason = 'FINANCIAL_PROVIDER_RATE_LIMIT_OR_AUTH'
            break
    return {'outcomes': outcomes, 'stop_reason': reason}


def evidence_args(lease, root, *, active):
    config = lease['configuration']
    flags = ['--campaign-shortlist', '--report-limit', str(config['report_limit'])]
    if not active:
        return flags
    flags += ['--research-dossier', '--prepare-filing-inputs', '--filing-budget', str(config['filing_budget']),
              '--source-dir', str(root / 'originals')]
    for key in config:
        if key.startswith(('GARP_GEMINI_', 'GARP_EDINET_')):
            os.environ[key] = config[key]
    if config['gemini']:
        flags.extend(['--enable-gemini', '--gemini-cache', str(root / 'gemini.sqlite'),
                      '--max-documents', str(config['max_documents']), '--max-requests', str(config['max_requests']),
                      '--gemini-total-input-budget', str(config['input_budget']),
                      '--gemini-total-output-budget', str(config['output_budget']),
                      '--gemini-input-price', config['GARP_GEMINI_INPUT_PRICE'],
                      '--gemini-output-price', config['GARP_GEMINI_OUTPUT_PRICE'],
                      '--gemini-max-cost-usd', config['GARP_GEMINI_MAX_COST_USD']])
    return flags


def next_status(lease, progress, pending, provider_wait, now):
    if lease['status'] != 'RUNNING':
        return lease['status'], lease['reason']
    stop_reason = progress['stop_reason']
    if provider_wait or stop_reason == 'FINANCIAL_PROVIDER_RATE_LIMIT_OR_AUTH':
        return 'PAUSED', 'FINANCIAL_PROVIDER_RATE_LIMIT_OR_AUTH'
    if not pending:
        return 'COMPLETE', 'ELIGIBLE_FINANCIAL_SCOPE_TERMINAL_OR_EXPLICITLY_BLOCKED'
    config = lease['configuration']
    if lease['financial_reserved_total'] >= config['total']:
        return ('COMPLETE', 'RESEARCH_NOW_SAMPLE_LIMIT') if config['mode'] == 'research-now' else (
            'EXHAUSTED', 'TOTAL_FINANCIAL_BUDGET')
    if (lease['round'] >= config['max_runs'] or
            now >= datetime.fromisoformat(lease['started']) + timedelta(hours=config['max_hours'])):
        return 'EXHAUSTED', 'CAMPAIGN_RUNTIME_OR_ROUND_LIMIT'
    if stop_reason == 'RESERVATION_CHANGED_BEFORE_CALL':
        return 'PAUSED', stop_reason
    if now.date().isoformat() == lease['quota_date'] and (
            lease['reserved_before_today'] + len(lease['jobs']) >= lease['daily_cap']):
        return 'PAUSED', 'DAILY_FINANCIAL_BUDGET'
    if not any(row['retry_eligible_now'] for row in pending):
        return 'PAUSED', 'FINANCIAL_RETRY_BACKOFF'
    return 'CONTINUE_READY', 'NEXT_BOUNDED_WAVE'


def publish_report(plan, state, lease, progress, output, private, universe, *, now=None, parent_report=None):
    now = now or cycle.utcnow()
    config = lease['configuration']
    registry_path = classification_path(config)
    registry = load_registry(registry_path, now.date())
    exclusions, _ = scheduling_metadata(plan, registry)
    shards, items = cycle.summaries(plan, state, now)
    uncertain = lease['uncertain_attempts']
    pending, provider_wait = eligibility(shards, items, exclusions.keys() | uncertain.keys())
    status, reason = next_status(lease, progress, pending, provider_wait, now)
    run_evidence = (not lease['evidence_run_id'] and not lease['evidence_uncertain'] and lease['status'] == 'RUNNING' and
                    (lease['evidence_allowed'] or status in {'COMPLETE', 'EXHAUSTED'}) and
                    reason != 'FINANCIAL_PROVIDER_RATE_LIMIT_OR_AUTH')
    flags = evidence_args(lease, private, active=run_evidence)
    parent_metadata = parent_report / EXCHANGE_EVIDENCE if parent_report else None
    metadata = read(parent_metadata) if parent_metadata and parent_metadata.is_file() else (
        exchange_metadata(plan, now) if lease['status'] == 'RUNNING' and not lease['evidence_uncertain'] and
        reason != 'FINANCIAL_PROVIDER_RATE_LIMIT_OR_AUTH' else None)
    snapshot = private / EXCHANGE_EVIDENCE
    write(snapshot, {'rows': metadata['rows'] if metadata else {}, 'exclusions': exclusions})
    flags += ['--campaign-exchange-evidence', str(snapshot)]
    cycle.aggregate(plan, state, output, universe, registry_path, flags)
    if metadata:
        write(output / EXCHANGE_EVIDENCE, metadata)
    research = output / 'research'
    division = {row['ticker']: row for row in records(research, '70_industry_classification_audit_v1.csv')}
    ranked = {row['ticker']: row for row in records(research, '01_all_research_candidates.csv')}
    review = {row['ticker']: row.get('review_reasons', '') for row in records(research, '64_exclusion_audit.csv')}
    shortlist = records(research, '73_campaign_preliminary_shortlist.csv')
    shortlisted = {row['ticker'] for row in shortlist}
    dossiers = research / '71_research_dossiers' / 'index.json'
    research_manifest = research / '67_v06_run_manifest.json'
    evidence = read(research_manifest) if research_manifest.is_file() else {}
    evidence_run = lease['evidence_run_id'] or (lease['run_id'] if run_evidence and shortlist else None)
    ticker_rows = []
    markets = {market: Counter() for market in cycle.MARKETS}
    confidence = {market: {'discovered': Counter(), 'scored': Counter(), 'shortlisted': Counter()} for market in cycle.MARKETS}
    industries = Counter()
    for listing in plan['discovered']:
        ticker, market = listing['ticker'], listing['market']
        item = items.get(ticker, {})
        classification = division.get(ticker)
        if classification is None:
            raw = {**listing, **((metadata or {}).get('rows', {}).get(ticker) or {})}
            classification = campaign_classify(raw, classify(raw, registry.get(ticker)), registry.get(ticker), '')
        score = ranked.get(ticker, {})
        attempts = item.get('attempt_count', 0)
        excluded = ticker in exclusions or not item or item['status'] == 'EXCLUDED_SECURITY_TYPE'
        instrument = exclusions.get(ticker, classification.get('instrument_class', ''))
        label = 'EXCLUDED_INSTRUMENT' if excluded else classification.get('industry_confidence', 'UNRESOLVED')
        group = 'unclassified' if excluded else classification.get('operating_peer_group', 'unclassified')
        financial_status = item.get('status', 'EXCLUDED_SECURITY_TYPE')
        campaign_status = 'EXCLUDED_SECURITY_TYPE' if excluded else (
            'BLOCKED_UNCERTAIN_PREVIOUS_ATTEMPT' if ticker in uncertain and financial_status not in cycle.TERMINAL else
            'BLOCKED_RETRY_LIMIT' if pending_reason(item) == 'RETRY_LIMIT_REACHED' else financial_status)
        scored = bool(score.get('cross_industry_score_100'))
        period = item.get('data_date') or ''
        period_status = ('STALE_OVER_185_DAYS' if (now.date() - date.fromisoformat(period)).days > 185
                         else 'PERIOD_REPORTED') if period else 'PERIOD_UNKNOWN'
        screen_pass = score.get('v031_research_eligible', '').lower() in {'true', '1'}
        candidate_reason = review.get(ticker) or score.get('v031_research_status', '') or campaign_status
        if label in {'CONFLICTED', 'UNRESOLVED'} and attempts:
            candidate_reason += '|INDUSTRY_' + label
        market_data = markets[market]
        market_data.update(discovered=1, attempted=int(bool(attempts)), requests=attempts,
                           stored_responses=int(bool(item.get('payload'))), scored=int(scored),
                           screened=int(screen_pass), shortlisted=int(ticker in shortlisted),
                           rejected=int(campaign_status in {'EXCLUDED_SECURITY_TYPE', 'PERMANENT_FAILURE'} or
                                        (financial_status in cycle.READY and not screen_pass)),
                           blocked=int(campaign_status.startswith('BLOCKED_')),
                           pending=int(not excluded and ticker not in uncertain and
                                       pending_reason(item) not in {None, 'RETRY_LIMIT_REACHED'}),
                           industry_flagged_scored=int(scored and label in {'CONFLICTED', 'UNRESOLVED'}),
                           industry_review_required_scored=int(scored and label != 'HUMAN_REVIEWED'))
        confidence[market]['discovered'][label] += 1
        if scored:
            confidence[market]['scored'][label] += 1
        if ticker in shortlisted:
            confidence[market]['shortlisted'][label] += 1
        industries[group] += attempts
        ticker_rows.append({**classification, 'ticker': ticker, 'market': market, 'company': listing['company'],
                            'exchange': listing.get('exchange') or listing.get('venue') or '',
                            'instrument_class': instrument, 'industry_confidence': label,
                            'operating_peer_group': group, 'financial_status': financial_status,
                            'campaign_financial_status': campaign_status,
                            'provider_error': item.get('error') or '', 'attempts': attempts, 'data_date': period,
                            'financial_period_status': period_status, 'selected': ticker in shortlisted,
                            'candidate_exclusion_or_review': candidate_reason if not excluded else
                            'EXCLUDED_SECURITY_TYPE', 'frozen_listing_source': listing.get('discovery_source', '')})
    pd.DataFrame(ticker_rows).to_csv(output / '75_campaign_security_audit.csv', index=False)
    pd.DataFrame([dict(source='VENDOR', original_label=label, peer_group=group) for label, group in CAMPAIGN_LABELS.items()] +
                 [dict(source='OFFICIAL_EXCHANGE_LABEL', original_label=label, peer_group=group)
                  for label, group in EXCHANGE_LABELS.items()] +
                 [dict(source='VENDOR_BROAD_REQUIRES_CORROBORATION', original_label=label, peer_group='unclassified')
                  for label in sorted(AMBIGUOUS_VENDOR_LABELS)]).to_csv(
                      output / '76_campaign_industry_mapping.csv', index=False)
    pd.DataFrame(progress['outcomes'], columns=['ticker', 'shard', 'attempt', 'market', 'planning_peer_group',
                                                 'outcome', 'transport_operations']).to_csv(
                                                     output / '77_campaign_wave.csv', index=False)
    previous_manifest = parent_report / REPORT if parent_report else None
    current_evidence = {'filing_attempts': evidence.get('filing_attempts', []),
                        'outcomes': evidence.get('outcomes', {}),
                        'gemini': evidence.get('gemini', {}),
                        'dossiers': read(dossiers) if dossiers.is_file() else {}}
    retained_evidence = (read(previous_manifest)['research_evidence']
                         if lease['evidence_run_id'] and previous_manifest and previous_manifest.is_file()
                         else current_evidence)
    manifest = dict(cycle_id=plan['cycle_id'], campaign_id=lease['campaign_id'], run_id=lease['run_id'],
                    handoff_batch_run_id=lease['batch_run_id'], revision=lease['revision'], round=lease['round'],
                    status=status, reason=reason, provider_blocked_until=provider_wait,
                    configuration=config, market_coverage=markets, industry_confidence_by_market=confidence,
                    finance_attempts_by_industry=industries, lease_sha256=cycle.checksum(cycle.packed(lease)),
                    financial_reserved_total=lease['financial_reserved_total'], reserved_this_wave=len(lease['jobs']),
                    limits={'parallel_financial_workers': 1, 'financial_attempts_per_ticker': cycle.RETRIES,
                            'transport_operations_per_attempt': TRANSPORT_LIMIT, 'redirects_per_operation': REDIRECT_LIMIT,
                            'max_financial_transport_operations_this_wave': len(lease['jobs']) * TRANSPORT_LIMIT},
                    financial_transport_operations_this_wave=sum(row.get('transport_operations') or 0
                                                                 for row in progress['outcomes']),
                    checkpoint_attempts_before=lease['checkpoint_attempts_before'],
                    checkpoint_attempts_after=sum(row['attempt_count'] for row in items.values()),
                    exchange_industry_evidence={'status': metadata['status'], 'matched': len(metadata['rows'])}
                    if metadata else {'status': 'NOT_ATTEMPTED'},
                    evidence_run_id=evidence_run, screening_thresholds={'minimum_metric_coverage': .70,
                    'profitable_operating_margin_and_roe': True, 'known_peer_group': True, 'clean_screening_flags': True},
                    research_evidence=retained_evidence,
                    financial_input_provenance=evidence.get('financial_input_provenance', {}),
                    evidence_uncertain=lease['evidence_uncertain'],
                    blocked_uncertain_provider_attempts=uncertain,
                    human_responsibility='Final thesis, valuation assumptions and investment conclusions')
    write(output / REPORT, manifest)
    lines = ['# Asia GARP campaign', '', f'Cycle {plan["cycle_id"]}, wave {lease["round"]}. {status} ({reason}).',
             '', '| Market | Discovered | Attempted | Scored | Screened | Blocked | Pending |',
             '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
             *[f'| {market} | ' + ' | '.join(str(count[key]) for key in
               ('discovered', 'attempted', 'scored', 'screened', 'blocked', 'pending')) + ' |'
               for market, count in markets.items()], '',
             'The denominator is the frozen discovery population. Financial attempts and scored coverage are tracked separately.',
             '', '## Industry and screening',
             '', 'The security audit records confidence, unresolved conflicts, source labels, applied weights and valuation anchors, '
             'and rank and eligibility under the original and campaign classifications.',
             '', '| Scope | Human reviewed | Automated | Provisional | Conflicted | Unresolved |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for scope in ('discovered', 'scored', 'shortlisted'):
        counts = sum((entry[scope] for entry in confidence.values()), Counter())
        lines.append(f'| {scope} | ' + ' | '.join(str(counts[key]) for key in
                     ('HUMAN_REVIEWED', 'AUTO_CLASSIFIED', 'PROVISIONAL', 'CONFLICTED', 'UNRESOLVED')) + ' |')
    lines.extend(['', '## Preliminary shortlist', '',
                  *[f'- {row["ticker"]} ({row["market"]}, {row["peer_group"]}). Screen rank '
                    f'{row["original_screen_rank"]}. Industry confidence {row["industry_confidence"]}.'
                    for row in shortlist], '',
                  f'Evidence run {evidence_run or "pending or unavailable"}.',
                  f'Gemini extraction responses this wave {evidence.get("gemini", {}).get("extraction_responses_received", 0)}.',
                  'The analyst owns the final thesis, valuation assumptions and investment research report.'])
    (output / '74_campaign_summary.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['prepare', 'collect', 'report'])
    args = parser.parse_args()
    plan = cycle.load_plan(WORKING / 'plan')
    state = WORKING / 'state'
    if args.stage == 'prepare':
        mode = os.environ['GARP_CAMPAIGN_MODE']
        parent = Path('campaign-parent')
        restored = parent.is_dir()
        parent_exchange = parent / 'report' / EXCHANGE_EVIDENCE
        if not restored:
            verify_handoff(plan, state, read(Path('campaign-batch-report/67_v06_run_manifest.json')), cycle.utcnow())
        lease = prepare(plan, state, os.environ['GITHUB_RUN_ID'], os.environ['GITHUB_SHA'], os.environ['GITHUB_REF_NAME'],
                        mode, os.environ['GARP_CAMPAIGN_CHECKPOINT'],
                        previous=read(parent / REPORT) if (parent / REPORT).is_file() else None,
                        previous_lease=read(parent / 'lease.json') if restored else None,
                        config=config_from_environment(mode) if not restored or mode == 'full-sweep' else None,
                        reserved_today=int(os.environ['GARP_CYCLE_RESERVED_TODAY']),
                        control=os.environ.get('GARP_CAMPAIGN_CONTROL', ''),
                        exchange=read(parent_exchange)['rows'] if parent_exchange.is_file() else None,
                        recover=(parent / 'recover').is_file())
        write(LEASE, lease)
        write(Path('cycle-quota.json'), {'items': lease['jobs'], 'date': lease['quota_date']})
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
            stream.write(f"reserved={len(lease['jobs'])}\nquota_date={lease['quota_date']}\n")
    elif args.stage == 'collect':
        write(LEASE.with_name('progress.json'), collect(plan, state, read(LEASE)))
    else:
        report = publish_report(plan, state, read(LEASE), read(LEASE.with_name('progress.json')), OUTPUT,
                                Path(os.environ['RUNNER_TEMP']) / 'garp-campaign-private', Path('data/universe.csv'),
                                parent_report=Path('campaign-parent/report'))
        with Path(os.environ['GITHUB_OUTPUT']).open('a', encoding='utf-8') as stream:
            stream.write(f"status={report['status']}\n")


if __name__ == '__main__':
    main()
