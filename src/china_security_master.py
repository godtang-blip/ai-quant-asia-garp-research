"""BaoStock listing inventory, independently validated against its dated market snapshot."""
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
from time import monotonic
from zoneinfo import ZoneInfo

from .official_universe import _market_row
from .venue_sources import ListingError

HOST, PORT = 'public-api.baostock.com', 10030
ENDPOINT = f'tcp://{HOST}:{PORT}'
PROVIDER_URL = 'http://www.baostock.com/'
BOARDS = {
    'sh': ('.SS', r'(?:600|601|603|605|688|689)\d{3}'),
    'sz': ('.SZ', r'(?:000|001|002|003|300|301)\d{3}'),
    'bj': ('.BJ', r'(?:4\d|8\d|92)\d{4}'),
}


def sdk_rows(result, progress=None):
    records = []
    while result.error_code == '0' and result.next():
        records.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
        if progress is not None:
            progress['rows'] = len(records)
        if len(records) > 40_000:
            raise ValueError('BaoStock row ceiling exceeded')
    if result.error_code != '0':
        code = str(result.error_code)
        raise RuntimeError('BaoStock SDK error ' + (code if code.isdecimal() else 'UNKNOWN'))
    return records


STAGE_TIMEOUTS = {'login': 8, 'calendar': 8, 'dated_inventory': 16,
                  'master_query': 12, 'master_rows': 16}
WORKER_TIMEOUT = 64


class StageTimeout(BaseException):
    pass


def sdk_stage(stage, operation, metrics):
    def timed_out(*_):
        raise StageTimeout

    print(f'BAOSTOCK_STAGE:{stage}', file=sys.stderr, flush=True)
    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.setitimer(signal.ITIMER_REAL, STAGE_TIMEOUTS[stage])
    started = monotonic()
    try:
        return operation()
    finally:
        metrics.setdefault(stage, {})['duration_seconds'] = round(monotonic() - started, 3)
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def failed_stage(stderr):
    events = re.findall(r'^BAOSTOCK_STAGE:([a-z_]+)$',
                        (stderr or b'').decode(errors='replace'), re.M)
    return events[-1] if events and events[-1] in STAGE_TIMEOUTS else 'unknown'


def collect(allow_provisional=False):
    import baostock as bs

    metrics = {}
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    login = sdk_stage('login', bs.login, metrics)
    if login.error_code != '0':
        raise RuntimeError('BaoStock login error')
    calendar = sdk_stage('calendar', lambda: sdk_rows(bs.query_trade_dates(
        start_date=str(today - timedelta(days=14)), end_date=str(today - timedelta(days=1)))), metrics)
    as_of = max(row['calendar_date'] for row in calendar if row['is_trading_day'] == '1')
    snapshot = sdk_stage('dated_inventory', lambda: sdk_rows(bs.query_all_stock(as_of)), metrics)
    metrics['dated_inventory']['rows'] = len(snapshot)
    data = {'provider': 'BaoStock', 'as_of': as_of, 'snapshot': snapshot, 'sdk_metrics': metrics}
    stage = 'master_query'
    try:
        result = sdk_stage(stage, bs.query_stock_basic, metrics)
        first_page = getattr(result, 'data', None)
        if isinstance(first_page, list):
            metrics[stage]['rows'] = len(first_page)
        if result.error_code != '0':
            raise RuntimeError('BaoStock master query failed')
        stage = 'master_rows'
        progress = metrics.setdefault(stage, {'rows': 0})
        data['master'] = sdk_stage(stage, lambda: sdk_rows(result, progress), metrics)
    except (StageTimeout, RuntimeError, ValueError) as exc:
        if not allow_provisional:
            raise
        data['master_failure'] = 'TIMEOUT' if isinstance(exc, StageTimeout) else 'SOURCE_UNAVAILABLE'
        data['master_failure_stage'] = stage
    # Process exit closes the one-shot worker's connection.
    return data


