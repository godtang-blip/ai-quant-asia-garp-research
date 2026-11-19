"""Separate provider values, primary observations and signed valuation inputs."""
import argparse
from collections import Counter, defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from io import BytesIO
from itertools import chain
import json
from pathlib import Path
import re

import pandas as pd

from .filing_evidence import PROVENANCE, SOURCES, VENUE_SUFFIXES, validate_original, validate_source
from .gemini_filing import is_public_https
from .scoring_v03 import compute_scores


# Snapshot columns and provider field names are retained independently of the
# definitions an analyst later supplies. None of the Yahoo P/E fields prove a
# fiscal period, a statutory denominator, or a split adjustment basis.
VENDOR_FIELDS = {
    'current_price': ('price', 'currentPrice/regularMarketPrice', 'INSTANT', 'CURRENCY_PER_SHARE'),
    'forward_eps': ('eps', 'forwardEps', 'FORWARD', 'CURRENCY_PER_SHARE'),
    'trailing_eps': ('eps', 'trailingEps', 'TTM', 'CURRENCY_PER_SHARE'),
    'vendor_forward_pe_raw': ('forward_pe', 'forwardPE', 'FORWARD', 'MULTIPLE'),
    'revenue_total_raw': ('revenue', 'totalRevenue', '', 'CURRENCY'),
    'free_cashflow_raw': ('free_cash_flow', 'freeCashflow', '', 'CURRENCY'),
    'market_cap': ('market_cap', 'marketCap', 'INSTANT', 'CURRENCY'),
    'revenue_growth': ('revenue_growth', 'revenueGrowth', '', 'RATIO'),
    'earnings_growth': ('earnings_growth', 'earningsGrowth', '', 'RATIO'),
    'operating_margin': ('operating_margin', 'operatingMargins', '', 'RATIO'),
    'roe': ('roe', 'returnOnEquity', '', 'RATIO'),
    'vendor_price_to_sales_raw': ('price_to_sales', 'priceToSalesTrailing12Months', 'TTM', 'MULTIPLE'),
    'debt_to_equity_ratio': ('debt_to_equity', 'debtToEquity / 100', '', 'RATIO'),
    'price_change_52w': ('price_change', '52WeekChange', 'TRAILING_52_WEEKS', 'RATIO'),
    'fcf_yield': ('fcf_yield', 'ENGINE_DERIVED_FCF_YIELD', '', 'RATIO'),
}
CONTEXT = ('issuer_id', 'definition', 'period_kind', 'period_start', 'period_end', 'scope',
           'accounting_standard', 'adjustment', 'share_basis', 'currency', 'unit')
OBSERVATION_COLUMNS = ('ticker', 'metric', 'value', 'scale', *CONTEXT, 'venue', 'market', 'issuer_name',
                       'publication_date', 'collected_at', 'source_url', 'source_locator', 'source_sha256',
                       'provider_version', 'parser_version')
REVIEW_COLUMNS = ('observation_sha256', 'reviewer', 'reviewed_at', 'decision',
                  'quote_value', 'quote_currency', 'quote_collected_at', 'quote_source_url', 'quote_share_basis')
CASE_DATA = Path(__file__).resolve().parents[1] / 'docs/cases/yukiguni_1375T.json'
TOLERANCE = Decimal('0.02')
STATUTORY = {'IFRS', 'JP_GAAP', 'US_GAAP', 'K_IFRS', 'HKFRS', 'TIFRS', 'PRC_GAAP'}


def clean(value):
    if value is None or pd.isna(value):
        return ''
    return str(value).strip()


def decimal_value(value):
    try:
        result = Decimal(clean(value))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def iso_date(value):
    try:
        if len(value) == 10:
            return date.fromisoformat(value)
        return datetime.fromisoformat(value).date()
    except (TypeError, ValueError):
        return None


def read_rows(path, required):
    if not path.is_file():
        return []
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not set(required) <= set(frame.columns):
        raise ValueError(f'{path.name} is missing required provenance fields')
    return [{key: value.strip() for key, value in row.items()} for row in frame.to_dict('records')]


def unique_index(rows, keys, label):
    result = {}
    for row in rows:
        key = tuple(row[field] for field in keys)
        if any(not part for part in key) or key in result:
            raise ValueError(f'Blank or duplicate {label} key')
        result[key] = row
    return result


