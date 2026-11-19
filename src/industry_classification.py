"""Versioned, point-in-time security and operating-industry evidence."""
from datetime import date
import re
from urllib.parse import urlsplit

import pandas as pd

from .gemini_filing import is_public_https
from .scoring_v03 import SECTOR_WEIGHTS


SCHEMA_VERSION = '1'
EXCLUDED = {'SPAC', 'SHELL_OR_SPAC', 'ETF', 'FUND', 'REIT', 'PREFERRED', 'WARRANT', 'DERIVATIVE', 'NON_EQUITY'}
TYPES = EXCLUDED | {'OPERATING_EQUITY', 'UNRESOLVED'}
SOURCE_KINDS = {'OFFICIAL_EXCHANGE', 'OFFICIAL_ISSUER', 'CURATED', 'SOURCE_GROUNDED_GEMINI', 'VENDOR'}
CAMPAIGN_LABELS = {
    'semiconductor equipment': 'chip_equipment',
    'semiconductor equipment & materials': 'chip_equipment',
    'semiconductor foundry': 'chip_manufacturing',
    'fabless semiconductors': 'chip_components',
    'semiconductor design': 'chip_components',
    'electronic industrial equipment': 'industrial_electrification',
    'electrical components & equipment': 'industrial_electrification',
    'interactive media & services': 'platforms',
    'interactive home entertainment': 'gaming_media',
    'biotechnology': 'healthcare_biopharma',
    'pharmaceuticals': 'healthcare_biopharma',
    'automobile manufacturers': 'automakers',
    'auto manufacturers': 'automakers',
    'auto parts': 'automakers',
    'automotive parts & equipment': 'automakers',
    'packaged foods': 'consumer_brands',
    'packaged foods & meats': 'consumer_brands',
    'food products': 'consumer_brands',
    'brewers': 'consumer_brands',
    'non-alcoholic beverages': 'consumer_brands',
    'apparel, accessories & luxury goods': 'consumer_brands',
}
AMBIGUOUS_VENDOR_LABELS = {'semiconductors', 'electronic components', 'electrical components'}
EXCHANGE_LABELS = {'食料品': 'consumer_brands', '医薬品': 'healthcare_biopharma',
                   'Foods': 'consumer_brands', 'Pharmaceutical': 'healthcare_biopharma'}
LISTING_EXCLUSIONS = EXCLUDED | {'MUTUALFUND', 'MUTUAL_FUND', 'PREFERRED_STOCK', 'PREFERRED_EQUITY'}


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


def listing_instrument(row):
    """Use explicit instrument labels and exclusions already in listing metadata."""
    label = str(row.get('security_type') or '').strip().upper().replace(' ', '_')
    if label in LISTING_EXCLUSIONS:
        return {'MUTUALFUND': 'FUND', 'MUTUAL_FUND': 'FUND',
                'PREFERRED_STOCK': 'PREFERRED', 'PREFERRED_EQUITY': 'PREFERRED'}.get(label, label)
    if row.get('security_type_status') in {'NON_EQUITY_VENDOR_EXCLUDED', 'REJECT_NON_EQUITY'}:
        return 'NON_EQUITY'
    return None


