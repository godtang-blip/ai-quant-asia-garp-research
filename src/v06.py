"""Run bounded five-market research with separate evidence and analyst gates."""
import argparse
from collections import Counter
from datetime import date, datetime, timezone
from decimal import Decimal
from importlib.metadata import version
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

import pandas as pd

from .discovery_review import candidate_review
from .filing_evidence import SOURCES, read_export, reconcile
from .gemini_filing import Gemini, plan, research
from .official_filings import acquire_sources, ATTACHMENT_HOSTS
from .v031 import FundamentalsUnavailable, _fetch_vendor
from .v051 import run as run_legacy


MARKETS = tuple(dict.fromkeys(market for market, _, _ in SOURCES.values()))
DEFAULT_MODEL = 'gemini-3.8-flash'


class FinancialBudget:
    def __init__(self, checkpoint, cutoff, budget, delay, fetch=_fetch_vendor):
        self.connection = sqlite3.connect(checkpoint)
        self.connection.execute('CREATE TABLE IF NOT EXISTS fundamentals '
                                '(scope TEXT, ticker TEXT, payload TEXT, PRIMARY KEY(scope, ticker))')
        self.scope = f'v06:{cutoff}:yfinance:{version("yfinance")}'
        self.budget = budget
        self.delay = delay
        self.fetch = fetch
        self.requests = 0
        self.hits = 0
        self.live_tickers = set()
        self.live_successes = set()
        self.not_before = 0.0

    def __call__(self, ticker):
        cached = self.connection.execute('SELECT payload FROM fundamentals WHERE scope=? AND ticker=?',
                                         (self.scope, ticker)).fetchone()
        if cached:
            self.hits += 1
            return json.loads(cached[0])
        for attempt in range(2):
            if self.requests >= self.budget:
                raise RuntimeError('FINANCIAL_FETCH_BUDGET_EXHAUSTED')
            time.sleep(max(0, self.not_before - time.monotonic()))
            self.requests += 1
            self.live_tickers.add(ticker)
            self.not_before = time.monotonic() + self.delay
            try:
                payload = self.fetch(ticker)
            except Exception:
                if attempt:
                    raise RuntimeError('FINANCIAL_PROVIDER_ERROR') from None
                self.not_before += 1
                continue
            with self.connection:
                self.connection.execute('INSERT OR REPLACE INTO fundamentals VALUES (?, ?, ?)',
                                        (self.scope, ticker, json.dumps(payload)))
            self.live_successes.add(ticker)
            return payload
        raise AssertionError('Unreachable')


def read_table(output, name):
    path = output / name
    if not path.is_file():
        return pd.DataFrame()
    return pd.read_csv(path, keep_default_na=False)