def source_url(value):
    return value if isinstance(value, str) and is_public_https(value) else ''


def vendor_observations(ranked, directory):
    key_fields = ('ticker', 'snapshot_field', 'collected_at')
    context = unique_index(read_rows(directory / 'vendor_context.csv', key_fields), key_fields, 'vendor context')
    result = []
    for row in ranked.to_dict('records'):
        if clean(row.get('fetch_error')):
            continue
        ticker = clean(row['ticker'])
        collected = clean(row.get('retrieved_at_utc'))
        for field, (metric, reported, kind, unit) in VENDOR_FIELDS.items():
            effective = {'vendor_forward_pe_raw': 'forward_pe', 'vendor_price_to_sales_raw': 'price_to_sales'}.get(field, field)
            value = decimal_value(row.get(field))
            # Old snapshots may have only the screen field and no raw alias.
            if value is None and (field not in row or clean(row.get('valuation_quote_status')) in
                                  {'SAME_CURRENCY_VENDOR_RATIO_UNVERIFIED', 'CURRENCY_UNKNOWN_VENDOR_RATIO_UNVERIFIED'}):
                value = decimal_value(row.get(effective))
            if value is None:
                continue
            observation = dict.fromkeys(OBSERVATION_COLUMNS, '')
            observation.update(ticker=ticker, metric=metric, value=str(value), scale='1', period_kind=kind,
                               unit=unit, collected_at=collected, source_url=source_url(clean(row.get('source_url'))),
                               snapshot_field=field, reported_label=reported,
                               currency=clean(row.get('currency')) if field in {'current_price', 'market_cap'} else '',
                               verification_status='UNVERIFIED_PROVIDER' if field != 'fcf_yield' else 'DERIVED_UNVERIFIED')
            if field in {'revenue_total_raw', 'free_cashflow_raw'}:
                observation['currency'] = clean(row.get('financial_currency'))
            declared = context.get((ticker, field, collected), {})
            for name in CONTEXT:
                if declared.get(name):
                    if observation[name] and observation[name] != declared[name]:
                        raise ValueError(f'Vendor context contradicts the snapshot metadata for {field}')
                    observation[name] = declared[name]
            result.append(observation)
    return result


def official_observations(directory, cutoff, acquired=()):
    declared = read_rows(directory / 'official_observations.csv', OBSERVATION_COLUMNS)
    registry = read_rows(directory.parent / 'issuer_source_registry.csv',
                         ('ticker', 'filing_url', 'earnings_url', 'source_date', 'reviewed_by')) if declared else []
    result = []
    for original, manual in chain(((row, True) for row in declared), ((row, False) for row in acquired)):
        is_acquired = original.get('acquisition') in {'OFFICIAL_LIVE', 'OFFICIAL_REPLAY'}
        row = {field: clean(original.get(field)) for field in OBSERVATION_COLUMNS}
        reported_definition = row['definition']
        if row['metric'] == 'diluted_eps':
            row.update(metric='eps', definition='DILUTED_EPS')
        if is_acquired and row['accounting_standard'] == 'IFRS':
            if row['metric'] == 'revenue' and reported_definition in {'Revenue', 'RevenueIFRS'}:
                row['definition'] = 'IFRS_TOTAL_REVENUE'
            if row['metric'] == 'operating_income' and reported_definition in {'OperatingProfitLoss', 'OperatingProfitLossIFRS'}:
                row['definition'] = 'IFRS_OPERATING_INCOME'
        row.update(reported_label=reported_definition, verification_status='UNVERIFIED_OFFICIAL_OBSERVATION',
                   source_check='NOT_CHECKED')
        if manual:
            try:
                validate_manual_source(row, registry, directory / 'originals', cutoff)
                if not valid_official_context(row, cutoff):
                    raise ValueError('INVALID_OFFICIAL_OBSERVATION_CONTEXT')
            except (ValueError, KeyError, OSError) as exc:
                row.update(verification_status='BLOCKED', source_check=str(exc) if isinstance(exc, ValueError)
                           else type(exc).__name__)
            else:
                row.update(source_check='ORIGINAL_HASH_MATCHED_MANUAL_TRANSCRIPTION')
        elif 'primary_normalized' in original:
            row['source_check'] = 'ORIGINAL_HASH_MATCHED'
            if is_acquired:
                row['verification_status'] = 'SOURCE_TEXT_MATCHED'
        else:
            row.update(verification_status='BLOCKED', source_check=clean(original.get('reason')) or 'SOURCE_UNVERIFIED')
        row['source_url'] = source_url(row['source_url'])
        identity = {key: row[key] for key in OBSERVATION_COLUMNS}
        row['observation_sha256'] = sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()
        result.append(row)
    return result


