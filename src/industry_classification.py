"""Versioned, point-in-time security and operating-industry evidence."""
from datetime import date
import re

import pandas as pd

from .gemini_filing import is_public_https
from .scoring_v03 import SECTOR_WEIGHTS


SCHEMA_VERSION = '1'
EXCLUDED = {'SPAC', 'SHELL_OR_SPAC', 'ETF', 'FUND', 'REIT', 'PREFERRED', 'WARRANT', 'DERIVATIVE', 'NON_EQUITY'}
TYPES = EXCLUDED | {'OPERATING_EQUITY', 'UNRESOLVED'}
SOURCE_KINDS = {'OFFICIAL_EXCHANGE', 'OFFICIAL_ISSUER', 'CURATED', 'SOURCE_GROUNDED_GEMINI', 'VENDOR'}


def load_registry(path, cutoff):
    if path is None:
        return {}
    records = {}
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {'ticker', 'issuer_id', 'security_type', 'share_class', 'counter', 'peer_group',
                'source_kind', 'source_url', 'source_date', 'reviewed_by', 'review_date'}
    if not required <= set(frame.columns):
        raise ValueError('Incomplete security classification schema')
    for row in frame.to_dict('records'):
        ticker = row['ticker'].strip().upper()
        if (not ticker or row['source_kind'] not in SOURCE_KINDS
                or row['security_type'] not in TYPES | {''}
                or row['peer_group'] not in set(SECTOR_WEIGHTS) | {'', 'unclassified'}
                or not is_public_https(row['source_url'])):
            raise ValueError(f'Invalid classification evidence for {ticker}')
        published = date.fromisoformat(row['source_date'])
        reviewed = date.fromisoformat(row['review_date']) if row['review_date'] else None
        if published > cutoff:
            continue
        if ticker in records:
            raise ValueError(f'Duplicate in-scope classification evidence for {ticker}')
        row['reviewed'] = (bool(row['reviewed_by'].strip()) and reviewed is not None
                           and published <= reviewed <= cutoff)
        records[ticker] = row
    return records


def vendor_security_type(row):
    quote = str(row.get('vendor_quote_type') or '').strip().upper()
    category = str(row.get('vendor_industry') or '').strip().casefold()
    aliases = {'ETF': 'ETF', 'MUTUALFUND': 'FUND', 'REIT': 'REIT', 'PREFERRED': 'PREFERRED',
               'WARRANT': 'WARRANT', 'OPTION': 'DERIVATIVE', 'FUTURE': 'DERIVATIVE'}
    if quote and quote != 'EQUITY':
        return aliases.get(quote, 'NON_EQUITY')
    if re.match(r'^reit(?:\b|\s*-)', category):
        return 'REIT'
    if category in {'special purpose acquisition companies', 'spac'}:
        return 'SPAC'
    if category == 'shell companies':
        return 'SHELL_OR_SPAC'
    return 'UNRESOLVED'


def classify(row, evidence):
    baseline = row.get('peer_group', 'unclassified')
    sec = vendor_security_type(row)
    origin = row.get('sector_mapping_status', '')
    industry_source = 'CURATED_UNIVERSE' if origin.startswith('CURATED_') else 'VENDOR'
    result = dict(classification_version=SCHEMA_VERSION, legacy_peer_group=baseline,
                  legacy_sector_mapping_status=origin, operating_peer_group=baseline,
                  industry_confidence='UNRESOLVED' if baseline == 'unclassified' else 'PROVISIONAL',
                  industry_source=industry_source,
                  industry_source_url=str(row.get('source_url') or '') if industry_source == 'VENDOR' else '',
                  classification_source_date='', classification_review_date='', classification_reviewed_by='',
                  proposed_peer_group='', proposed_source_kind='', proposed_source_url='', classification_issuer_id='',
                  classification_share_class='', listing_counter='', instrument_class=sec, instrument_source='VENDOR')
    if evidence:
        reviewed = evidence['reviewed']
        result.update(proposed_peer_group=evidence['peer_group'], proposed_source_kind=evidence['source_kind'],
                      proposed_source_url=evidence['source_url'], classification_source_date=evidence['source_date'],
                      classification_review_date=evidence['review_date'],
                      classification_share_class=evidence['share_class'], listing_counter=evidence['counter'])
        if reviewed:
            result.update(classification_issuer_id=evidence['issuer_id'],
                          classification_reviewed_by=evidence['reviewed_by'])
            if evidence['security_type'] and not (sec in EXCLUDED and evidence['security_type'] == 'OPERATING_EQUITY'):
                result.update(instrument_class=evidence['security_type'], instrument_source=evidence['source_kind'])
            if evidence['peer_group'] in SECTOR_WEIGHTS:
                result.update(operating_peer_group=evidence['peer_group'],
                              industry_confidence='HUMAN_REVIEWED', industry_source=evidence['source_kind'],
                              industry_source_url=evidence['source_url'])
        elif evidence['peer_group']:
            result['industry_confidence'] = 'PROPOSED_NEEDS_REVIEW'
    return result


def issuer_representatives(frame):
    """One research representative per reviewed legal issuer; leave every security row in coverage."""
    issuer = frame['classification_issuer_id'].fillna('')
    return frame.loc[issuer.eq('') | ~issuer.duplicated()]