def campaign_classify(row, result, evidence, observed_at):
    """Map explicit labels and preserve unresolved differences in the audit."""
    def label(value):
        return value.strip() if isinstance(value, str) else ''

    official = (evidence and evidence['issuer_id']
                and evidence['source_kind'] in {'OFFICIAL_EXCHANGE', 'OFFICIAL_ISSUER'}
                and evidence['peer_group'] in SECTOR_WEIGHTS)
    vendor_label = label(row.get('vendor_industry'))
    vendor_sector = label(row.get('vendor_sector'))
    vendor_group = CAMPAIGN_LABELS.get(vendor_label.casefold()) or CAMPAIGN_LABELS.get(vendor_sector.casefold())
    if result['legacy_sector_mapping_status'] == 'VENDOR_HEURISTIC_NEEDS_REVIEW':
        vendor_group = vendor_group or result['legacy_peer_group']
    listing_label = label(row.get('exchange_industry'))
    listing_url = label(row.get('listing_source_url'))
    ambiguous = vendor_label.casefold() in AMBIGUOUS_VENDOR_LABELS
    if ambiguous:
        vendor_group = None
    listing_group = (EXCHANGE_LABELS.get(listing_label) if is_public_https(listing_url)
                     and urlsplit(listing_url).hostname in {'www.jpx.co.jp', 'jpx.co.jp'} else None)
    independent_group = (result['operating_peer_group'] if
                         (result['legacy_sector_mapping_status'] != 'VENDOR_HEURISTIC_NEEDS_REVIEW'
                          or result['industry_confidence'] == 'HUMAN_REVIEWED') else None)
    metadata_groups = {group for group in (
        vendor_group, listing_group, evidence['peer_group'] if official else None,
        independent_group if independent_group in SECTOR_WEIGHTS else None) if group}
    listing_exclusion = label(row.get('campaign_excluded_instrument')) or listing_instrument(row)
    excluded = listing_exclusion or (result['instrument_class'] if result['instrument_class'] in EXCLUDED else None)
    if excluded:
        result.update(operating_peer_group='unclassified', industry_confidence='EXCLUDED_INSTRUMENT',
                      instrument_class=excluded, instrument_source='LISTING' if listing_exclusion else
                      result['instrument_source'])
    elif len(metadata_groups) > 1 and result['industry_confidence'] != 'HUMAN_REVIEWED':
        result.update(operating_peer_group='unclassified', industry_confidence='CONFLICTED')
    elif ambiguous and not metadata_groups:
        result.update(operating_peer_group='unclassified', industry_confidence='UNRESOLVED')
    elif result['industry_confidence'] != 'HUMAN_REVIEWED' and len(metadata_groups) == 1:
        if row.get('vendor_quote_type') == 'EQUITY' or result['instrument_class'] == 'OPERATING_EQUITY':
            exact_industry = CAMPAIGN_LABELS.get(vendor_label.casefold())
            result.update(operating_peer_group=next(iter(metadata_groups)),
                          industry_confidence='AUTO_CLASSIFIED' if exact_industry else 'PROVISIONAL')
            if official:
                result.update(industry_source=evidence['source_kind'], industry_source_url=evidence['source_url'])
            elif listing_group:
                result.update(industry_source='OFFICIAL_EXCHANGE_LABEL', industry_source_url=listing_url,
                              classification_source_date=label(row.get('listing_source_date')))
            elif vendor_group:
                result.update(industry_source='VENDOR', industry_source_url=label(row.get('source_url')))
    result.update(original_vendor_industry=vendor_label, original_vendor_sector=vendor_sector,
                  original_exchange_industry=listing_label, listing_industry_url=listing_url,
                  vendor_classification_url=label(row.get('source_url')) if vendor_label or vendor_sector else '',
                  vendor_security_type_reported=label(row.get('vendor_quote_type')),
                  official_issuer_source_label=label(evidence.get('source_label')) if official else '',
                  listing_classification_source=label(row.get('listing_source_ids')) or label(row.get('discovery_source')),
                  issuer_identity_reported=label(row.get('provider_name')) or label(row.get('company')),
                  issuer_identity_status='REVIEWED_REGISTRY_ID' if result['classification_issuer_id']
                  else 'LISTING_OR_VENDOR_NAME_REQUIRES_VERIFICATION',
                  vendor_classification_observed_at=observed_at if vendor_label or vendor_sector else '',
                  classification_conflicts='|'.join(sorted(metadata_groups)) if len(metadata_groups) > 1 else '',
                  classification_review_required=result['industry_confidence'] != 'HUMAN_REVIEWED' or len(metadata_groups) > 1)
    return result


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