def validate_manual_source(row, registry, originals, cutoff):
    url = row['source_url']
    if row['venue'] not in SOURCES:
        raise ValueError('UNRECOGNIZED_PRIMARY_VENUE')
    for registration in registry:
        registered_at = iso_date(registration['source_date'])
        if (registration['ticker'] == row['ticker'] and url in {registration['filing_url'], registration['earnings_url']}
                and registration['reviewed_by'] and registered_at and registered_at <= cutoff and source_url(url)
                and row['ticker'].endswith(VENUE_SUFFIXES[row['venue']])
                and row['market'] == SOURCES[row['venue']][0] and all(row[field] for field in PROVENANCE)):
            validate_original(row, originals)
            return
    validate_source(row, originals)


def valid_official_context(row, cutoff):
    start, end, published, collected = (iso_date(row[field]) for field in
                                         ('period_start', 'period_end', 'publication_date', 'collected_at'))
    value, scale = decimal_value(row['value']), decimal_value(row['scale'])
    if (not all((start, end, published, collected)) or not start <= end or not published <= collected <= cutoff
            or row['period_kind'] not in {'FY', 'TTM', 'QUARTER', 'YTD', 'FORWARD', 'INSTANT'}
            or not (published < end if row['period_kind'] == 'FORWARD' else end <= published)
            or (row['period_kind'] == 'INSTANT' and start != end)
            or row['scope'] not in {'CONSOLIDATED', 'SEPARATE'}
            or not row['definition'] or not row['issuer_id'] or value is None
            or scale not in {Decimal(10) ** power for power in range(13)}
            or not re.fullmatch('[A-Z]{3}', row['currency'])):
        return False
    if (re.search(r'\bCORE\b', row['definition'].upper().replace('_', ' ')) or row['adjustment'] == 'COMPANY_DEFINED_CORE'
            or row['accounting_standard'] == 'NON_IFRS_COMPANY_DEFINED'):
        return (row['definition'] == 'ISSUER_CORE_OPERATING_INCOME' and row['metric'] == 'operating_income'
                and row['unit'] == 'CURRENCY'
                and row['adjustment'] == 'COMPANY_DEFINED_CORE' and
                row['accounting_standard'] == 'NON_IFRS_COMPANY_DEFINED')
    return (row['accounting_standard'] in STATUTORY and row['adjustment'] in {'UNADJUSTED', 'ADJUSTED'}
            and row['unit'] in {'CURRENCY', 'CURRENCY_PER_SHARE', 'RATIO', 'MULTIPLE', 'SHARES'})