def provisional_shenzhen(data, today=None):
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    as_of = date.fromisoformat(data['as_of'])
    if data['provider'] != 'BaoStock' or not 0 <= (today - as_of).days <= 10:
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'BaoStock provisional inventory date is invalid')
    snapshot = data['snapshot']
    codes = [row['code'] for row in snapshot]
    if not codes or len(set(codes)) != len(codes):
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'BaoStock provisional inventory is empty or duplicated')
    suffix, pattern = BOARDS['sz']
    return [{'ticker': code[3:] + suffix, 'source_asof': str(as_of), 'source': ENDPOINT,
             'classification': 'UNVERIFIED_INVENTORY_CANDIDATE', 'screening_eligible': False}
            for code in codes if code.startswith('sz.') and re.fullmatch(pattern, code[3:])]


def validated_rows(data, today=None):
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    as_of = date.fromisoformat(data['as_of'])
    if data['provider'] != 'BaoStock' or not 0 <= (today - as_of).days <= 10:
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'BaoStock snapshot date is stale or invalid')
    snapshot = data['snapshot']
    master = data['master']
    listing_codes = {row['code'] for row in snapshot}
    if not snapshot or len(listing_codes) != len(snapshot) or not master:
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Empty or duplicate BaoStock market inventory')
    master_codes = {row['code'] for row in master}
    if any(code not in master_codes and exchange in BOARDS and re.fullmatch(BOARDS[exchange][1], symbol)
           for code in listing_codes for exchange, _, symbol in [code.partition('.')]):
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Dated A-share inventory is absent from the security master')
    groups = {exchange: [] for exchange in BOARDS}
    unknown = excluded = inactive = duplicates = 0
    seen = {}
    for item in master:
        exchange, _, code = item['code'].partition('.')
        suffix, mask = BOARDS.get(exchange, ('', ''))
        kind, status = item['type'], item['status']
        if kind not in {'1', '2', '3', '4', '5'} or status not in {'0', '1'} or exchange not in BOARDS:
            unknown += 1
            continue
        if kind != '1' or not re.fullmatch(mask, code):
            excluded += 1
            continue
        if status != '1' or item['outDate']:
            inactive += 1
            continue
        if not item['ipoDate'] or not item['code_name'].strip():
            unknown += 1
            continue
        if date.fromisoformat(item['ipoDate']) > as_of:
            inactive += 1
            continue
        if item['code'] not in listing_codes:
            raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Active security missing from dated inventory')
        if item['code'] in seen:
            if seen[item['code']] != item:
                raise ListingError('SOURCE_CONFLICT', 'Conflicting duplicate security master record')
            duplicates += 1
            continue
        seen[item['code']] = item
        row = _market_row(code + suffix, item['code_name'].strip(), 'China', PROVIDER_URL)
        row['security_type_status'] = 'THIRD_PARTY_EQUITY_REQUIRES_VENDOR_CONFIRMATION'
        groups[exchange].append(row)
    if not groups['sh'] or not groups['sz']:
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'BaoStock did not establish both Shanghai and Shenzhen scope')
    return [row for rows in groups.values() for row in rows], {
        'scope': 'BaoStock active A-share security master cross-checked with dated inventory; not exchange verified',
        'source_url': ENDPOINT, 'source_asof': str(as_of), 'received': len(master),
        'rejected_non_equity': excluded, 'inactive_or_after_cutoff': inactive, 'unknown_classification': unknown, 'duplicate_rows': duplicates,
        'scope_counts': json.dumps({
            'SSE_MAIN': sum(not row['ticker'].startswith(('688', '689')) for row in groups['sh']),
            'SSE_STAR': sum(row['ticker'].startswith(('688', '689')) for row in groups['sh']),
            'SZSE_MAIN': sum(not row['ticker'].startswith(('300', '301')) for row in groups['sz']),
            'SZSE_CHINEXT': sum(row['ticker'].startswith(('300', '301')) for row in groups['sz']),
            'BSE': len(groups['bj']),
        }),
        'completeness_check': 'ACTIVE_MASTER_CODES_PRESENT_IN_DATED_PROVIDER_INVENTORY; NO_EXCHANGE_TOTAL_CHECK',
    }


