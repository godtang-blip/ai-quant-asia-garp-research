"""Check one representative Yahoo symbol per missing board without running screening."""

import argparse
from contextlib import redirect_stdout
import csv
import datetime as dt
import json
import math
from pathlib import Path
import subprocess
import sys

SAMPLES = {'SZSE_MAIN': '000001.SZ', 'SZSE_CHINEXT': '300750.SZ', 'BSE': '920002.BJ'}
RESULT_FIELDS = ('observed_utc', 'board', 'ticker', 'vendor', 'status', 'http_status',
                 'quote_type', 'financial_fields_present')


def lookup(symbol):
    from .quality_v051 import FINANCIAL_FIELDS
    from .v031 import _fetch_vendor

    result = {'status': '', 'http_status': '', 'quote_type': '', 'financial_fields_present': ''}
    try:
        quote = _fetch_vendor(symbol)
    except Exception as exc:
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
        if 'connect tunnel failed' in str(exc).lower():
            result['status'] = 'PROXY_CONNECTION_FAILED'
        elif type(status) is int and 100 <= status <= 599:
            result.update(status='PROVIDER_HTTP_ERROR', http_status=status)
        elif isinstance(exc, ValueError) and str(exc) == 'No fundamentals from vendor':
            result['status'] = 'NO_FUNDAMENTALS_RETURNED'
        else:
            result['status'] = 'VENDOR_REQUEST_FAILED'
        return result
    kind = quote['vendor_quote_type']
    fields = [field for field in FINANCIAL_FIELDS if math.isfinite(quote[field])]
    result['quote_type'] = 'EQUITY' if kind == 'EQUITY' else ('OTHER' if kind else 'UNKNOWN')
    result['financial_fields_present'] = '|'.join(fields)
    if kind != 'EQUITY':
        result['status'] = 'EQUITY_TYPE_NOT_CONFIRMED'
    else:
        result['status'] = 'EQUITY_WITH_FINANCIAL_OBSERVATIONS' if fields else 'EQUITY_WITHOUT_FINANCIAL_OBSERVATIONS'
    return result


def probe_symbol(board, symbol):
    identity = {'observed_utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'board': board,
                'ticker': symbol, 'vendor': 'Yahoo Finance via yfinance get_info'}
    try:
        child = subprocess.run(
            [sys.executable, '-m', 'src.china_finance_probe', '--worker', symbol],
            capture_output=True, text=True, timeout=15, check=False,
        )
    except subprocess.TimeoutExpired:
        return {**identity, 'status': 'PROBE_TIMEOUT'}
    if child.returncode:
        return {**identity, 'status': 'PROBE_WORKER_FAILED'}
    try:
        return {**identity, **json.loads(child.stdout)}
    except (TypeError, ValueError):
        return {**identity, 'status': 'PROBE_WORKER_FAILED'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--output', type=Path)
    mode.add_argument('--worker', choices=SAMPLES.values(), help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        with redirect_stdout(sys.stderr):
            result = lookup(args.worker)
        print(json.dumps(result))
        return
    with args.output.open('x', encoding='utf-8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        for board, symbol in SAMPLES.items():
            writer.writerow(probe_symbol(board, symbol))
            stream.flush()


if __name__ == '__main__':
    main()