def compare(vendor, official):
    """Return independent semantic and numeric results for the same metric family."""
    if (vendor.get('metric') != official.get('metric') or
            (vendor.get('ticker') and official.get('ticker') and vendor['ticker'] != official['ticker'])):
        return 'ISSUER_OR_METRIC_MISMATCH', '', None
    period_fields = ('period_kind', 'period_start', 'period_end')
    differences = [field for field in CONTEXT if vendor.get(field) and official.get(field)
                   and vendor[field] != official[field]]
    if any(field in differences for field in period_fields):
        return 'PERIOD_MISMATCH_OR_UNRESOLVED', '|'.join(differences), None
    if 'definition' in differences or 'adjustment' in differences:
        return 'DEFINITION_OR_ADJUSTMENT_MISMATCH', '|'.join(differences), None
    missing_period = [field for field in period_fields if not vendor.get(field) or not official.get(field)]
    if missing_period:
        return 'PERIOD_MISMATCH_OR_UNRESOLVED', '|'.join(missing_period), None
    required = tuple(key for key in CONTEXT if key != 'share_basis' or vendor['metric'] == 'eps')
    missing = [field for field in required if not vendor.get(field) or not official.get(field)]
    if differences or missing:
        return 'COMPARISON_CONTEXT_MISMATCH_OR_UNRESOLVED', '|'.join(differences + missing), None
    if official.get('verification_status') not in {'SOURCE_TEXT_MATCHED', 'HUMAN_REVIEWED_SOURCE'}:
        return 'PRIMARY_SOURCE_UNVERIFIED', '', None
    vendor_url, primary_url = (source_url(row.get('source_url', '')) for row in (vendor, official))
    if not vendor_url or not primary_url or vendor_url == primary_url:
        return 'INDEPENDENT_PRIMARY_SOURCE_REQUIRED', '', None
    observed_at, filing_date, retrieved_at = (
        iso_date(value) for value in (vendor.get('collected_at'), official.get('publication_date'), official.get('collected_at')))
    if not all((observed_at, filing_date, retrieved_at)):
        return 'COMPARISON_CONTEXT_MISMATCH_OR_UNRESOLVED', 'COLLECTION_OR_PUBLICATION_DATE', None
    if filing_date > observed_at:
        return 'PRIMARY_PUBLISHED_AFTER_VENDOR_SNAPSHOT', '', None
    numbers = [decimal_value(row[field]) for row in (official, vendor) for field in ('value', 'scale')]
    if any(value is None for value in numbers):
        return 'NON_NUMERIC_COMPARISON_VALUE', '', None
    primary, observed = numbers[0] * numbers[1], numbers[2] * numbers[3]
    difference = abs(primary - observed)
    comparable = difference <= abs(primary) * TOLERANCE
    return ('COMPARABLE_VALUES_AGREE' if comparable else 'COMPARABLE_NUMERIC_DISCREPANCY',
            '', difference)


def arithmetic(price, eps, pe, quote_currency='', eps_currency=''):
    quote, estimate, reported = map(decimal_value, (price, eps, pe))
    if not all(value is not None and value > 0 for value in (quote, estimate, reported)):
        return 'INSUFFICIENT_POSITIVE_PRICE_EPS_PER', None
    if quote_currency and eps_currency and quote_currency != eps_currency:
        return 'CURRENCY_MISMATCH', None
    implied = quote / estimate
    status = 'INTERNAL_ARITHMETIC_AGREES' if abs(implied - reported) <= reported * TOLERANCE else 'INTERNAL_ARITHMETIC_MISMATCH'
    if not quote_currency or not eps_currency:
        status += '_EPS_OR_PRICE_UNIT_UNCONFIRMED'
    return status, implied


