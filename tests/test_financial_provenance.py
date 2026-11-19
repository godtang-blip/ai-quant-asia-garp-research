"""Synthetic evidence fixtures, plus a reproducible case supplied by the user."""
from datetime import date
from hashlib import sha256
import json

import pandas as pd

from src import financial_provenance as finance
from src.filing_evidence import reconcile
from src.research_quality import DCF_FIELDS, FIN_FIELDS, enhance, reconcile_financials
from src.scoring_v03 import SUBMETRICS, compute_scores
from src.v031 import eligibility
from test_v05_quality import a_dcf, a_fin, save_rows


CUTOFF = date(2026, 11, 19)
TICKER = '7203.T'
QUOTE_URL = 'https://finance.yahoo.com/quote/7203.T/'
COLLECTED = '2026-11-18T07:00:00+00:00'


def ranking():
    inputs = []
    for ticker, pe in [(TICKER, 5), ('9984.T', 9)]:
        row = dict.fromkeys((field for fields in SUBMETRICS.values() for field in fields), .15)
        row.update(ticker=ticker, company='Fixture company', market='Japan', peer_group='consumer_brands',
                   current_price=100, forward_eps=100 / pe, forward_pe=pe, vendor_forward_pe_raw=pe,
                   price_to_sales=2, currency='JPY', financial_currency='JPY', retrieved_at_utc=COLLECTED,
                   source_url=QUOTE_URL, security_type_status='VERIFIED_EQUITY_VENDOR',
                   data_quality_flags='', fetch_error='', is_new_discovery=False)
        inputs.append(row)
    ranked = compute_scores(pd.DataFrame(inputs))
    ranked['v031_research_eligible'] = eligibility(ranked)[0]
    return ranked


def official(directory, **options):
    directory.mkdir(exist_ok=True)
    content = b'Synthetic source fixture; FY forecast, Basic EPS 5'
    digest = sha256(content).hexdigest()
    originals = directory / 'originals'
    originals.mkdir(exist_ok=True)
    (originals / digest).write_bytes(content)
    row = dict(ticker=TICKER, metric='eps', value='5', scale='1', issuer_id='E99999', issuer_name='Fixture',
               definition='BASIC_EPS', period_kind='FORWARD', period_start='2026-04-01', period_end='2027-03-31',
               scope='CONSOLIDATED', accounting_standard='IFRS', adjustment='UNADJUSTED', share_basis='ORDINARY_V1',
               currency='JPY', unit='CURRENCY_PER_SHARE', venue='JPX', market='Japan', publication_date='2026-11-15',
               collected_at='2026-11-16', source_url='https://api.edinet-fsa.go.jp/example-fixture',
               source_locator='Fixture p. 2', source_sha256=digest, provider_version='fixture', parser_version='manual')
    row.update(options)
    save_rows(directory / 'official_observations.csv', [row], finance.OBSERVATION_COLUMNS)
    return row


def sign(directory, **options):
    item, = finance.official_observations(directory, CUTOFF)
    review = dict(observation_sha256=item['observation_sha256'], reviewer='fixture-analyst',
                  reviewed_at='2026-11-19', decision='CONFIRMED', quote_value='100', quote_currency='JPY',
                  quote_collected_at=COLLECTED, quote_source_url=QUOTE_URL, quote_share_basis='ORDINARY_V1')
    review.update(options)
    save_rows(directory / 'analyst_reviews.csv', [review], finance.REVIEW_COLUMNS)


def test_user_case_reproduces_arithmetic_and_holds_rank():
    result = finance.reproduce_case(json.loads(finance.CASE_DATA.read_text()))
    assert result['source_status'].startswith('USER_SUPPLIED_REAL_CASE')
    assert result['vendor_arithmetic_status'] == 'INTERNAL_ARITHMETIC_AGREES'
    assert result['vendor_implied_per'] == '7.1962'
    assert result['reported_issuer_forecast_price_proxy_per'] == '17.8521'
    assert result['absolute_eps_gap_not_a_verified_discrepancy'] == '94.31'
    assert result['forecast_comparison'] == result['ttm_comparison'] == 'PERIOD_MISMATCH_OR_UNRESOLVED'
    assert result['reassessed_score'] is None and result['reassessed_rank'] is None


