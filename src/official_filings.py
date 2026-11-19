"""Bounded retrieval of approved original filings from public official publishers."""
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from zipfile import is_zipfile

import requests

from .evidence import dart_recent_filings, dart_stock_code_map
from .edinet_filings import API, EDINETError, fetch_edinet, parse_xbrl
from .filing_evidence import SOURCES, VENUE_SUFFIXES, read_export
from .filing_statements import StatementError, parse_statement
from .gemini_filing import is_public_https
from .opendart_statements import fetch_statement


# Exact delivery hosts. Public disclosure search screens supply attachment links.
ATTACHMENT_HOSTS = {
    'SSE_MAIN': {'www.sse.com.cn', 'static.sse.com.cn'},
    'SSE_STAR': {'www.sse.com.cn', 'static.sse.com.cn'},
    'SZSE_MAIN': {'www.szse.cn', 'disc.static.szse.cn', 'static.cninfo.com.cn'},
    'SZSE_CHINEXT': {'www.szse.cn', 'disc.static.szse.cn', 'static.cninfo.com.cn'},
    'BSE': {'www.bse.cn', 'static.bse.cn'},
    'HKEX': {'www.hkexnews.hk', 'www1.hkexnews.hk'},
    'TWSE': {'mops.twse.com.tw', 'doc.twse.com.tw'},
    'TPEX': {'mops.twse.com.tw', 'doc.twse.com.tw'},
}
MAX_BYTES = 32_000_000


class SourceUnavailable(ValueError):
    """Controlled diagnostic that never contains URLs with API keys."""


@dataclass(frozen=True)
class FilingRequest:
    venue: str
    ticker: str
    issuer_id: str
    issuer_name: str
    period_start: date
    period_end: date
    publication_date: date
    source_url: str
    document_id: str
    expected_sha256: str

    @classmethod
    def from_row(cls, row, cutoff):
        venue = row['venue']
        ticker = row['ticker']
        if venue not in ATTACHMENT_HOSTS and venue != 'JPX':
            raise SourceUnavailable('UNSUPPORTED_FILING_VENUE')
        if not ticker.endswith(VENUE_SUFFIXES[venue]):
            raise SourceUnavailable('FILING_TICKER_VENUE_MISMATCH')
        if not all(row[key].strip() for key in ('issuer_id', 'issuer_name')):
            raise SourceUnavailable('FILING_ISSUER_REQUIRED')
        start, end, published = (date.fromisoformat(row[key]) for key in
                                 ('period_start', 'period_end', 'publication_date'))
        if not start <= end <= published <= cutoff or not 350 <= (end - start).days <= 380:
            raise SourceUnavailable('INVALID_ANNUAL_FILING_PERIOD_OR_LOOKAHEAD')
        url = row.get('source_url', '')
        if venue != 'JPX' and (not is_public_https(url) or urlsplit(url).hostname not in ATTACHMENT_HOSTS[venue]):
            raise SourceUnavailable('FILING_URL_NOT_ON_OFFICIAL_DELIVERY_HOST')
        digest = row.get('expected_sha256', '')
        if digest and not re.fullmatch('[0-9a-f]{64}', digest):
            raise SourceUnavailable('INVALID_EXPECTED_SHA256')
        return cls(venue, ticker, row['issuer_id'].strip(), row['issuer_name'].strip(), start, end, published,
                   url, row.get('document_id', '').strip(), digest)

    def provenance(self, url, digest):
        market, publisher, _ = SOURCES[self.venue]
        return {
            'ticker': self.ticker, 'venue': self.venue, 'market': market,
            'issuer_id': self.issuer_id, 'issuer_name': self.issuer_name,
            'publication_date': str(self.publication_date), 'source_url': url,
            'source_sha256': digest, 'provider_version': publisher,
        }


