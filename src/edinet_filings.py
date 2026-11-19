"""EDINET API v2 securities reports and conservative annual XBRL extraction."""
from collections import Counter
from decimal import Decimal, InvalidOperation
from io import BytesIO
import json
import re
from zipfile import BadZipFile, ZipFile

from lxml import etree


API = 'https://api.edinet-fsa.go.jp/api/v2/documents'
EDINET_IDENTIFIER_SCHEME = 'http://disclosure.edinet-fsa.go.jp'
XBRL = 'http://www.xbrl.org/2003/instance'
ISO4217 = 'http://www.xbrl.org/2003/iso4217'
TAXONOMY = {
    'NetSales': ('jppfs', 'revenue', 'IS'),
    'OperatingIncome': ('jppfs', 'operating_income', 'IS'),
    'ProfitLossAttributableToOwnersOfParent': ('jppfs ifrs', 'attributable_net_income', 'IS'),
    'NetCashProvidedByUsedInOperatingActivities': ('jppfs', 'operating_cash_flow', 'CF'),
    'Assets': ('jppfs ifrs', 'assets', 'BS'),
    'Liabilities': ('jppfs ifrs', 'liabilities', 'BS'),
    'NetAssets': ('jppfs', 'equity', 'BS'),
    'CashAndDeposits': ('jppfs', 'cash', 'BS'),
    'Revenue': ('jpigp ifrs', 'revenue', 'IS'),
    'RevenueIFRS': ('jpigp', 'revenue', 'IS'),
    'OperatingProfitLoss': ('ifrs', 'operating_income', 'IS'),
    'OperatingProfitLossIFRS': ('jpigp', 'operating_income', 'IS'),
    'ProfitLossAttributableToOwnersOfParentIFRS': ('jpigp', 'attributable_net_income', 'IS'),
    'CashFlowsFromUsedInOperatingActivities': ('ifrs', 'operating_cash_flow', 'CF'),
    'CashFlowsFromUsedInOperatingActivitiesIFRS': ('jpigp', 'operating_cash_flow', 'CF'),
    'AssetsIFRS': ('jpigp', 'assets', 'BS'),
    'LiabilitiesIFRS': ('jpigp', 'liabilities', 'BS'),
    'Equity': ('ifrs', 'equity', 'BS'),
    'EquityIFRS': ('jpigp', 'equity', 'BS'),
    'CashAndCashEquivalents': ('ifrs', 'cash', 'BS'),
    'CashAndCashEquivalentsIFRS': ('jpigp', 'cash', 'BS'),
}


class EDINETError(ValueError):
    """A fixed, credential-free EDINET diagnostic."""


def fetch_edinet(fetch, filing, key):
    if not re.fullmatch(r'E\d{5}', filing.issuer_id):
        raise EDINETError('INVALID_EDINET_ISSUER_CODE')
    if filing.document_id and not re.fullmatch(r'S[0-9A-Z]{7}', filing.document_id):
        raise EDINETError('INVALID_EDINET_DOCUMENT_ID')
    raw, _ = fetch(f'{API}.json', params={'date': str(filing.publication_date), 'type': '2',
                                         'Subscription-Key': key}, limit=12_000_000)
    index = json.loads(raw)
    if str(index.get('metadata', {}).get('status')) != '200' or not isinstance(index.get('results'), list):
        raise EDINETError('EDINET_INDEX_UNAVAILABLE')
    symbol = filing.ticker.removesuffix('.T')
    candidates = [
        row['docID'] for row in index['results']
        if (isinstance(row, dict) and row.get('edinetCode') == filing.issuer_id
            and row.get('secCode') == symbol + '0'
            and row.get('docTypeCode') == '120'
            and row.get('xbrlFlag') == '1'
            and row.get('periodStart') == str(filing.period_start)
            and row.get('periodEnd') == str(filing.period_end)
            and str(row.get('submitDateTime', ''))[:10] == str(filing.publication_date)
            and row.get('withdrawalStatus') == '0'
            and row.get('disclosureStatus') == '0'
            and re.fullmatch(r'S[0-9A-Z]{7}', row.get('docID') or '')
            and (not filing.document_id or filing.document_id == row.get('docID')))
    ]
    if len(candidates) != 1:
        raise EDINETError('EDINET_ANNUAL_DOCUMENT_NOT_UNIQUE')
    url = f'{API}/{candidates[0]}'
    raw, _ = fetch(url, params={'type': '1', 'Subscription-Key': key})
    return raw, url + '?type=1', parse_xbrl


def taxonomy(namespace):
    match = re.fullmatch(r'https?://disclosure\.edinet-fsa\.go\.jp/taxonomy/'
                         r'(jppfs|jpigp|jpdei)/\d{4}-\d{2}-\d{2}/\1_cor', namespace or '')
    if match:
        return match[1]
    if re.fullmatch(r'https?://xbrl\.ifrs\.org/taxonomy/\d{4}-\d{2}-\d{2}/ifrs-full', namespace or ''):
        return 'ifrs'
    return ''


