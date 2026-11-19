"""Common, fail-closed ingestion for operator-authorized filing exports."""
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlsplit

import pandas as pd

from .gemini_filing import is_public_https


SOURCES = {
    'KRX': ('Korea', 'OpenDART', ('opendart.fss.or.kr', 'dart.fss.or.kr')),
    'JPX': ('Japan', 'EDINET', ('disclosure2dl.edinet-fsa.go.jp', 'disclosure2.edinet-fsa.go.jp', 'api.edinet-fsa.go.jp')),
    'SSE_MAIN': ('China', 'SSE', ('sse.com.cn',)),
    'SSE_STAR': ('China', 'SSE', ('sse.com.cn',)),
    'SZSE_MAIN': ('China', 'SZSE', ('szse.cn', 'static.cninfo.com.cn')),
    'SZSE_CHINEXT': ('China', 'SZSE', ('szse.cn', 'static.cninfo.com.cn')),
    'BSE': ('China', 'BSE', ('bse.cn',)),
    'HKEX': ('Hong Kong', 'HKEXnews', ('hkexnews.hk',)),
    'TWSE': ('Taiwan', 'MOPS', ('mops.twse.com.tw', 'doc.twse.com.tw')),
    'TPEX': ('Taiwan', 'MOPS', ('mops.twse.com.tw', 'doc.twse.com.tw')),
}
METRICS = {
    'revenue', 'operating_income', 'attributable_net_income', 'operating_cash_flow',
    'capital_expenditure', 'free_cash_flow', 'assets', 'liabilities', 'equity',
    'cash', 'interest_bearing_debt', 'shares_outstanding', 'diluted_eps',
}
KEYS = ('ticker', 'issuer_id', 'metric', 'definition', 'period_start', 'period_end',
        'period_kind', 'scope', 'statement', 'currency', 'unit')
VENUE_SUFFIXES = {
    'KRX': ('.KS', '.KQ'), 'JPX': ('.T',), 'SSE_MAIN': ('.SS',), 'SSE_STAR': ('.SS',),
    'SZSE_MAIN': ('.SZ',), 'SZSE_CHINEXT': ('.SZ',), 'BSE': ('.BJ',),
    'HKEX': ('.HK',), 'TWSE': ('.TW',), 'TPEX': ('.TWO',),
}
PROVENANCE = ('issuer_name', 'publication_date', 'source_url', 'source_locator',
              'source_sha256', 'provider_version', 'parser_version')


@dataclass(frozen=True)
class Observation:
    fields: dict[str, str]
    normalized: Decimal

    @property
    def key(self):
        return tuple(self.fields[field] for field in KEYS)


def parse(row, cutoff):
    if any(not row.get(field, '').strip() for field in KEYS):
        raise ValueError('MISSING_COMPARISON_CONTEXT')
    if row['metric'] not in METRICS:
        raise ValueError('UNSUPPORTED_METRIC')
    start, end, published = (date.fromisoformat(row[field]) for field in
                             ('period_start', 'period_end', 'publication_date'))
    if not start <= end <= published <= cutoff:
        raise ValueError('INVALID_OR_FUTURE_PERIOD')
    if row['period_kind'] not in {'FY', 'QUARTER', 'YTD', 'INSTANT'}:
        raise ValueError('UNKNOWN_PERIOD_KIND')
    if row['period_kind'] == 'INSTANT' and start != end:
        raise ValueError('INVALID_INSTANT')
    if row['scope'] not in {'CONSOLIDATED', 'SEPARATE'}:
        raise ValueError('UNKNOWN_ACCOUNTING_SCOPE')
    if len(row['currency']) != 3 or not row['currency'].isascii() or not row['currency'].isupper() or not row['currency'].isalpha():
        raise ValueError('INVALID_CURRENCY')
    expected_unit = {'shares_outstanding': 'SHARES', 'diluted_eps': 'CURRENCY_PER_SHARE'}
    if row['unit'] != expected_unit.get(row['metric'], 'CURRENCY'):
        raise ValueError('INCOMPATIBLE_UNIT')
    value, scale = (Decimal(row[field]) for field in ('value', 'scale'))
    if not value.is_finite() or scale not in {Decimal(10) ** power for power in range(13)}:
        raise ValueError('INVALID_VALUE_OR_SCALE')
    return Observation(row, value * scale)


