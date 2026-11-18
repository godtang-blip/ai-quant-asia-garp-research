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


def sdk_rows(result):
    records = []
    while result.error_code == '0' and result.next():
        records.append(dict(zip(result.fields, result.get_row_data(), strict=True)))
        if len(records) > 40_000:
            raise ValueError('BaoStock row ceiling exceeded')
    if result.error_code != '0':
        code = str(result.error_code)
        raise RuntimeError('BaoStock SDK error ' + (code if code.isdecimal() else 'UNKNOWN'))
    return records


STAGE_TIMEOUTS = {'login': 8, 'calendar': 8, 'security_master': 16, 'dated_inventory': 16}


class StageTimeout(BaseException):
    pass


def sdk_stage(stage, operation):
    def timed_out(*_):
        raise StageTimeout

    print(f'BAOSTOCK_STAGE:{stage}', file=sys.stderr, flush=True)
    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.setitimer(signal.ITIMER_REAL, STAGE_TIMEOUTS[stage])
    try:
        return operation()
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def failed_stage(stderr):
    events = re.findall(r'^BAOSTOCK_STAGE:([a-z_]+)$',
                        (stderr or b'').decode(errors='replace'), re.M)
    return events[-1] if events and events[-1] in STAGE_TIMEOUTS else 'unknown'


def collect():
    import baostock as bs

    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    login = sdk_stage('login', bs.login)
    if login.error_code != '0':
        code = str(login.error_code)
        raise RuntimeError('BaoStock login error ' + (code if code.isdecimal() else 'UNKNOWN'))
    calendar = sdk_stage('calendar', lambda: sdk_rows(bs.query_trade_dates(
        start_date=str(today - timedelta(days=14)), end_date=str(today - timedelta(days=1)))))
    as_of = max(row['calendar_date'] for row in calendar if row['is_trading_day'] == '1')
    master = sdk_stage('security_master', lambda: sdk_rows(bs.query_stock_basic()))
    snapshot = sdk_stage('dated_inventory', lambda: sdk_rows(bs.query_all_stock(as_of)))
    # This is a one-shot SDK worker. Process exit closes its socket.
    return {'provider': 'BaoStock', 'as_of': as_of, 'master': master, 'snapshot': snapshot}


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
            result = subprocess.run([sys.executable, '-m', 'src.china_security_master'],
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=52, check=False)
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
        rows, detail = validated_rows(json.loads(raw))
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
        with redirect_stdout(sys.stderr):
            data = collect()
        validated_rows(data)
        print(json.dumps(data, ensure_ascii=False))
    except StageTimeout:
        sys.exit(3)
    except Exception as exc:
        print(type(exc).__name__, file=sys.stderr)
        sys.exit(1)