def download(session, url, *, params=None, limit=MAX_BYTES):
    """Use approved HTTPS hosts without redirect, session login or challenge handling."""
    try:
        with session.get(url, params=params, timeout=(6, 15), stream=True,
                         allow_redirects=False, auth=lambda request: request,
                         headers={'User-Agent': 'AsiaGARPResearch/0.6'}) as reply:
            if reply.status_code != 200:
                raise SourceUnavailable(f'ORIGIN_HTTP_{reply.status_code}')
            started = time.monotonic()
            body = bytearray()
            for chunk in reply.iter_content(65536):
                body.extend(chunk)
                if len(body) > limit or time.monotonic() - started > 25:
                    raise SourceUnavailable('FILING_DOWNLOAD_LIMIT')
            return bytes(body), reply.headers.get('Content-Type', '').split(';')[0].strip().lower()
    except requests.exceptions.ProxyError as exc:
        diagnostic = str(exc)
        reason = next((f'PROXY_CONNECT_{status}' for status in (403, 407, 502, 503)
                       if f'Tunnel connection failed: {status}' in diagnostic), 'PROXY_CONNECTION_FAILED')
        raise SourceUnavailable(reason) from None
    except requests.exceptions.Timeout:
        raise SourceUnavailable('OFFICIAL_SOURCE_TIMEOUT') from None
    except requests.RequestException:
        raise SourceUnavailable('OFFICIAL_SOURCE_TRANSPORT_ERROR') from None
    finally:
        # Publisher cookies are unnecessary and may select user-specific responses.
        session.cookies.clear()


def store_original(source_dir, digest, raw):
    source_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = source_dir / digest
    try:
        with target.open('xb') as stream:
            stream.write(raw)
    except FileExistsError:
        with target.open('rb') as stream:
            if sha256(stream.read(MAX_BYTES + 1)).hexdigest() != digest:
                raise SourceUnavailable('EXISTING_SOURCE_HASH_MISMATCH')


def acquire_sources(native_path, dart_path, source_dir, cutoff, budget, delay, keys, *, replay_dir=None, selected_tickers=None):
    """Return parsed observations and one measurable outcome per scheduled filing."""
    planned = [(row, False) for row in read_export(native_path)]
    planned += [(row, True) for row in read_export(dart_path)]
    rows, attempts = [], []
    used = 0
    seen = set()
    with requests.Session() as session:
        for row, dart in planned:
            if selected_tickers is not None and row.get('ticker') not in selected_tickers:
                continue
            venue = 'KRX' if dart else row.get('venue', '')
            identity = (venue, row.get('ticker', ''), row.get('period_end', ''))
            attempt = dict(venue=venue, ticker=identity[1], status='NOT_TESTED', attempted=False,
                           source_response_received=False, document_retrieved=False, observations=0)
            attempts.append(attempt)
            try:
                if identity in seen:
                    raise SourceUnavailable('DUPLICATE_FILING_REQUEST')
                seen.add(identity)
                key_name = 'DART_API_KEY' if dart else 'EDINET_API_KEY' if venue == 'JPX' else None
                key = keys.get(key_name, '')
                if key_name and not key and not (replay_dir and not dart):
                    attempt['reason'] = key_name + '_MISSING'
                    continue
                if used >= budget:
                    attempt['reason'] = 'FILING_BUDGET_EXHAUSTED'
                    continue
                filing = None if dart else FilingRequest.from_row(row, cutoff)
                if replay_dir and not dart:
                    if not filing.expected_sha256:
                        raise SourceUnavailable('REPLAY_EXPECTED_SHA256_REQUIRED')
                    with (replay_dir / filing.expected_sha256).open('rb') as stream:
                        raw = stream.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES or sha256(raw).hexdigest() != filing.expected_sha256:
                        raise SourceUnavailable('REPLAY_ORIGINAL_CHECKSUM_MISMATCH')
                    if venue == 'JPX':
                        if not re.fullmatch(r'S[0-9A-Z]{7}', filing.document_id):
                            raise SourceUnavailable('REPLAY_EDINET_DOCUMENT_ID_REQUIRED')
                        url = f'{API}/{filing.document_id}?type=1'
                        extracted = parse_xbrl(raw, filing)
                    else:
                        url = filing.source_url
                        kind = 'application/pdf' if raw.startswith(b'%PDF-') else 'text/html'
                        extracted = parse_statement(raw, kind, filing)
                    store_original(source_dir, filing.expected_sha256, raw)
                    rows.extend(dict(filing.provenance(url, filing.expected_sha256), **item,
                                     acquisition='OFFICIAL_REPLAY') for item in extracted)
                    used += 1
                    attempt.update(status='REPLAY_PARSED' if extracted else 'REPLAY_NO_SUPPORTED_STATEMENT_ROWS',
                                   replay_observations=len(extracted), source_sha256=filing.expected_sha256)
                    continue
                if used:
                    time.sleep(delay)
                used += 1
                attempt['attempted'] = True
                if dart:
                    extracted = fetch_statement(session, row, key, cutoff, source_dir)
                    attempt['source_response_received'] = True
                    attempt['document_retrieved'] = True
                else:
                    if venue == 'JPX':
                        # EDINET annual list and archive requests both go through the same limits.
                        def fetch(url, **kwargs):
                            return download(session, url, **kwargs)
                        raw, url, parser = fetch_edinet(fetch, filing, key)
                    else:
                        url = filing.source_url
                        raw, kind = download(session, url)
                        parser = lambda payload, spec: parse_statement(payload, kind, spec)
                    attempt['source_response_received'] = True
                    digest = sha256(raw).hexdigest()
                    if filing.expected_sha256 and digest != filing.expected_sha256:
                        raise SourceUnavailable('FILING_HASH_MISMATCH')
                    if venue == 'JPX' and is_zipfile(BytesIO(raw)):
                        attempt.update(document_retrieved=True, source_sha256=digest, source_url=url)
                    observations = parser(raw, filing)
                    attempt['document_retrieved'] = True
                    store_original(source_dir, digest, raw)
                    extracted = [dict(filing.provenance(url, digest), **observation) for observation in observations]
                if extracted:
                    attempt['source_sha256'] = extracted[0]['source_sha256']
                rows.extend(extracted)
                attempt.update(status='PARSED' if extracted else 'NO_SUPPORTED_STATEMENT_ROWS',
                               observations=len(extracted))
            except (SourceUnavailable, EDINETError, StatementError) as exc:
                attempt.update(status=('PARSE_FAILED' if attempt['document_retrieved'] else
                                       'NOT_TESTED' if str(exc).startswith('PROXY_CONNECT_') else 'FAILED'),
                               reason=str(exc))
            except (ValueError, KeyError, OSError, requests.RequestException) as exc:
                # Generic transport and document errors may include credentialized parameters.
                attempt.update(status='FAILED', reason=type(exc).__name__)
    return rows, attempts



