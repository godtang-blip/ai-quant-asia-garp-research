"""Prepare dossier inputs from verified official documents, with explicit review outcomes."""
import csv
from datetime import date, timedelta
from hashlib import sha256
from io import BytesIO
import json
import re
import unicodedata

import requests
from pypdf import PdfReader
from pypdf.errors import PdfReadError

from .edinet_filings import API
from .gemini_filing import MAX_BYTES, document_identity
from .official_filings import FilingRequest, SourceUnavailable, download, locate_dart_annual_filings, store_original


REQUEST_FIELDS = ('venue', 'ticker', 'issuer_id', 'issuer_name', 'period_start', 'period_end',
                  'publication_date', 'source_url', 'document_id')
APPROVAL_FIELDS = ('ticker', 'source_url', 'issuer_name', 'document_date', 'date_source_url',
                   'document_title', 'expected_sha256')


def search_days(cutoff, supplied):
    if supplied:
        days = sorted(set(date.fromisoformat(item.strip()) for item in supplied.split(',')), reverse=True)
        if len(days) > 20 or any(day > cutoff for day in days):
            raise ValueError('Set at most 20 distinct EDINET index dates on or before the cutoff')
        return days
    year = cutoff.year if cutoff >= date(cutoff.year, 6, 30) else cutoff.year - 1
    seasonal = {date(year, 6, day) for day in range(19, 31)}
    return sorted(seasonal | {cutoff - timedelta(days=offset) for offset in range(5)}, reverse=True)


def read_indexes(session, key, days):
    entries, failures = [], []
    for day in days:
        day = day.isoformat()
        try:
            raw, _ = download(session, f'{API}.json', params={
                'date': day, 'type': '2', 'Subscription-Key': key}, limit=12_000_000)
            data = json.loads(raw)
            if str(data.get('metadata', {}).get('status')) != '200' or not isinstance(data.get('results'), list):
                raise SourceUnavailable('EDINET_INDEX_INVALID_RESPONSE')
            entries.extend(row for row in data['results'] if isinstance(row, dict)
                           and str(row.get('submitDateTime', ''))[:10] == day)
        except (ValueError, AttributeError) as exc:
            reason = str(exc) if isinstance(exc, SourceUnavailable) else 'EDINET_INDEX_INVALID_RESPONSE'
            failures.append({'date': day, 'reason': reason})
            if reason.startswith(('PROXY_', 'ORIGIN_HTTP_401', 'ORIGIN_HTTP_403', 'ORIGIN_HTTP_429')):
                break
    return entries, failures


def annual_requests(candidate, entries, cutoff):
    ticker = candidate['ticker']
    by_id = {}
    for item in entries:
        if (item.get('secCode') != ticker.removesuffix('.T') + '0' or item.get('docTypeCode') != '120'
                or item.get('withdrawalStatus') != '0' or item.get('disclosureStatus') != '0'
                or not re.fullmatch(r'E\d{5}', item.get('edinetCode') or '')
                or not re.fullmatch(r'S[0-9A-Z]{7}', item.get('docID') or '')):
            continue
        row = dict(venue='JPX', ticker=ticker, issuer_id=item['edinetCode'], issuer_name=item.get('filerName') or '',
                   period_start=item.get('periodStart'), period_end=item.get('periodEnd'),
                   publication_date=item['submitDateTime'][:10], document_id=item['docID'],
                   source_url=f"{API}/{item['docID']}?type=1")
        try:
            FilingRequest.from_row(row, cutoff)
        except (ValueError, TypeError):
            continue
        by_id[item['docID']] = (row, item)
    return sorted(by_id.values(), key=lambda pair: pair[0]['period_end'], reverse=True)


def verify_pdf(raw, request):
    if not raw.startswith(b'%PDF-') or len(raw) > MAX_BYTES:
        raise SourceUnavailable('GEMINI_ORIGINAL_NOT_PDF')
    try:
        cover = (PdfReader(BytesIO(raw)).pages[0].extract_text() or '')[:8000]
    except (PdfReadError, IndexError, ValueError):
        raise SourceUnavailable('GEMINI_PDF_COVER_UNREADABLE') from None
    if document_identity(request['issuer_name'], cover) != 'OPERATOR_ISSUER_NAME_FOUND_IN_FRONT_MATTER':
        raise SourceUnavailable('GEMINI_PDF_ISSUER_NEEDS_REVIEW')
    cover = ''.join(unicodedata.normalize('NFKC', cover).split())
    if '有価証券報告書' not in cover:
        raise SourceUnavailable('GEMINI_PDF_ANNUAL_TYPE_NEEDS_REVIEW')
    period = re.search(r'事業年度.{0,150}', cover)
    dates = [date.fromisoformat(request[field]) for field in ('period_start', 'period_end')]
    if not period or any(not re.search(rf'{day.year}年0?{day.month}月0?{day.day}日', period[0]) for day in dates):
        raise SourceUnavailable('GEMINI_PDF_PERIOD_NEEDS_REVIEW')