def reviewed_forward(ranked, directory, cutoff, official=None):
    reviews = read_rows(directory / 'analyst_reviews.csv', REVIEW_COLUMNS)
    if not reviews:
        return {}, []
    records = official if official is not None else official_observations(directory, cutoff)
    by_hash = defaultdict(list)
    for item in records:
        by_hash[item['observation_sha256']].append(item)
    candidates = ranked.set_index('ticker').to_dict('index') if not ranked.empty else {}
    reviews_by_hash = Counter(row['observation_sha256'] for row in reviews)
    accepted = defaultdict(list)
    results = []
    for review in reviews:
        targets = by_hash[review['observation_sha256']]
        item = targets[0] if len(targets) == 1 else {}
        ticker = item.get('ticker', '')
        current = candidates.get(ticker, {})
        observed_at = clean(current.get('retrieved_at_utc'))
        reviewed_at, quote_date = iso_date(review['reviewed_at']), iso_date(observed_at)
        price, eps = decimal_value(review['quote_value']), decimal_value(item.get('value'))
        filing_date = iso_date(item.get('publication_date', ''))
        evidence_date = iso_date(item.get('collected_at', ''))
        row = {key: review[key] for key in REVIEW_COLUMNS}
        row['quote_source_url'] = source_url(row['quote_source_url'])
        row.update(ticker=ticker, review_status='BLOCKED', forward_review_status='NOT_APPLICABLE', reason='')
        results.append(row)
        if reviews_by_hash[review['observation_sha256']] != 1:
            row['reason'] = 'AMBIGUOUS_OBSERVATION_REVIEW'
            continue
        if item.get('source_check') not in {'ORIGINAL_HASH_MATCHED_MANUAL_TRANSCRIPTION', 'ORIGINAL_HASH_MATCHED'}:
            row['reason'] = 'SOURCE_OR_OBSERVATION_HASH_UNAVAILABLE'
            continue
        elif (review['decision'] != 'CONFIRMED' or not review['reviewer'] or not reviewed_at or
              not filing_date or not evidence_date or not filing_date <= evidence_date <= reviewed_at <= cutoff):
            row['reason'] = 'REVIEW_MISSING_OR_NOT_POINT_IN_TIME'
            continue
        row.update(review_status='HUMAN_REVIEWED_SOURCE', reviewed_value=item['value'],
                   official_source_url=item['source_url'])
        if item['metric'] != 'eps' or item['period_kind'] != 'FORWARD':
            continue
        row['forward_review_status'] = 'BLOCKED'
        if (item['definition'] not in {'BASIC_EPS', 'DILUTED_EPS'} or item['scope'] != 'CONSOLIDATED' or
              item['accounting_standard'] not in STATUTORY or item['adjustment'] != 'UNADJUSTED' or
              item['unit'] != 'CURRENCY_PER_SHARE' or item['scale'] != '1' or
              not valid_official_context(item, cutoff) or eps is None or eps <= 0):
            row['reason'] = 'UNSUPPORTED_FORWARD_EPS_BASIS'
        elif (not quote_date or not filing_date <= quote_date <= reviewed_at or quote_date >= iso_date(item['period_end'])
              or price is None or price <= 0 or price != decimal_value(current.get('current_price')) or
              review['quote_collected_at'] != observed_at or not row['quote_source_url'] or
              row['quote_source_url'] != clean(current.get('source_url')) or not item['share_basis'] or
              review['quote_share_basis'] != item['share_basis'] or
              review['quote_currency'] != item['currency'] or review['quote_currency'] != clean(current.get('currency'))):
            row['reason'] = 'PRICE_CURRENCY_DATE_OR_SHARE_BASIS_NOT_ATTESTED'
        else:
            row.update(forward_review_status='HUMAN_REVIEWED_FORWARD_BASIS', issuer_guidance_per=str(price / eps))
            accepted[ticker].append(row)
    approved = {}
    for ticker, matches in accepted.items():
        if len(matches) == 1:
            approved[ticker] = matches[0]
        else:
            for row in matches:
                row.update(forward_review_status='BLOCKED', reason='AMBIGUOUS_FORWARD_VALUATION_REVIEW')
    return approved, results


def has_forward_input(row):
    return any(decimal_value(row.get(field)) is not None for field in ('forward_pe', 'vendor_forward_pe_raw', 'forward_eps'))


def compare_rows(vendor, official):
    index = defaultdict(list)
    for item in official:
        index[item['ticker'], item['metric']].append(item)
    results = []
    for item in vendor:
        for primary in index[item['ticker'], item['metric']]:
            status, reason, difference = compare(item, primary)
            results.append({'ticker': item['ticker'], 'metric': item['metric'],
                            'vendor_field': item['snapshot_field'], 'vendor_value': item['value'],
                            'official_value': primary['value'], 'official_scale': primary['scale'],
                            'vendor_definition': item['definition'], 'official_definition': primary['definition'],
                            'official_observation_sha256': primary['observation_sha256'],
                            'comparison_status': status, 'comparison_reason': reason,
                            'normalized_difference': str(difference) if difference is not None else ''})
    return results