def test_exact_context_conflict_and_currency_arithmetic_are_independent(tmp_path):
    primary = official(tmp_path)
    primary['verification_status'] = 'SOURCE_TEXT_MATCHED'
    vendor = dict(primary, value='20', source_url=QUOTE_URL)
    assert finance.compare(vendor, primary)[0] == 'COMPARABLE_NUMERIC_DISCREPANCY'
    assert finance.compare(dict(vendor, value='5.01'), primary)[0] == 'COMPARABLE_VALUES_AGREE'
    assert finance.compare(dict(vendor, period_end=''), primary)[0] == 'PERIOD_MISMATCH_OR_UNRESOLVED'
    assert finance.compare(dict(vendor, period_end='2028-03-31'), primary)[0] == 'PERIOD_MISMATCH_OR_UNRESOLVED'
    assert finance.compare(dict(vendor, share_basis=''), primary)[0] == 'COMPARISON_CONTEXT_MISMATCH_OR_UNRESOLVED'
    assert finance.compare(dict(vendor, source_url=primary['source_url']), primary)[0] == 'INDEPENDENT_PRIMARY_SOURCE_REQUIRED'
    assert finance.compare(dict(vendor, collected_at='2026-11-14'), primary)[0] == 'PRIMARY_PUBLISHED_AFTER_VENDOR_SNAPSHOT'
    assert finance.compare(vendor, dict(primary, verification_status='UNVERIFIED'))[0] == 'PRIMARY_SOURCE_UNVERIFIED'
    assert finance.arithmetic('100', '20', '5', 'JPY', 'USD') == ('CURRENCY_MISMATCH', None)
    assert finance.arithmetic('100', '20', '5', 'JPY', '')[0].endswith('UNIT_UNCONFIRMED')


def test_core_and_product_sales_are_separate_definitions(tmp_path):
    row = official(tmp_path, metric='revenue', definition='IFRS_TOTAL_REVENUE', unit='CURRENCY',
                   period_kind='FY', period_start='2025-04-01', period_end='2026-03-31')
    row['verification_status'] = 'SOURCE_TEXT_MATCHED'
    sales = dict(row, definition='PRODUCT_SALES', source_url=QUOTE_URL)
    assert finance.compare(sales, row)[0] == 'DEFINITION_OR_ADJUSTMENT_MISMATCH'
    core = dict(row, metric='operating_income', definition='ISSUER_CORE_OPERATING_INCOME', unit='CURRENCY',
                accounting_standard='NON_IFRS_COMPANY_DEFINED', adjustment='COMPANY_DEFINED_CORE')
    assert finance.valid_official_context(core, CUTOFF)
    assert not finance.valid_official_context(dict(core, metric='eps'), CUTOFF)
    assert not finance.valid_official_context(dict(core, accounting_standard='IFRS'), CUTOFF)
    statutory = dict(row, metric='operating_income', definition='IFRS_OPERATING_INCOME')
    assert finance.compare(dict(core, source_url=QUOTE_URL), statutory)[0] == 'DEFINITION_OR_ADJUSTMENT_MISMATCH'
    assert finance.compare(dict(core, ticker='9999.T'), core)[0] == 'ISSUER_OR_METRIC_MISMATCH'
    path = tmp_path / 'legacy.csv'
    save_rows(path, [a_fin() | {'statement_label': 'Product sales'},
                     a_fin(metric='operating_income') | {'statement_label': 'Core operating profit'}], FIN_FIELDS)
    audit, stats = reconcile_financials(path, cutoff=CUTOFF)
    assert stats['blocked_n'] == 2 and audit.validation_status.eq('BLOCKED').all()


def test_separate_reassessment_uses_existing_weights_and_preserves_screen(tmp_path):
    directory = tmp_path / 'private'
    official(directory)
    ranked = ranking()
    original = ranked.copy(deep=True)
    output = tmp_path / 'report'
    output.mkdir()
    # Declaring a source hash does not itself approve its financial or quote inputs.
    report = finance.write_audit(output, ranked, directory, CUTOFF, [])
    assert report['reassessed_tickers'] == 0
    assert pd.read_csv(output / '84_forward_valuation_reassessment.csv').rank_after.isna().all()
    fields = dict(ticker=TICKER, snapshot_field='forward_eps', collected_at=COLLECTED,
                  issuer_id='E99999', definition='BASIC_EPS', period_start='2026-04-01', period_end='2027-03-31',
                  scope='CONSOLIDATED', accounting_standard='IFRS', adjustment='UNADJUSTED',
                  share_basis='ORDINARY_V1', currency='JPY')
    save_rows(directory / 'vendor_context.csv', [fields], list(fields))
    sign(directory)
    report = finance.write_audit(output, ranked, directory, CUTOFF, [])
    pd.testing.assert_frame_equal(ranked, original)
    assert report['comparison_states'] == {'COMPARABLE_NUMERIC_DISCREPANCY': 1}
    assert report['reassessed_tickers'] == 1
    comparison = pd.read_csv(output / '84_forward_valuation_reassessment.csv').set_index('ticker')
    row = comparison.loc[TICKER]
    assert (row.vendor_eps, row.vendor_reported_per, row.reviewed_forward_per) == (20, 5, 20)
    assert row.score_before > row.score_after and (row.rank_before, row.rank_after) == (1, 2)
    assert comparison.loc['9984.T', 'rank_after'] == 1
    provenance = pd.read_csv(output / '80_vendor_metric_provenance.csv')
    eps = provenance[(provenance.ticker == TICKER) & provenance.snapshot_field.eq('forward_eps')].iloc[0]
    assert eps.verification_status == 'UNVERIFIED_PROVIDER' and eps.period_end == '2027-03-31'
    review = pd.read_csv(output / '82_analyst_metric_reviews.csv').iloc[0]
    assert review.forward_review_status == 'HUMAN_REVIEWED_FORWARD_BASIS'
    original.to_csv(output / '01_all_research_candidates.csv', index=False)
    expected = (output / '01_all_research_candidates.csv').read_bytes()
    finance.write_audit(output, ranked, directory, CUTOFF, [])
    assert expected == (output / '01_all_research_candidates.csv').read_bytes()