def prepare_inputs(output, source_dir, selected, cutoff, budget, keys, *, index_dates='', official=True, gemini=True):
    output.mkdir(parents=True, exist_ok=True)
    requests_out, approvals, outcomes, originals = [], [], [], {}
    targets = selected[:budget]
    japanese = [row for row in targets if row['market'] == 'Japan']
    key = keys.get('EDINET_API_KEY')
    days = search_days(cutoff, index_dates) if japanese and key else []
    korean = [row['ticker'] for row in targets if row['market'] == 'Korea']
    dart_leads = {row['ticker']: row for row in locate_dart_annual_filings(
        korean, keys.get('DART_API_KEY'), cutoff, len(korean))}
    with requests.Session() as session:
        entries, failures = read_indexes(session, key, days) if days else ([], [])
        for position, candidate in enumerate(selected, 1):
            ticker = candidate['ticker']
            result = {'ticker': ticker, 'company': candidate['company'], 'market': candidate['market'],
                      'shortlist_position': position, 'status': 'REVIEW_REQUIRED'}
            outcomes.append(result)
            if position > budget:
                result.update(status='NOT_ATTEMPTED', reason='FILING_BUDGET_EXHAUSTED')
                continue
            if candidate['market'] == 'Korea':
                lead = dart_leads[ticker]
                result.update(dart_annual_index=lead, reason='DART_ORIGINAL_AND_ANNUAL_PERIOD_REQUIRE_REVIEW')
                if lead['status'] == 'BLOCKED':
                    reason = lead['reason']
                    result['reason'] = reason
                    if reason == 'DART_API_KEY_MISSING' or reason.startswith(('DART_ISSUER_MAP_', 'DART_ANNUAL_LIST_')):
                        result['status'] = 'INACCESSIBLE'
                continue
            if candidate['market'] != 'Japan':
                result['reason'] = 'NO_VERIFIED_AUTOMATED_ANNUAL_ORIGINAL_ROUTE'
                continue
            if not key:
                result.update(status='INACCESSIBLE', reason='EDINET_API_KEY_MISSING')
                continue
            rows = annual_requests(candidate, entries, cutoff)
            if not rows:
                result.update(status='INACCESSIBLE' if failures else 'REVIEW_REQUIRED',
                              reason=failures[-1]['reason'] if failures else 'EDINET_ANNUAL_NOT_FOUND_IN_BOUNDED_INDEX',
                              index_failures=failures)
                continue
            request, meta = rows[0]
            result['filing_lead'] = request
            if any(row['period_end'] == request['period_end'] for row, _ in rows[1:]):
                result['reason'] = 'EDINET_MULTIPLE_ANNUALS_FOR_PERIOD'
                continue
            if official and meta.get('xbrlFlag') == '1':
                requests_out.append(request)
                result['official_request_status'] = 'VERIFIED_PUBLISHER_INDEX_XBRL_REQUEST'
            if not gemini:
                result.update(status='VERIFIED_OFFICIAL_INDEX', reason='EXPLICIT_GEMINI_INPUT_CONFIGURED')
                continue
            if meta.get('pdfFlag') != '1':
                result['reason'] = 'EDINET_PDF_UNAVAILABLE'
                continue
            locator = f"{API}/{request['document_id']}"
            result['pdf_source_url'] = locator + '?type=2'
            try:
                raw, _ = download(session, locator, params={'type': '2', 'Subscription-Key': key}, limit=MAX_BYTES)
            except SourceUnavailable as exc:
                result.update(status='INACCESSIBLE', reason=str(exc))
                continue
            try:
                verify_pdf(raw, request)
            except SourceUnavailable as exc:
                result['reason'] = str(exc)
                continue
            digest = sha256(raw).hexdigest()
            store_original(source_dir, digest, raw)
            originals[ticker] = source_dir / digest
            approvals.append(dict(ticker=ticker, source_url=locator + '?type=2', issuer_name=request['issuer_name'],
                                  document_date=request['publication_date'], date_source_url=f"{API}.json?type=2&date={request['publication_date']}",
                                  document_title='EDINET annual securities report', expected_sha256=digest))
            result.update(status='AUTO_VERIFIED_OFFICIAL_ORIGINAL', pdf_sha256=digest)
    for name, header, rows in [('official_filing_requests.csv', REQUEST_FIELDS, requests_out),
                               ('gemini_approved_sources.csv', APPROVAL_FIELDS, approvals)]:
        if rows:
            with (output / name).open('w', encoding='utf-8', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=header)
                writer.writeheader()
                writer.writerows(rows)
    (output / 'review.json').write_text(json.dumps(
        {'edinet_index_dates': [str(day) for day in days], 'outcomes': outcomes},
        ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return originals
