"""Assemble analyst evidence packets from the existing research pipeline."""
from hashlib import sha256
from html import escape
import json
import re
from urllib.parse import urlsplit

import pandas as pd

from .filing_evidence import SOURCES, VENUE_SUFFIXES
from .gemini_filing import EXCERPT_CATEGORIES, is_public_https
from .research_quality import DCF_FIELDS, REQUIRED_MEMO_TEXT, dcf_per_share
from .scoring_v03 import SUBMETRICS


def records(root, name, ticker=None):
    path = root / name
    if not path.is_file():
        return []
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if ticker is not None:
        frame = frame[frame.ticker.eq(ticker)]
    return frame.to_dict('records')


def select_candidates(root, limit):
    # Reuse the engine's issuer-deduplicated, screening-eligible shortlist.
    return records(root, '02_research_shortlist.csv')[:limit]


def official_url(ticker, url):
    if not is_public_https(url):
        return False
    host = urlsplit(url).hostname
    return any(ticker.endswith(VENUE_SUFFIXES[venue]) and
               any(host == domain or host.endswith('.' + domain) for domain in domains)
               for venue, (_, _, domains) in SOURCES.items())


def valuation_workspace(root, ticker, cutoff):
    row = next(iter(records(root, '31_valuation_scenario_audit.csv', ticker)), {})
    inputs = dict.fromkeys(DCF_FIELDS, '')
    inputs['ticker'] = ticker
    if row.get('asof_date') and row['asof_date'] <= cutoff:
        inputs.update({field: row[field] for field in DCF_FIELDS if field in row and field not in REQUIRED_MEMO_TEXT})
    valuation = {'status': row.get('valuation_status', 'NO_REVIEWED_INPUTS'),
                 'flags': row.get('valuation_flags', ''), 'scenarios': {}, 'sensitivity': []}
    if valuation['status'] != 'MODELED_MANUAL_INPUT_REVIEWED':
        return inputs, valuation
    valuation['scenarios'] = dcf_per_share(inputs)
    # Sensitivity changes only the analyst-provided discount rate.
    for delta in (-0.01, 0.0, 0.01):
        rate = round(float(inputs['discount_rate']) + delta, 6)
        scenario = {'discount_rate': rate}
        try:
            scenario.update(dcf_per_share({**inputs, 'discount_rate': str(rate)}))
        except ValueError:
            scenario['status'] = 'OUTSIDE_EXISTING_MODEL_CONSTRAINTS'
        valuation['sensitivity'].append(scenario)
    return inputs, valuation