def instance(raw):
    try:
        with ZipFile(BytesIO(raw)) as archive:
            candidates = [entry for entry in archive.infolist()
                          if re.fullmatch(r'XBRL/PublicDoc/[^/]+\.xbrl', entry.filename)]
            if len(candidates) != 1 or candidates[0].file_size > 24_000_000:
                raise EDINETError('EDINET_PUBLIC_XBRL_MISSING_AMBIGUOUS_OR_OVERSIZE')
            body = archive.read(candidates[0])
    except (BadZipFile, RuntimeError, NotImplementedError):
        raise EDINETError('EDINET_DOWNLOAD_IS_NOT_AN_XBRL_ARCHIVE') from None
    parser = etree.XMLParser(resolve_entities=False, no_network=True, load_dtd=False)
    try:
        root = etree.fromstring(body, parser)
    except etree.XMLSyntaxError:
        raise EDINETError('EDINET_XML_PARSE_FAILED') from None
    if root.getroottree().docinfo.doctype or root.tag != f'{{{XBRL}}}xbrl':
        raise EDINETError('EDINET_INVALID_XBRL_ROOT')
    return root, candidates[0].filename


def issuer_context(context, filing, ns):
    if context is None:
        return False
    identifier = context.find('x:entity/x:identifier', ns)
    # EDINET uses -000 for the filing issuer. Other suffixes are separate
    # identifiers and must not be mapped to the issuer by prefix.
    return (identifier is not None and identifier.get('scheme') == EDINET_IDENTIFIER_SCHEME
            and identifier.text in {filing.issuer_id, f'{filing.issuer_id}-000'}
            and context.find('x:entity/x:segment', ns) is None
            and context.find('x:scenario', ns) is None)


def parse_xbrl(raw, filing):
    root, filename = instance(raw)
    ns = {'x': XBRL}
    contexts = {element.get('id'): element for element in root.findall('x:context', ns)}
    units = {element.get('id'): element for element in root.findall('x:unit', ns)}
    if (len(contexts) != len(root.findall('x:context', ns)) or
            len(units) != len(root.findall('x:unit', ns))):
        raise EDINETError('EDINET_DUPLICATE_XBRL_CONTEXT_OR_UNIT')
    consolidated = []
    scope_context = contexts.get('FilingDateInstant')
    if (not issuer_context(scope_context, filing, ns) or
            scope_context.findtext('x:period/x:instant', namespaces=ns) != str(filing.publication_date)):
        raise EDINETError('EDINET_CONSOLIDATED_SCOPE_UNCONFIRMED')
    for fact in root:
        if not isinstance(fact.tag, str):
            continue
        name = etree.QName(fact)
        if (name.localname == 'WhetherConsolidatedFinancialStatementsArePreparedDEI'
                and taxonomy(name.namespace) == 'jpdei' and fact.get('contextRef') == 'FilingDateInstant'):
            consolidated.append((fact.text or '').strip())
    if set(consolidated) != {'true'} and set(consolidated) != {'1'}:
        raise EDINETError('EDINET_CONSOLIDATED_SCOPE_UNCONFIRMED')
    rows = []
    for fact in root:
        if not isinstance(fact.tag, str):
            continue
        qname = etree.QName(fact)
        mapped = TAXONOMY.get(qname.localname)
        if mapped is None:
            continue
        families, metric, statement = mapped
        family = taxonomy(qname.namespace)
        if family not in families.split():
            continue
        context_id = fact.get('contextRef')
        instant = statement == 'BS'
        if context_id != ('CurrentYearInstant' if instant else 'CurrentYearDuration'):
            continue
        context = contexts.get(context_id)
        if not issuer_context(context, filing, ns):
            continue
        period = context.find('x:period', ns)
        if period is None:
            continue
        end = period.findtext('x:instant' if instant else 'x:endDate', namespaces=ns)
        start = end if instant else period.findtext('x:startDate', namespaces=ns)
        if end != str(filing.period_end) or start != str(filing.period_end if instant else filing.period_start):
            continue
        unit = units.get(fact.get('unitRef'))
        if unit is None or len(unit) != 1 or unit[0].tag != f'{{{XBRL}}}measure':
            continue
        prefix, _, currency = (unit[0].text or '').strip().partition(':')
        if unit[0].nsmap.get(prefix) != ISO4217 or not re.fullmatch('[A-Z]{3}', currency):
            continue
        try:
            value = Decimal((fact.text or '').strip())
        except InvalidOperation:
            continue
        if not value.is_finite():
            continue
        rows.append(dict(metric=metric, definition=qname.localname, statement=statement,
                         period_start=start, period_end=end, period_kind='INSTANT' if instant else 'FY',
                         scope='CONSOLIDATED', currency=currency, unit='CURRENCY', scale='1',
                         accounting_standard='JP_GAAP' if family == 'jppfs' else 'IFRS', adjustment='UNADJUSTED',
                         value=str(value), parser_version='edinet-xbrl-2',
                         source_locator=f'{filename}:{fact.sourceline} {qname.localname}[{context_id}]'))
    counts = Counter(row['metric'] for row in rows)
    return [row for row in rows if counts[row['metric']] == 1]