def test_memo_requires_applicable_review_and_rejects_bad_or_future_inputs(tmp_path):
    ranked = ranking().iloc[:1]
    ranked.to_csv(tmp_path / '01_all_research_candidates.csv', index=False)
    (tmp_path / '24_research_quality_audit.json').write_text('{}')
    data = tmp_path / 'data'
    data.mkdir()
    decisions = [dict(ticker=TICKER, decision='ACCEPTED', decision_date='2026-11-18',
                      decision_reason='fixture', evidence_urls='https://example.net/fixture',
                      analyst_reviewed_by='fixture', key_counterevidence='fixture',
                      initial_thesis='fixture', revisit_trigger='fixture')]
    save_rows(tmp_path / '26_research_decisions.csv', decisions, list(decisions[0]))
    save_rows(data / 'verified_financials.csv',
              [a_fin(metric, TICKER) for metric in ('revenue', 'operating_income', 'net_income')], FIN_FIELDS)
    save_rows(data / 'valuation_assumptions.csv', [a_dcf(TICKER)], DCF_FIELDS)
    assert enhance(tmp_path, data, asof_date=CUTOFF)['memo_ready_n'] == 0
    assert 'HOLD_FORWARD_INPUT_NOT_REVIEWED' in (tmp_path / '32_research_stage_gate.csv').read_text()
    directory = data / 'financial_evidence'
    source = official(directory)
    sign(directory, quote_share_basis='AFTER_SPLIT')
    assert enhance(tmp_path, data, asof_date=CUTOFF)['memo_ready_n'] == 0
    sign(directory, reviewed_at='2026-11-20')
    assert enhance(tmp_path, data, asof_date=CUTOFF)['memo_ready_n'] == 0
    sign(directory)
    assert enhance(tmp_path, data, asof_date=CUTOFF)['memo_ready_n'] == 1
    (directory / 'originals' / source['source_sha256']).write_bytes(b'Wrong original')
    assert enhance(tmp_path, data, asof_date=CUTOFF)['memo_ready_n'] == 0


def test_legacy_filing_numeric_match_requires_declared_accounting_context(tmp_path):
    source = official(tmp_path, metric='revenue', definition='IFRS_TOTAL_REVENUE', unit='CURRENCY',
                      period_kind='FY', period_start='2025-04-01', period_end='2026-03-31')
    source['statement'] = 'IS'
    for basis in ('', 'JP_GAAP'):
        row, = reconcile([source], [source | {'accounting_standard': basis}], tmp_path / 'originals', CUTOFF)
        assert row['status'] == 'UNVERIFIED'
        assert row['reason'] == 'ACCOUNTING_OR_ADJUSTMENT_MISMATCH_OR_UNRESOLVED'


def test_archived_ranking_command_writes_separate_hashed_audit(tmp_path):
    archived = tmp_path / 'archived.csv'
    ranking().to_csv(archived, index=False)
    raw = archived.read_bytes()
    evidence = tmp_path / 'evidence'
    official(evidence)
    sign(evidence)
    output = tmp_path / 'separate-audit'
    finance.main(['audit-ranked', '--ranked', str(archived), '--asof-date', str(CUTOFF),
                  '--metric-evidence-dir', str(evidence), '--output', str(output)])
    report = json.loads((output / '85_financial_provenance_manifest.json').read_text())
    assert report['ranked_input_sha256'] == sha256(raw).hexdigest()
    assert report['reassessed_tickers'] == 1
    assert archived.read_bytes() == raw