def write_dossiers(output, selected, audit, gemini, manifest):
    directory = output / '71_research_dossiers'
    directory.mkdir(exist_ok=True)
    index = {'status': 'GENERATED' if selected else 'BLOCKED_NO_SCREENING_ELIGIBLE_CANDIDATE',
             'run_status': manifest['run_status'], 'selection_source': '02_research_shortlist.csv',
             'dossiers': [],
             'official_acquisition_status': (
                 'BLOCKED_NO_SCREENING_ELIGIBLE_CANDIDATE' if not selected else
                 'LIVE_DOCUMENTS_RETRIEVED' if any(row['document_retrieved'] for row in manifest['filing_attempts']) else
                 'REPLAY_ONLY' if any(row['acquisition'] == 'OFFICIAL_REPLAY' for row in audit) else
                 'BLOCKED_NO_OFFICIAL_DOCUMENT'),
             'gemini_status': gemini.get('validation_status', gemini['status']),
             'gemini_blockers': gemini.get('blockers', []),
             'financial_failures': manifest['failed_fetch_reasons']}
    inputs = []
    names = ('02_research_shortlist.csv', '11_discovery_universe.csv', '12_discovery_sources_log.csv',
             '18_evidence_ledger.csv', '20_vendor_quarterly_earnings.csv', '30_primary_financial_reconciliation.csv',
             '31_valuation_scenario_audit.csv', '32_research_stage_gate.csv', '62_numerical_reconciliation.csv',
             '63_gemini_evidence.json')
    hashes = {name: sha256((output / name).read_bytes()).hexdigest()
              for name in names if (output / name).is_file()}
    metrics = ['revenue_total_raw', 'free_cashflow_raw',
               *(field for group in SUBMETRICS.values() for field in group)]
    for position, candidate in enumerate(selected, 1):
        ticker = candidate['ticker']
        key = f'{position:02d}-' + re.sub(r'[^A-Za-z0-9_.-]', '_', ticker)
        stage = next(iter(records(output, '32_research_stage_gate.csv', ticker)), {})
        valuation_inputs, valuation = valuation_workspace(output, ticker, manifest['asof_date'])
        inputs.append(valuation_inputs)
        attempts = [row for row in manifest['filing_attempts'] if row['ticker'] == ticker]
        leads = [row for row in manifest['official_filing_leads'] if row['ticker'] == ticker]
        filings = [row for row in audit if row['ticker'] == ticker]
        ledger = records(output, '18_evidence_ledger.csv', ticker)
        model_run = next((row for row in gemini.get('companies', []) if row['ticker'] == ticker), {})
        model_findings = [row for row in gemini.get('observations', []) if row['ticker'] == ticker]
        excerpts = [row for row in gemini.get('qualitative_findings', []) if row['ticker'] == ticker]
        blockers = [reason for reason in stage.get('blocking_reasons', '').split('|') if reason]
        if not attempts:
            blockers.append('PRIMARY_FILING_REQUEST_REQUIRED: confirm legal issuer, annual period and official source')
        blockers.extend(item['reason'] for item in attempts + leads if item.get('reason'))
        if not any(row['status'] == 'MACHINE_RECONCILED' for row in filings):
            blockers.append('NO_MACHINE_RECONCILIATION: supply comparable independent financial observations')
        if not model_findings and not excerpts:
            blockers.append('GEMINI: ' + (model_run.get('status') or gemini.get('reason') or gemini['status']))
        missing_categories = set(EXCERPT_CATEGORIES) - {row['category'] for row in excerpts}
        if missing_categories:
            blockers.append('REVIEW_SOURCE_EVIDENCE: ' + ', '.join(sorted(missing_categories)))
        if not valuation['scenarios']:
            blockers.append('VALUATION: review sourced inputs in valuation_inputs.csv')
        valuation['inputs'] = {key: value for key, value in valuation_inputs.items()
                               if value and key not in REQUIRED_MEMO_TEXT and key != 'ticker'}
        identity = {field: candidate.get(field, '') for field in
                    ('ticker', 'company', 'market', 'classification_issuer_id', 'peer_group',
                     'industry_source', 'industry_source_url', 'industry_confidence', 'security_type_status')}
        payload = {'candidate': identity, 'shortlist_position': position,
                   'screening': {field: candidate.get(field, '') for field in
                                 ('cross_industry_score_100', 'score_method', 'score_coverage', 'v031_research_eligible',
                                  'v031_research_status', 'data_quality_flags', 'discovery_source', 'listing_source_ids',
                                  'industry_thesis', 'retrieved_at_utc')},
                   'historical_vendor': {'status': 'UNVERIFIED_VENDOR', 'url': candidate.get('source_url', ''),
                                         'currency': candidate.get('financial_currency', ''),
                                         'period_end': candidate.get('provider_financial_period_end', ''),
                                         'metrics': {field: candidate[field] for field in metrics if candidate.get(field)},
                                         'quarters': records(output, '20_vendor_quarterly_earnings.csv', ticker)},
                   'official_attempts': attempts, 'official_filing_leads': leads, 'primary_observations': filings,
                   'human_attested_inputs': records(output, '30_primary_financial_reconciliation.csv', ticker),
                   'evidence_ledger': ledger,
                   'gemini': {'execution': model_run, 'observations': model_findings, 'excerpts': excerpts},
                   'valuation': valuation, 'review_checklist': list(dict.fromkeys(blockers)),
                   'reproducibility': {'commit': manifest['commit'], 'run_status': manifest['run_status'],
                                       'asof_date': manifest['asof_date'], 'artifact_sha256': hashes,
                                       'financial_data_mode': manifest['outcomes']['financial_data_mode'],
                                       'market_coverage': next((row for row in manifest['coverage']
                                                                if row['market'] == candidate['market']), {}),
                                       'gemini': manifest['gemini']}}
        (directory / f'{key}.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        write_markdown(directory / f'{key}.md', payload)
        index['dossiers'].append({'ticker': ticker, 'markdown': f'{key}.md', 'manifest': f'{key}.json'})
    pd.DataFrame(inputs, columns=DCF_FIELDS).to_csv(directory / 'valuation_inputs.csv', index=False)
    (directory / 'index.json').write_text(json.dumps(index, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return index


def write_markdown(path, dossier):
    def cell(value):
        return escape(str(value if value is not None else '')).replace('|', '&#124;').replace('\n', ' ').replace('\r', ' ')

    c, s = dossier['candidate'], dossier['screening']
    context = dossier['reproducibility']
    lines = [f'# Research Dossier · {cell(c["company"])} ({cell(c["ticker"])})', '',
             'This evidence packet is for analyst review. The investment thesis and approval belong to the analyst.', '',
             '## Candidate origin and screening',
             f'- GARP shortlist position {dossier["shortlist_position"]}, score {cell(s["cross_industry_score_100"])} '
             f'with coverage {cell(s["score_coverage"])}. {cell(s["v031_research_status"])}.',
             f'- Listing source {cell(s["discovery_source"])}. {cell(s["listing_source_ids"])}.',
             f'- Peer group {cell(c["peer_group"])} ({cell(c["industry_confidence"])}). {cell(c["industry_source_url"])}.',
             f'- Screening warnings {cell(s["data_quality_flags"]) or "none reported"}.', '',
             '## Business, growth and competitive position',
             f'- Curated research lead (unverified) · {cell(s["industry_thesis"]) or "None recorded"}.',
             '- Verify segment economics, customer exposure and competitive claims against the filing excerpts.',
             '', '## Historical financial observations',
             f'- Vendor inputs are unverified. Currency {cell(dossier["historical_vendor"]["currency"]) or "unknown"}, '
             f'provider period {cell(dossier["historical_vendor"]["period_end"]) or "unknown"}. '
             f'{cell(dossier["historical_vendor"]["url"])}.']
    lines.extend(f'- {cell(metric)} · {cell(value)}' for metric, value in dossier['historical_vendor']['metrics'].items())
    lines.extend(['', '### Primary-source reconciliation'])
    for row in dossier['primary_observations']:
        lines.append(f'- {cell(row["metric"])} · {cell(row.get("value"))} {cell(row.get("currency"))}, '
                     f'unit {cell(row.get("unit"))}, scale {cell(row.get("scale"))}; '
                     f'{cell(row.get("period_start"))} to {cell(row.get("period_end"))}, {cell(row.get("scope"))}. '
                     f'{cell(row.get("evidence_state"))} {cell(row.get("reason"))}. '
                     f'{cell(row.get("source_url"))}, {cell(row.get("source_locator"))}, SHA-256 {cell(row.get("source_sha256"))}.')
    if not dossier['primary_observations']:
        lines.append('- No primary observations in this run.')
    for lead in dossier['official_filing_leads']:
        issuer = lead.get('official_issuer', {})
        for filing in lead.get('filings', []):
            lines.append(f'- OpenDART annual index (metadata only) · {cell(issuer.get("corp_name"))} '
                         f'{cell(issuer.get("corp_code"))} · {cell(filing.get("published_date"))} '
                         f'{cell(filing.get("title"))} · {cell(filing.get("source_url"))}.')
    for row in dossier['evidence_ledger']:
        if row['evidence_type'] == 'REGULATOR_FILING':
            lines.append(f'- Official index lead · {cell(row["title"])} ({cell(row["published_date"])}). '
                         f'{cell(row["verification_status"])} · {cell(row["source_url"])}.')
    execution = dossier['gemini']['execution']
    lines.extend(['', '## Gemini findings', f'- Execution · {cell(execution.get("status")) or "See checklist"}'])
    for row in dossier['gemini']['observations'] + dossier['gemini']['excerpts']:
        lines.append(f'- {cell(row.get("metric_label") or row.get("category"))} · {cell(row["evidence_state"])}. '
                     f'{cell(row.get("classification_status") or row.get("verification_status"))}. '
                     f'{cell(row["source_location"])} · {cell(row["source_url"])} · SHA-256 {cell(row["document_sha256"])}. '
                     f'Excerpt: “{cell(row["supporting_text"])}”')
    lines.append(f'- Unsupported proposals withheld: {execution.get("rejected_proposals", 0) + execution.get("rejected_excerpt_proposals", 0)}.')
    lines.extend(['', '## Risks, counterevidence and falsification',
                  '- Review the risk and counterevidence excerpts. Record material contradictions and observable falsification conditions.',
                  '', '## Valuation workspace',
                  f'- {cell(dossier["valuation"]["status"])}. Edit valuation_inputs.csv.'])
    lines.extend(f'- {cell(field)} · {cell(value)}' for field, value in dossier['valuation']['inputs'].items())
    if dossier['valuation']['scenarios']:
        lines.append('- Illustrative analyst-input sensitivity, per share in the declared currency.')
    for scenario in dossier['valuation']['sensitivity']:
        lines.append(f'- Discount rate {scenario["discount_rate"]}; Bear / Base / Bull · ' + ' / '.join(
            cell(scenario.get(f'intrinsic_{label}', scenario.get('status', ''))) for label in ('bear', 'base', 'bull')))
    lines.extend(['', '## Missing data and analyst checklist'])
    lines.extend(f'- [ ] {cell(item)}' for item in dossier['review_checklist'])
    lines.extend(['', '## Reproducibility',
                  f'- Commit {context["commit"]}, cutoff {context["asof_date"]}, status {context["run_status"]}.',
                  f'- Financial mode {context["financial_data_mode"]}. Market coverage and input hashes are in the companion JSON.'])
    path.write_text('\n'.join(lines) + '\n', encoding='utf-8')