def score_comparison(ranked, approved, vendor):
    from .v031 import eligibility

    if ranked.empty:
        return []
    before = ranked.set_index('ticker')
    scores = pd.to_numeric(before['cross_industry_score_100'], errors='coerce')
    original_rank = dict(zip(scores.dropna().index, range(1, scores.notna().sum() + 1)))
    after, new_rank = None, {}
    if approved:
        revised = ranked[ranked.ticker.isin(approved)].copy()
        revised['forward_pe'] = revised.ticker.map(lambda ticker: float(approved[ticker]['issuer_guidance_per']))
        revised = compute_scores(revised)
        revised['v031_research_eligible'] = eligibility(revised)[0]
        after = before.copy()
        after['cross_industry_score_100'] = scores
        after['v031_research_eligible'] = after.v031_research_eligible.astype(str).str.lower().isin({'true', '1'})
        fields = ['cross_industry_score_100', 'v031_research_eligible']
        after.update(revised.set_index('ticker')[fields])
        # A missing revised score must replace, rather than keep, the original.
        for row in revised.itertuples():
            after.loc[row.ticker, 'cross_industry_score_100'] = row.cross_industry_score_100
        ordered = after.reset_index().sort_values(['v031_research_eligible', 'cross_industry_score_100', 'ticker'],
                                                ascending=[False, False, True])
        new_rank = {ticker: rank for rank, ticker in enumerate(
            ordered.loc[pd.to_numeric(ordered.cross_industry_score_100, errors='coerce').notna(), 'ticker'], 1)}
    eps_currencies = {item['ticker']: item['currency'] for item in vendor if item['snapshot_field'] == 'forward_eps'}
    results = []
    for ticker, row in before.iterrows():
        if not has_forward_input(row) and (after is None or ticker not in original_rank):
            continue
        reported = row.get('vendor_forward_pe_raw', row.get('forward_pe'))
        calculation, implied = arithmetic(row.get('current_price'), row.get('forward_eps'), reported,
                                          clean(row.get('currency')), eps_currencies.get(ticker, ''))
        item = approved.get(ticker)
        new_score = clean(after.at[ticker, 'cross_industry_score_100']) if after is not None else ''
        score_before = decimal_value(row['cross_industry_score_100'])
        score_after = decimal_value(new_score)
        results.append(dict(ticker=ticker, vendor_price=clean(row.get('current_price')),
                            vendor_eps=clean(row.get('forward_eps')), vendor_reported_per=clean(reported),
                            arithmetic_status=calculation, vendor_implied_per=str(implied) if implied is not None else '',
                            exploratory_forward_per=clean(row.get('forward_pe')),
                            score_before=clean(row['cross_industry_score_100']), rank_before=original_rank.get(ticker, ''),
                            reviewed_forward_per=item['issuer_guidance_per'] if item else '',
                            score_after=new_score, rank_after=new_rank.get(ticker, ''),
                            score_delta=str(score_after - score_before) if score_before is not None and score_after is not None else '',
                            reviewed_observation_sha256=item['observation_sha256'] if item else '',
                            reason=('HUMAN_REVIEWED_ISSUER_GUIDANCE_AND_PRICE' if item else
                                    'RANK_CONTEXT_OTHER_TICKERS_REASSESSED' if after is not None else
                                    'NOT_REASSESSED_NO_REVIEWED_FORWARD_BASIS')))
    return results


def write_audit(output, ranked, directory, cutoff, acquired):
    vendor = vendor_observations(ranked, directory)
    official = official_observations(directory, cutoff, acquired)
    approved, reviews = reviewed_forward(ranked, directory, cutoff, official)
    reviewed_hashes = {row['observation_sha256'] for row in reviews if row['review_status'] == 'HUMAN_REVIEWED_SOURCE'}
    for row in official:
        if row['observation_sha256'] in reviewed_hashes:
            row['verification_status'] = 'HUMAN_REVIEWED_SOURCE'
    comparisons = compare_rows(vendor, official)
    reassessment = score_comparison(ranked, approved, vendor)
    for name, rows, columns in (
        ('80_vendor_metric_provenance.csv', vendor, (*OBSERVATION_COLUMNS, 'snapshot_field', 'reported_label', 'verification_status')),
        ('81_official_metric_observations.csv', official, (*OBSERVATION_COLUMNS, 'reported_label', 'source_check',
                                                        'verification_status', 'observation_sha256')),
        ('82_analyst_metric_reviews.csv', reviews, (*REVIEW_COLUMNS, 'ticker', 'review_status', 'forward_review_status',
                                                  'reason', 'reviewed_value', 'issuer_guidance_per', 'official_source_url')),
        ('83_financial_metric_comparison.csv', comparisons, ('ticker', 'metric', 'vendor_field', 'vendor_value',
          'official_value', 'official_scale', 'vendor_definition', 'official_definition', 'official_observation_sha256',
          'comparison_status', 'comparison_reason', 'normalized_difference')),
        ('84_forward_valuation_reassessment.csv', reassessment, (
          'ticker', 'vendor_price', 'vendor_eps', 'vendor_reported_per', 'arithmetic_status', 'vendor_implied_per',
          'exploratory_forward_per', 'score_before', 'rank_before', 'reviewed_forward_per', 'score_after', 'rank_after',
          'score_delta', 'reviewed_observation_sha256', 'reason')),
    ):
        pd.DataFrame(rows, columns=columns).to_csv(output / name, index=False)
    return {'vendor_observations': len(vendor), 'official_observations': len(official),
            'analyst_review_rows': len(reviews), 'reassessed_tickers': len(approved),
            'comparison_states': dict(Counter(row['comparison_status'] for row in comparisons)),
            'unchanged_screen': '01_all_research_candidates.csv'}


