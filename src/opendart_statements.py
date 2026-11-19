"""Fetch explicitly scheduled OpenDART annual consolidated statements."""
from datetime import date
from hashlib import sha256
import json
import os
import re

import requests


ENDPOINT = 'https://opendart.fss.or.kr/api/fnlttSinglAcntAll.json'
MAX_RESPONSE = 8_000_000
TAXONOMY = {
    ('IS', 'ifrs-full_Revenue'): 'revenue',
    ('CIS', 'ifrs-full_Revenue'): 'revenue',
    ('IS', 'dart_OperatingIncomeLoss'): 'operating_income',
    ('CIS', 'dart_OperatingIncomeLoss'): 'operating_income',
    ('IS', 'ifrs-full_ProfitLossAttributableToOwnersOfParent'): 'attributable_net_income',
    ('CIS', 'ifrs-full_ProfitLossAttributableToOwnersOfParent'): 'attributable_net_income',
    ('IS', 'ifrs-full_DilutedEarningsLossPerShare'): 'diluted_eps',
    ('CIS', 'ifrs-full_DilutedEarningsLossPerShare'): 'diluted_eps',
    ('CF', 'ifrs-full_CashFlowsFromUsedInOperatingActivities'): 'operating_cash_flow',
    ('BS', 'ifrs-full_Assets'): 'assets',
    ('BS', 'ifrs-full_Liabilities'): 'liabilities',
    ('BS', 'ifrs-full_Equity'): 'equity',
    ('BS', 'ifrs-full_CashAndCashEquivalents'): 'cash',
}


def normalize_statement(payload, document, digest, cutoff):
    corp_code = document['issuer_id']
    receipt = document['receipt_number']
    start = date.fromisoformat(document['period_start'])
    end = date.fromisoformat(document['period_end'])
    published = date.fromisoformat(document['publication_date'])
    if not re.fullmatch(r'[0-9]{8}', corp_code) or not re.fullmatch(r'[0-9]{14}', receipt):
        raise ValueError('INVALID_DART_IDENTIFIER')
    if (not start <= end <= published <= cutoff or
            published.strftime('%Y%m%d') != receipt[:8] or not 350 <= (end - start).days <= 380):
        raise ValueError('INVALID_DART_FILING_DATES')
    if payload.get('status') != '000' or not isinstance(payload.get('list'), list):
        raise ValueError('OPENDART_NO_STATEMENTS')
    rows = []
    for index, account in enumerate(payload['list']):
        statement = account.get('sj_div')
        account_id = account.get('account_id')
        metric = TAXONOMY.get((statement, account_id))
        if not metric:
            continue
        if (account.get('rcept_no') != receipt or account.get('corp_code') != corp_code
                or account.get('bsns_year') != str(end.year) or account.get('reprt_code') != '11011'):
            raise ValueError('OPENDART_RECEIPT_OR_ISSUER_MISMATCH')
        amount = account.get('thstrm_amount', '').replace(',', '').strip()
        if not re.fullmatch(r'[+-]?[0-9]+(?:\.[0-9]+)?', amount):
            continue
        rows.append({
            'ticker': document['ticker'], 'issuer_id': corp_code, 'issuer_name': document['issuer_name'],
            'market': 'Korea', 'venue': 'KRX', 'metric': metric, 'definition': account_id,
            'statement': statement, 'period_start': str(end if statement == 'BS' else start),
            'period_end': str(end), 'period_kind': 'INSTANT' if statement == 'BS' else 'FY',
            'scope': 'CONSOLIDATED', 'currency': account.get('currency', ''), 'value': amount,
            'unit': 'CURRENCY_PER_SHARE' if metric == 'diluted_eps' else 'CURRENCY', 'scale': '1',
            'publication_date': str(published),
            'source_url': f'https://dart.fss.or.kr/dsaf001/main.do?rcpNo={receipt}',
            'source_locator': f'API list[{index}].thstrm_amount ({statement}/{account_id})',
            'source_sha256': digest, 'provider_version': 'OpenDART-fnlttSinglAcntAll',
            'parser_version': '1',
        })
    return rows


def fetch_statement(session, document, key, cutoff, source_dir):
    end = date.fromisoformat(document['period_end'])
    with session.get(ENDPOINT, params={'crtfc_key': key, 'corp_code': document['issuer_id'],
                     'bsns_year': end.year, 'reprt_code': '11011', 'fs_div': 'CFS'},
                     timeout=(5, 15), stream=True, allow_redirects=False) as response:
        if response.status_code != 200:
            raise ValueError('OPENDART_HTTP_FAILURE')
        body = bytearray()
        for chunk in response.iter_content(65536):
            body.extend(chunk)
            if len(body) > MAX_RESPONSE:
                raise ValueError('OPENDART_RESPONSE_SIZE_LIMIT')
    digest = sha256(body).hexdigest()
    rows = normalize_statement(json.loads(body), document, digest, cutoff)
    if rows:
        source_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = source_dir / digest
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            if sha256(path.read_bytes()).hexdigest() != digest:
                raise ValueError('OPENDART_EXISTING_SOURCE_CHECKSUM_MISMATCH')
        else:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(body)
    return rows