def tcp_preflight():
    try:
        probe = subprocess.run([sys.executable, '-m', 'src.china_security_master', '--tcp-probe'],
                               capture_output=True, timeout=8, check=False, text=True)
    except subprocess.TimeoutExpired:
        raise ListingError('TCP_PROBE_TIMEOUT', 'BaoStock TCP preflight exceeded 8 seconds') from None
    if probe.returncode:
        category = {
            'TIMEOUT': 'TCP_CONNECT_TIMEOUT', 'REFUSED': 'TCP_CONNECT_REFUSED',
            'DNS_ERROR': 'TCP_DNS_FAILURE', 'NETWORK_ERROR': 'TCP_UNREACHABLE',
        }.get(probe.stdout.strip(), 'TCP_PROBE_FAILED')
        raise ListingError(category, f'BaoStock TCP preflight failed for {HOST}:{PORT}')


def probe_endpoint():
    try:
        with socket.create_connection((HOST, PORT), timeout=5):
            return 'OK'
    except TimeoutError:
        return 'TIMEOUT'
    except ConnectionRefusedError:
        return 'REFUSED'
    except socket.gaierror:
        return 'DNS_ERROR'
    except OSError:
        return 'NETWORK_ERROR'


def fetch_baostock():
    from hashlib import sha256

    snapshot = os.environ.get('GARP_BAOSTOCK_SNAPSHOT')
    if snapshot:
        with Path(snapshot).open('rb') as stream:
            raw = stream.read(24_000_001)
    else:
        tcp_preflight()
        try:
            result = subprocess.run([sys.executable, '-m', 'src.china_security_master', '--allow-provisional'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=WORKER_TIMEOUT, check=False)
        except subprocess.TimeoutExpired as exc:
            stage = failed_stage(exc.stderr)
            raise ListingError('TIMEOUT', f'BaoStock worker deadline at stage {stage}') from None
        if result.returncode:
            stage = failed_stage(result.stderr)
            if result.returncode == 3:
                raise ListingError('TIMEOUT', f'BaoStock SDK stage {stage} exceeded its deadline')
            raise ListingError('SOURCE_UNAVAILABLE', f'BaoStock SDK failed at stage {stage}')
        raw = result.stdout
    if len(raw) > 24_000_000:
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'BaoStock snapshot exceeds byte ceiling')
    try:
        data = json.loads(raw)
        if not snapshot and 'master_failure' in data:
            provisional = provisional_shenzhen(data)
            return [], dict(source_asof=data['as_of'], source_url=ENDPOINT,
                            source_sha256=sha256(raw).hexdigest(), received=len(data['snapshot']),
                            provisional_rows=provisional, sdk_metrics=data['sdk_metrics'],
                            failure_code=data['master_failure'], failure_stage=data['master_failure_stage'],
                            retrieval_mode='LIVE_INVENTORY_ONLY')
        rows, detail = validated_rows(data)
        if not snapshot:
            detail['sdk_metrics'] = data['sdk_metrics']
    except (KeyError, ValueError, TypeError) as exc:
        if isinstance(exc, ListingError):
            raise
        raise ListingError('SCHEMA_DRIFT', 'BaoStock payload has invalid fields') from exc
    detail.update(source_sha256=sha256(raw).hexdigest(),
                  retrieval_mode='IMPORTED_VENDOR_SNAPSHOT' if snapshot else 'LIVE_VENDOR_SDK')
    return rows, detail


if __name__ == '__main__':
    from contextlib import redirect_stdout

    if sys.argv[1:] == ['--tcp-probe']:
        status = probe_endpoint()
        print(status)
        sys.exit(status != 'OK')

    try:
        allow_provisional = sys.argv[1:] == ['--allow-provisional']
        with redirect_stdout(sys.stderr):
            data = collect(allow_provisional=allow_provisional)
        if 'master_failure' in data:
            provisional_shenzhen(data)
        else:
            validated_rows(data)
        print(json.dumps(data, ensure_ascii=False))
    except StageTimeout:
        sys.exit(3)
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        sys.exit(1)