def reproduce_case(case):
    vendor = case['vendor']
    quote, eps, pe = (vendor[key] for key in ('price', 'eps', 'per'))
    status, implied = arithmetic(quote, eps, pe, vendor['quote_currency'], vendor['stated_eps_currency'])
    forecast = case['issuer_forecast']
    trailing = case['trailing_eps']
    forecast_comparison = compare(vendor['observation'], forecast)
    trailing_comparison = compare(vendor['observation'], trailing)
    return {'ticker': case['ticker'], 'snapshot_date': case['snapshot_date'], 'source_status': case['source_status'],
            'vendor_eps': eps, 'vendor_per': pe, 'vendor_arithmetic_status': status,
            'vendor_implied_per': str(implied.quantize(Decimal('0.0001'))),
            'reported_issuer_forecast_eps': forecast['value'],
            'reported_issuer_forecast_price_proxy_per': str((Decimal(quote) / Decimal(forecast['value'])).quantize(Decimal('0.0001'))),
            'absolute_eps_gap_not_a_verified_discrepancy': str(abs(Decimal(eps) - Decimal(forecast['value']))),
            'forecast_comparison': forecast_comparison[0], 'forecast_reason': forecast_comparison[1],
            'reported_ttm_eps': trailing['value'], 'ttm_comparison': trailing_comparison[0],
            'original_score': None, 'original_rank': None, 'reassessed_score': None, 'reassessed_rank': None,
            'valuation_gate': 'HOLD_FORWARD_INPUT_NOT_REVIEWED'}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='mode', required=True)
    case = commands.add_parser('case', help='Reproduce the user-supplied Yukiguni arithmetic')
    case.add_argument('--input', type=Path, default=CASE_DATA)
    offline = commands.add_parser('audit-ranked', help='Read an archived campaign ranking without fetching data')
    offline.add_argument('--ranked', type=Path, required=True)
    offline.add_argument('--asof-date', type=date.fromisoformat, required=True)
    offline.add_argument('--output', type=Path, required=True)
    offline.add_argument('--metric-evidence-dir', type=Path, default=Path('data/financial_evidence'))
    args = parser.parse_args(argv)
    if args.mode == 'case':
        print(json.dumps(reproduce_case(json.loads(args.input.read_text())), ensure_ascii=False, indent=2))
        return

    raw = args.ranked.read_bytes()
    ranked = pd.read_csv(BytesIO(raw), dtype={'ticker': str}, keep_default_na=False)
    if (not {'ticker', 'cross_industry_score_100', 'v031_research_eligible', 'retrieved_at_utc'} <= set(ranked)
            or ranked.ticker.eq('').any() or ranked.ticker.duplicated().any()):
        parser.error('Expected an archived campaign ranking with unique tickers and original score metadata')
    observed = ranked.retrieved_at_utc
    if 'fetch_error' in ranked:
        observed = observed[ranked.fetch_error.eq('')]
    if any(stamp and (not iso_date(stamp) or iso_date(stamp) > args.asof_date) for stamp in observed):
        parser.error('Ranking contains invalid or later data than the specified cutoff')
    args.output.mkdir(parents=True, exist_ok=False)
    report = write_audit(args.output, ranked, args.metric_evidence_dir, args.asof_date, [])
    report.update(mode='ARCHIVED_RANKS_READ_ONLY_NO_LIVE_REQUESTS', asof_date=str(args.asof_date),
                  ranked_input_sha256=sha256(raw).hexdigest())
    (args.output / '85_financial_provenance_manifest.json').write_text(
        json.dumps(report, indent=2) + '\n', encoding='utf-8')


if __name__ == '__main__':
    main()