def validate_source(row, source_dir):
    if any(not row.get(field, '').strip() for field in PROVENANCE):
        raise ValueError('MISSING_SOURCE_PROVENANCE')
    venue = row['venue']
    market, _, hosts = SOURCES[venue]
    if row['market'] != market or not row['ticker'].endswith(VENUE_SUFFIXES[venue]):
        raise ValueError('VENUE_MARKET_MISMATCH')
    url = urlsplit(row['source_url'])
    if (not is_public_https(row['source_url']) or
            not any(url.hostname == host or (url.hostname or '').endswith('.' + host) for host in hosts)):
        raise ValueError('UNRECOGNIZED_PRIMARY_SOURCE')
    digest = row['source_sha256']
    if len(digest) != 64 or set(digest) - set('0123456789abcdef'):
        raise ValueError('INVALID_SOURCE_CHECKSUM')
    source = source_dir / digest
    if source.stat().st_size > 64_000_000:
        raise ValueError('SOURCE_SIZE_LIMIT')
    if sha256(source.read_bytes()).hexdigest() != digest:
        raise ValueError('SOURCE_CHECKSUM_MISMATCH')


def reconcile(primary, vendor, source_dir, cutoff, tolerance=Decimal('0.02')):
    """Compare exact semantic matches, preserving original values and provenance."""
    if not tolerance.is_finite() or not 0 <= tolerance <= 1:
        raise ValueError('Invalid reconciliation tolerance')
    vendor_index = {}
    for row in vendor:
        try:
            observation = parse(row, cutoff)
        except (ValueError, KeyError, InvalidOperation):
            continue
        vendor_index.setdefault(observation.key, []).append(observation)
    audit = []
    for row in primary:
        result = {**row, 'status': 'UNVERIFIED', 'reason': '',
                  'evidence_state': 'UNVERIFIED', 'human_review_status': 'NOT_REVIEWED',
                  'normalization': 'REPORTED_VALUE_TIMES_DECLARED_SCALE'}
        audit.append(result)
        try:
            validate_source(row, source_dir)
            observation = parse(row, cutoff)
        except (ValueError, KeyError, InvalidOperation, OSError) as exc:
            result.update(status='BLOCKED', reason=str(exc) if isinstance(exc, ValueError) else type(exc).__name__)
            continue
        result['primary_normalized'] = str(observation.normalized)
        if row.get('acquisition') in {'OFFICIAL_LIVE', 'OFFICIAL_REPLAY'}:
            result['evidence_state'] = 'SOURCE_TEXT_MATCHED'
        matches = vendor_index.get(observation.key, [])
        if not matches:
            result['reason'] = 'NO_COMPARABLE_VENDOR_OBSERVATION'
            continue
        if len(matches) != 1:
            result.update(status='BLOCKED', reason='AMBIGUOUS_VENDOR_OBSERVATION')
            continue
        comparison = matches[0]
        difference = abs(observation.normalized - comparison.normalized)
        denominator = abs(observation.normalized)
        relative = difference / denominator if denominator else (Decimal(0) if not difference else None)
        passed = relative is not None and relative <= tolerance
        result.update(vendor_value=comparison.fields['value'], vendor_scale=comparison.fields['scale'],
                      vendor_publication_date=comparison.fields['publication_date'],
                      vendor_normalized=str(comparison.normalized), absolute_difference=str(difference),
                      relative_difference='' if relative is None else str(relative),
                      status='MACHINE_RECONCILED' if passed else 'BLOCKED',
                      reason='' if passed else 'NUMERICAL_DISCREPANCY')
    duplicates = {}
    for row in audit:
        if 'primary_normalized' in row:
            duplicates.setdefault(tuple(row[field] for field in KEYS), []).append(row)
    for group in duplicates.values():
        if len(group) > 1:
            for row in group:
                row.update(status='BLOCKED', reason='DUPLICATE_OR_RESTATED_PRIMARY')
    for row in audit:
        if row['status'] in {'BLOCKED', 'MACHINE_RECONCILED'}:
            row['evidence_state'] = row['status']
    return audit


def read_export(path: Path | None) -> list[dict]:
    return pd.read_csv(path, dtype=str, keep_default_na=False).to_dict('records') if path else []