def locate_dart_annual_filings(tickers, key, cutoff, budget):
    """Resolve up to budget Korean issuers, using one map and one list call per issuer."""
    if not tickers:
        return []
    if not key or budget <= 0:
        reason = 'DART_API_KEY_MISSING' if not key else 'FILING_BUDGET_EXHAUSTED'
        return [{'ticker': ticker, 'status': 'BLOCKED', 'reason': reason} for ticker in tickers]
    outcomes = []
    with requests.Session() as session:
        try:
            mapping = dart_stock_code_map(key, session)
        except (ValueError, OSError, requests.RequestException) as exc:
            return [{'ticker': ticker, 'status': 'BLOCKED', 'reason': 'DART_ISSUER_MAP_' + type(exc).__name__}
                    for ticker in tickers]
        for index, ticker in enumerate(tickers):
            issuer = mapping.get(ticker.split('.')[0])
            row = {'ticker': ticker, 'status': 'BLOCKED'}
            outcomes.append(row)
            if index >= budget:
                row['reason'] = 'FILING_BUDGET_EXHAUSTED'
            elif not issuer:
                row['reason'] = 'DART_ISSUER_NOT_MAPPED'
            else:
                try:
                    results = dart_recent_filings(ticker.split('.')[0], mapping, key, session,
                                                  days=450, limit=5, annual_only=True, cutoff=cutoff)
                    row.update(official_issuer=issuer, filings=results,
                               status='METADATA_ONLY' if results else 'BLOCKED',
                               reason='ANNUAL_PERIOD_AND_ORIGINAL_APPROVAL_REQUIRED' if results else
                               'NO_DART_ANNUAL_FILING_IN_LOOKBACK')
                except (ValueError, OSError, requests.RequestException) as exc:
                    row['reason'] = 'DART_ANNUAL_LIST_' + type(exc).__name__
    return outcomes


def main():
    """Run only the publisher path, useful when the fundamentals vendor is unavailable."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--requests', required=True, type=Path)
    parser.add_argument('--source-dir', required=True, type=Path)
    parser.add_argument('--replay-dir', type=Path)
    parser.add_argument('--budget', type=int, choices=range(1, 11), default=5)
    parser.add_argument('--asof-date', type=date.fromisoformat, default=date.today())
    args = parser.parse_args()
    rows, attempts = acquire_sources(args.requests, None, args.source_dir, args.asof_date, args.budget, 1,
                                     {'EDINET_API_KEY': os.environ.get('EDINET_API_KEY', '')}, replay_dir=args.replay_dir)
    print(json.dumps({'attempts': attempts, 'parsed_rows': len(rows)}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