def write_json(output, name, payload):
    (output / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def gemini_report(args):
    model = args.model
    report = {'model': model, 'status': 'NOT_REQUESTED', 'gemini_requests': 0,
              'api_responses_received': 0}
    if not args.enable_gemini and not args.gemini_preflight:
        return report
    key = os.environ.get('GEMINI_API_KEY', '').strip()
    if not args.approved_sources:
        blockers = ['APPROVED_SOURCES_MISSING']
        if args.enable_gemini and not key:
            blockers.append('GEMINI_API_KEY_MISSING')
        return {**report, 'status': 'NOT_TESTED', 'reason': blockers[0], 'blockers': blockers}
    candidates = args.output / '01_all_research_candidates.csv'
    ledger = args.output / '18_evidence_ledger.csv'
    if not args.gemini_approved_only and (not candidates.is_file() or not ledger.is_file()):
        return {**report, 'status': 'NOT_TESTED', 'reason': 'RESEARCH_CANDIDATES_OR_LEDGER_MISSING'}
    selected, filings = plan(None if args.gemini_approved_only else candidates,
                             None if args.gemini_approved_only else ledger, args.approved_sources,
                             args.max_documents, [])
    filings = {ticker: filing for ticker, filing in filings.items()
               if date.fromisoformat(filing.document_date) <= args.asof_date}
    if not filings:
        return {**report, 'status': 'NOT_TESTED', 'reason': 'NO_APPROVED_DATED_FILING'}
    agent = Gemini(key, model, args.max_requests, 1, max_input_bytes=args.gemini_input_bytes,
                   max_output_tokens=args.gemini_output_tokens, delay=1) if args.enable_gemini and key else None
    mode = 'live' if agent else 'preflight' if args.gemini_preflight else 'dry-run'
    result = research(selected, filings, agent, mode=mode, replay_dir=args.gemini_replay_dir)
    responses = agent.responses_received if agent else 0
    status = ('LIVE_RESPONSE_RECEIVED' if responses else 'FAILED' if result['gemini_requests']
              else 'NOT_TESTED')
    reason = ('' if responses else 'NO_SUCCESSFUL_API_RESPONSE' if status == 'FAILED' else
              'DOCUMENT_PREFLIGHT_DID_NOT_REACH_MODEL' if agent else 'PREFLIGHT_ONLY' if args.gemini_preflight
              else 'GEMINI_API_KEY_MISSING')
    return {**result, 'model': model, 'status': status, 'reason': reason,
            'api_responses_received': responses,
            'sdk_version': version('google-genai') if agent else None,
            'reported_input_tokens': agent.input_tokens if agent else 0,
            'reported_output_tokens': agent.output_tokens if agent else 0,
            'estimated_cost_usd': None}


def rate(numerator, denominator):
    return {'succeeded': numerator, 'denominator': denominator,
            'rate': numerator / denominator if denominator else None}


def produce_reports(output, ranked, stages, findings, limit):
    if ranked.empty:
        ranked = pd.DataFrame(columns=['ticker', 'company', 'market'])
    if not stages.empty:
        ranked = ranked.merge(stages.drop(columns=['company', 'market'], errors='ignore'),
                              on='ticker', how='left', validate='one_to_one')
    by_ticker = {}
    for finding in findings:
        by_ticker.setdefault(finding.get('ticker'), []).append(finding)
    ranked['filing_status'] = [
        'BLOCKED' if 'BLOCKED' in statuses else
        'MACHINE_RECONCILED' if 'MACHINE_RECONCILED' in statuses else 'UNVERIFIED'
        for statuses in ({row['status'] for row in by_ticker.get(ticker, [])} for ticker in ranked.ticker)
    ]
    stage = ranked.get('research_stage', pd.Series('', index=ranked.index))
    issuer_ids = {}
    for ticker, rows in by_ticker.items():
        ids = {(row['market'], row['issuer_id']) for row in rows if 'primary_normalized' in row}
        if len(ids) == 1:
            issuer_ids[ticker] = ':'.join(next(iter(ids)))
        elif len(ids) > 1:
            ranked.loc[ranked.ticker.eq(ticker), 'filing_status'] = 'BLOCKED'
    ranked['verified_export_issuer_key'] = ranked.ticker.map(issuer_ids)
    shortlist = ranked[stage.eq('MEMO_READY') & ranked.filing_status.ne('BLOCKED')].copy()
    dedup_key = shortlist.verified_export_issuer_key.fillna('TICKER:' + shortlist.ticker)
    shortlist = shortlist[~dedup_key.duplicated()].head(limit)
    shortlist.to_csv(output / '65_five_market_shortlist.csv', index=False)
    lines = ['# Asia GARP v0.6 후보 검토', '',
             '업종별 점수 기준과 회계 범위가 다릅니다. 국가 간 비교에는 공시상 통화, 기간 및 연결 기준 확인이 필요합니다.',
             '']
    if shortlist.empty:
        lines.extend(['검토를 완료한 후보가 없습니다.', '', '## 검토 보류 사유'])
        for reason, count in Counter(stage.fillna('SCREEN_INCOMPLETE')).items():
            lines.append(f'- {reason or "SCREEN_INCOMPLETE"}: {count}')
        for reason, count in Counter(row['reason'] for row in findings if row['reason']).items():
            lines.append(f'- {reason}: {count}')
    for candidate in shortlist.head(3).to_dict('records'):
        ticker = candidate['ticker']
        lines.extend([f'## {ticker} {candidate["company"]}', '',
                      f'- 시장 및 동종 업종: {candidate["market"]} / {candidate["peer_group"]}',
                      f'- 매출 및 이익 성장률: {candidate.get("revenue_growth", "")} / {candidate.get("earnings_growth", "")}',
                      f'- 영업이익률: {candidate.get("operating_margin", "")}',
                      f'- 공시 검증: {candidate["filing_status"]}',
                      f'- Bear / Base / Bull: {candidate.get("intrinsic_bear")} / {candidate.get("intrinsic_base")} / {candidate.get("intrinsic_bull")}',
                      '- 성장 동력, 경쟁 우위 및 반증 조건: 검토 기록과 기존 리서치 메모 참조',
                      f'- 결론: {candidate["research_stage"]}', ''])
        for finding in by_ticker.get(ticker, []):
            if finding['status'] == 'MACHINE_RECONCILED':
                lines.append(f'- {finding["metric"]}: {finding["source_locator"]} ({finding["source_url"]})')
    (output / '66_candidate_briefs.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    return len(shortlist)


def run(args):
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    if (output / '11_discovery_universe.csv').exists():
        raise ValueError('Use a new output directory and reuse the external checkpoint')
    budget = FinancialBudget(args.checkpoint or output / '.financial.sqlite', args.asof_date,
                             args.financial_budget, args.delay_seconds)
    failed = pd.DataFrame()
    try:
        print('Discovery and financial screening', flush=True)
        run_legacy(args.universe, output, 0 if args.full_universe else args.max_symbols,
                   args.discover_mode, args.fx_mode, 0, args.snapshot_csv, args.per_region,
                   args.evidence_mode, args.evidence_limit, args.asof_date, markets=args.markets,
                   fetch_vendor=budget)
    except FundamentalsUnavailable as exc:
        failed = exc.attempts
    finally:
        budget.connection.close()
    ranked = read_table(output, '01_all_research_candidates.csv')
    stages = read_table(output, '32_research_stage_gate.csv')
    universe = read_table(output, '11_discovery_universe.csv')
    logs = read_table(output, '12_discovery_sources_log.csv')
    print('Primary filing import and deterministic reconciliation', flush=True)
    live_primary, filing_attempts = acquire_sources(
        args.official_filing_requests, args.opendart_requests, args.source_dir, args.asof_date,
        args.filing_budget, args.delay_seconds,
        {name: os.environ.get(name, '').strip() for name in ('DART_API_KEY', 'EDINET_API_KEY')})
    primary = [dict(row, acquisition='OPERATOR_EXPORT') for row in read_export(args.primary_export)]
    primary += [dict(row, acquisition='OFFICIAL_LIVE') for row in live_primary]
    vendor = read_export(args.vendor_export)
    audit = reconcile(primary, vendor, args.source_dir or output, args.asof_date, args.tolerance)
    pd.DataFrame(audit, columns=list(dict.fromkeys(
        ['ticker', 'venue', 'metric', 'status', 'reason'] + [key for row in audit for key in row]
    ))).to_csv(output / '62_numerical_reconciliation.csv', index=False)
    registry = [{'venue': venue, 'market': market, 'publisher': publisher,
                 'access': ('REGISTERED_API' if venue in {'KRX', 'JPX'} else
                            'APPROVED_OFFICIAL_ATTACHMENT' if venue in ATTACHMENT_HOSTS else 'AUTHORIZED_NORMALIZED_EXPORT'),
                 'status': 'LIVE_OBSERVATIONS' if any(row['venue'] == venue for row in live_primary) else
                 'EXPORT_SUPPLIED' if any(row.get('venue') == venue for row in primary) else
                 'SEE_FILING_ATTEMPTS' if any(row['venue'] == venue for row in filing_attempts) else 'NOT_CONFIGURED'}
                for venue, (market, publisher, _) in SOURCES.items()]
    pd.DataFrame(registry).to_csv(output / '61_primary_source_registry.csv', index=False)
    coverage = []
    for market in MARKETS:
        listed = universe[universe.market.eq(market)]
        evaluated = ranked[ranked.market.eq(market)] if not ranked.empty else ranked
        attempts = evaluated if failed.empty else failed[failed.market.eq(market)]
        filings = [row for row in audit if row.get('market') == market and 'primary_normalized' in row]
        coverage.append({'market': market, 'selected': market in args.markets, 'securities_discovered': len(listed),
                         'eligible_equities_confirmed': int(attempts.get('security_type_status', pd.Series(dtype=str)).eq('VERIFIED_EQUITY_VENDOR').sum()),
                         'mapped_issuer_ids_in_filing_exports': len({row['issuer_id'] for row in filings}),
                         'requiring_evidence_review': int(evaluated.get('v031_research_eligible', pd.Series(dtype=bool)).eq(True).sum()) -
                             int(stages.loc[stages.market.eq(market), 'research_stage'].eq('MEMO_READY').sum() if not stages.empty else 0),
                         'financial_rows': len(attempts),
                         'live_financial_attempted': int(attempts.ticker.isin(budget.live_tickers).sum()) if not attempts.empty else 0,
                         'live_financial_returned': int(attempts.ticker.isin(budget.live_successes).sum()) if not attempts.empty else 0,
                         'financial_fetch_succeeded': int(attempts.get('fetch_error', pd.Series(dtype=str)).eq('').sum()),
                         'securities_scored': int(pd.to_numeric(evaluated.get('cross_industry_score_100', pd.Series(dtype=float)), errors='coerce').notna().sum()),
                         'screen_passed': int(evaluated.get('v031_research_eligible', pd.Series(dtype=bool)).eq(True).sum()),
                         'securities_with_primary_observations': len({row['ticker'] for row in filings})})
    pd.DataFrame(coverage).to_csv(output / '60_financial_coverage.csv', index=False)
    print('Gemini filing interpretation and research reports', flush=True)
    try:
        gemini = gemini_report(args)
    except (ImportError, OSError, ValueError) as exc:
        gemini = {'status': 'GEMINI_INPUT_OR_SETUP_FAILED', 'error_type': type(exc).__name__,
                  'model': args.model, 'gemini_requests': 0}
    write_json(output, '63_gemini_evidence.json', gemini)
    exclusions = candidate_review(ranked, stages) if not ranked.empty else failed
    if args.previous_artifacts and not ranked.empty:
        previous = read_table(args.previous_artifacts, '01_all_research_candidates.csv')
        if previous.empty:
            raise ValueError('Previous artifacts do not contain screening rows')
        fields = ['ticker', 'lifecycle', 'review_reasons', 'v031_research_eligible',
                  'cross_industry_score_100', 'operating_margin', 'roe']
        exclusions = candidate_review(previous)[fields].merge(
            exclusions, on='ticker', how='outer', suffixes=('_before', ''), validate='one_to_one')
        blocked = set(stages.loc[stages.analyst_decision.isin(['REJECTED', 'ON_HOLD']), 'ticker']) if not stages.empty else set()
        source_backed = {row['ticker'] for row in audit if row['status'] == 'MACHINE_RECONCILED'}
        source_backed -= {row['ticker'] for row in audit if row['status'] == 'BLOCKED'}
        exclusions['recovery_review_pending'] = (
            exclusions.review_reasons_before.eq('MISSING_OR_INSUFFICIENT_DATA')
            & exclusions.v031_research_eligible.eq(True)
            & exclusions.ticker.isin(source_backed - blocked))
    exclusions.to_csv(output / '64_exclusion_audit.csv', index=False)
    report_files = ('65_five_market_shortlist.csv', '66_candidate_briefs.md')
    report_error = None
    try:
        shortlisted = produce_reports(output, ranked, stages, audit, args.report_limit)
    except OSError as exc:
        shortlisted, report_error = 0, type(exc).__name__
    report_count = sum((output / item).is_file() and (output / item).stat().st_size > 0 for item in report_files)
    verified_live = {(row['venue'], row['ticker'], row['source_sha256']) for row in audit
                     if row['acquisition'] == 'OFFICIAL_LIVE' and row['status'] == 'MACHINE_RECONCILED'}
    run_manifest = {
        'revision': '0.6', 'asof_date': str(args.asof_date),
        'generated_utc': datetime.now(timezone.utc).isoformat(),
        'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], text=True).strip(),
        'financial_status': 'PARTIAL_OR_FAILED' if ranked.empty or ranked.fetch_error.ne('').any()
        or (args.full_universe is False and len(universe[universe.market.isin(args.markets)]) > len(ranked))
        else 'SELECTED_UNIVERSE_FETCHED',
        'coverage': coverage,
        'failed_fetch_reasons': dict(Counter(value for value in (failed if ranked.empty else ranked)
                                             .get('fetch_error', []) if value)), 'discovery_sources': logs.to_dict('records'),
        'filing_attempts': filing_attempts,
        'outcomes': {
            'financial_data_mode': 'SNAPSHOT_REPLAY' if args.snapshot_csv else 'LIVE_WITH_OPTIONAL_CHECKPOINT',
            'discovered_unique_tickers': int(universe.ticker.nunique()),
            'live_financial_responses': rate(len(budget.live_successes), len(budget.live_tickers)),
            'live_financial_scored': rate(sum(row['ticker'] in budget.live_successes and
                                              pd.notna(pd.to_numeric(row['cross_industry_score_100'], errors='coerce'))
                                              for row in ranked.to_dict('records')), len(budget.live_tickers)),
            'official_source_responses': rate(sum(row['source_response_received'] for row in filing_attempts),
                                             sum(row['attempted'] for row in filing_attempts)),
            'official_document_retrieval': rate(sum(row['document_retrieved'] for row in filing_attempts),
                                               sum(row['attempted'] for row in filing_attempts)),
            'official_statement_parsing': rate(sum(row['observations'] > 0 for row in filing_attempts),
                                               sum(row['document_retrieved'] for row in filing_attempts)),
            'official_documents_with_numeric_reconciliation': rate(len(verified_live),
                                                                   sum(row['observations'] > 0 for row in filing_attempts)),
            'research_report_files': rate(report_count, len(report_files)),
            'research_report_error': report_error,
        },
        'verification_states': dict(Counter(row['status'] for row in audit)),
        'vendor_requests': budget.requests, 'checkpoint_hits': budget.hits,
        'provider_versions': {'yfinance': version('yfinance')},
        'gemini': {key: value for key, value in gemini.items() if key not in {'companies', 'observations'}},
        'shortlisted': shortlisted,
        'trade_orders': 'NONE', 'predictive_validation': 'NOT_PERFORMED',
    }
    write_json(output, '67_v06_run_manifest.json', run_manifest)
    return run_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--universe', type=Path, default=Path('data/universe.csv'))
    parser.add_argument('--output', type=Path, default=Path('outputs'))
    parser.add_argument('--markets', nargs='+', choices=MARKETS, default=MARKETS)
    parser.add_argument('--discover-mode', choices=['all5_official', 'all5', 'regional5', 'nikkei', 'off'], default='all5_official')
    parser.add_argument('--fx-mode', choices=['off', 'live'], default='off')
    parser.add_argument('--evidence-mode', choices=['off', 'news', 'full'], default='off')
    parser.add_argument('--per-region', type=int, default=90)
    parser.add_argument('--evidence-limit', type=int, default=8)
    parser.add_argument('--snapshot-csv', type=Path)
    parser.add_argument('--max-symbols', type=int, default=25)
    parser.add_argument('--full-universe', action='store_true')
    parser.add_argument('--financial-budget', type=int, default=25)
    parser.add_argument('--delay-seconds', type=float, default=1)
    parser.add_argument('--checkpoint', type=Path)
    parser.add_argument('--asof-date', type=date.fromisoformat, default=datetime.now(timezone.utc).date())
    parser.add_argument('--opendart-requests', type=Path)
    parser.add_argument('--official-filing-requests', type=Path)
    parser.add_argument('--filing-budget', type=int, choices=range(11), default=0)
    parser.add_argument('--primary-export', type=Path)
    parser.add_argument('--vendor-export', type=Path)
    parser.add_argument('--source-dir', type=Path)
    parser.add_argument('--tolerance', type=Decimal, default=Decimal('0.02'))
    parser.add_argument('--approved-sources', type=Path)
    gemini_mode = parser.add_mutually_exclusive_group()
    gemini_mode.add_argument('--enable-gemini', action='store_true')
    gemini_mode.add_argument('--gemini-preflight', action='store_true')
    parser.add_argument('--gemini-approved-only', action='store_true',
                        help='Use explicitly dated approvals independently of screening for a source canary')
    parser.add_argument('--gemini-replay-dir', type=Path)
    parser.add_argument('--model', default=os.environ.get('GARP_GEMINI_MODEL') or DEFAULT_MODEL)
    parser.add_argument('--gemini-input-bytes', type=int, default=24000)
    parser.add_argument('--gemini-output-tokens', type=int, default=1024)
    parser.add_argument('--previous-artifacts', type=Path)
    parser.add_argument('--max-documents', type=int, choices=range(1, 4), default=3)
    parser.add_argument('--max-requests', type=int, choices=range(1, 10), default=6)
    parser.add_argument('--report-limit', type=int, choices=range(1, 6), default=5)
    args = parser.parse_args()
    today = datetime.now(timezone.utc).date()
    if args.delay_seconds < 0.7 or args.max_symbols < 1 or args.financial_budget < 0:
        parser.error('Require delay >= 0.7, max-symbols >= 1 and financial-budget >= 0')
    if args.asof_date > today or (args.asof_date < today and not args.snapshot_csv):
        parser.error('Historical dates require a dated vendor snapshot. Future dates are invalid.')
    if not 1 <= args.gemini_input_bytes <= 24000 or not 1 <= args.gemini_output_tokens <= 1024:
        parser.error("Gemini caps are 24000 input bytes and 1024 output tokens per request")
    if (args.opendart_requests or args.official_filing_requests) and (not args.source_dir or args.source_dir.resolve().is_relative_to(args.output.resolve())):
        parser.error('Live filing acquisition requires a private --source-dir outside --output')
    run(args)


if __name__ == '__main__':
    main()
