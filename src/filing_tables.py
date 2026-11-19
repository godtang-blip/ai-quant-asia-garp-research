"""Read bounded HTML financial tables without relying on model accounting guesses."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from heapq import nlargest
import re

MAX_TABLES = 300
MAX_CONTEXTS = 4_000
MAX_GRID_ROWS = 300
MAX_GRID_COLUMNS = 80
MAX_PASSAGES = 48
PASSAGE_CHARS = 2_400
MONEY = re.compile(r'(?:[-+]?|\()(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\)?', re.ASCII)
YEAR = re.compile(r'(?:19|20)\d{2}')
DATE = re.compile(
    r'\b\d{4}-\d{2}-\d{2}\b|'
    r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)'
    r'\s+\d{1,2},?\s+\d{4}\b', re.IGNORECASE)
MONEY_METRIC = re.compile(
    r'\b(?:revenue|income|sales|earnings|profit|loss|assets|liabilities|equity|cash|expenses|debt|'
    r'operating costs?|tax|cost of|dividends?|turnover)\b', re.IGNORECASE)
NON_CURRENCY_METRIC = re.compile(r'per share|per ads|percentage|margin|ratio|number of shares|%', re.I)
STATEMENT = re.compile(r'(?:statements? of|balance sheets?|financial (?:position|results))', re.I)
AS_OF = re.compile(r'\bas (?:of|at)\b', re.I)
ENDED = re.compile(r'\b(?:ended|ending)\b', re.I)
CURRENCIES = {
    'USD': r'USD|US\s*\$|U\.?S\.?\s+dollars?',
    'HKD': r'HKD|HK\s*\$|Hong Kong dollars?',
    'TWD': r'TWD|NT\s*\$|(?:New )?Taiwan dollars?',
    'JPY': r'JPY|Japanese yen|yen',
    'KRW': r'KRW|(?:Korean )?won',
    'CNY': r'CNY|RMB|renminbi',
    'EUR': r'EUR|euros?',
    'SGD': r'SGD|Singapore dollars?',
    'GBP': r'GBP|pounds sterling',
}
CURRENCY = '|'.join(f'(?:{p})' for p in CURRENCIES.values())
SCALE = r'units?|hundreds?|thousands?|millions?|billions?'
CONTEXT = re.compile(
    rf'(?<![\w$])(?P<c1>{CURRENCY})(?![a-z])(?:\s+in)?[\s,:]+(?P<s1>{SCALE})\b'
    rf'|\b(?P<s2>{SCALE})\s+(?:of\s+)?(?P<c2>{CURRENCY})(?![a-z])', re.I)
SCALE_UNITS = {0: 'units', 2: 'hundreds', 3: 'thousands', 6: 'millions', 9: 'billions'}


@dataclass(frozen=True)
class TableCell:
    cell_id: str
    metric_label: str
    value_text: str
    currency: str
    unit: str
    period_start: str
    period_end: str
    period_kind: str
    column_header: str
    unit_text: str
    location: str
    row_text: str
    entity_identifier: str = ''
    entity_identifier_scheme: str = ''
    dimensions: tuple[str, ...] = ()
    context_id: str = ''
    uncertainty: tuple[str, ...] = ()
    xbrl_concept: str = ''
    statement_heading: str = ''


@dataclass(frozen=True)
class TablePassage:
    location: str
    text: str
    cells: tuple[TableCell, ...]


def _text(tag) -> str:
    return ' '.join(tag.get_text(' ', strip=True).split())


def _visible_text(tag) -> str:
    # Footnote markers are kept out of numeric and label cells. The source
    # coordinates still point to the original cell including any footnote.
    return ' '.join(' '.join(str(s) for s in tag.strings if
                            s.find_parent(['sup', 'script', 'style']) is None).split())


def _numeric(value: str) -> bool:
    candidate = value.replace('−', '-')
    return bool(MONEY.fullmatch(candidate)) and candidate.startswith('(') == candidate.endswith(')')


def _date(text: str) -> str:
    for fmt in ('%Y-%m-%d', '%B %d, %Y', '%B %d %Y'):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            continue
    return ''


def _dates(text: str) -> list[str]:
    return list(dict.fromkeys(parsed for match in DATE.findall(text) if (parsed := _date(match))))


def _accounting_period(headers: list[str]) -> tuple[str, str, str]:
    combined = ' | '.join(headers)
    dates = _dates(combined)
    # Comparative dates belong only to their aligned column's header stack.
    if len(dates) == 1 and AS_OF.search(combined):
        return 'POINT_IN_TIME', '', dates[0]
    if len(dates) == 1 and ENDED.search(combined):
        return 'DURATION', '', dates[0]
    if len(dates) == 2 and dates[0] < dates[1] and re.search(r'\bfrom\b.+\bto\b', combined, re.I):
        return 'DURATION', dates[0], dates[1]
    return 'UNRESOLVED', '', ''


def _presentation_unit(lines: list[str]) -> tuple[str, str, str, bool]:
    matches = {}
    for line in lines:
        for match in CONTEXT.finditer(line):
            cur = match['c1'] or match['c2']
            unit = (match['s1'] or match['s2']).lower().rstrip('s') + 's'
            code = next(code for code, pattern in CURRENCIES.items() if re.fullmatch(pattern, cur, re.I))
            matches.setdefault((code, unit), match[0])
    if len(matches) == 1:
        (currency, unit), evidence = next(iter(matches.items()))
        return currency, unit, evidence, False
    # A conflict must not disappear simply because we found the closest phrase.
    return '', '', ' | '.join(matches.values()), len(matches) > 1


def _xbrl_resources(soup) -> tuple[dict, dict]:
    contexts = {}
    for node in soup.find_all(re.compile(r'(?:^|:)context$'), limit=MAX_CONTEXTS):
        context_id = node.get('id')
        if not context_id:
            continue
        period = node.find(re.compile(r'(?:^|:)period$'))
        entity = node.find(re.compile(r'(?:^|:)entity$'))
        if period is None or entity is None or context_id in contexts:
            contexts[context_id] = None
            continue
        identifier = entity.find(re.compile(r'(?:^|:)identifier$'))
        dates = {tag.name.split(':')[-1]: _date(_text(tag)) for tag in period.find_all(recursive=False)}
        start, end, instant = (dates.get(name, '') for name in ('startdate', 'enddate', 'instant'))
        kind = 'UNRESOLVED'
        if instant and not start and not end:
            kind, end = 'POINT_IN_TIME', instant
        elif start and end and start <= end and not instant:
            kind = 'DURATION'
        qualifiers = node.find_all(re.compile(r'(?:^|:)(?:explicitmember|typedmember)$'))
        dimensions = tuple(f"{member.get('dimension', '')}={_text(member)}" for member in qualifiers)
        contexts[context_id] = (kind, start, end, _text(identifier) if identifier else '',
                                identifier.get('scheme', '') if identifier else '', dimensions)
    units = {}
    for node in soup.find_all(re.compile(r'(?:^|:)unit$'), limit=MAX_CONTEXTS):
        unit_id = node.get('id')
        if not unit_id:
            continue
        measures = node.find_all(re.compile(r'(?:^|:)measure$'), recursive=False)
        match = re.fullmatch(r'iso4217:([A-Z]{3})', _text(measures[0])) if len(measures) == 1 else None
        units[unit_id] = match[1] if match and unit_id not in units else ''
    return contexts, units


def _nearby_context(table) -> list[str]:
    # Captions and nearby text in the same container only. Stop at another
    # table instead of borrowing an old table's currency or scale.
    lines = []
    caption = table.find('caption', recursive=False)
    if caption:
        lines.append(_text(caption)[:260])
    for sibling in table.find_previous_siblings(limit=4):
        if sibling.name == 'table' or sibling.find('table'):
            break
        text = _text(sibling)
        if 0 < len(text) <= 260:
            lines.append(text)
    return lines


def _grid(table) -> list[list]:
    grid = []
    active_spans = {}
    for row_index, row in enumerate(table.find_all('tr', limit=MAX_GRID_ROWS), 1):
        if row.find_parent('table') != table:
            continue
        coordinates = {}
        for col, (cell, remaining) in list(active_spans.items()):
            coordinates[col] = cell
            if remaining == 1:
                del active_spans[col]
            else:
                active_spans[col] = cell, remaining - 1
        col = 0
        for source_col, tag in enumerate(row.find_all(['td', 'th'], recursive=False), 1):
            while col in coordinates:
                col += 1
            try:
                width = int(tag.get('colspan', 1))
                depth = int(tag.get('rowspan', 1))
            except ValueError:
                return []
            if not 0 < width <= MAX_GRID_COLUMNS - col or not 0 < depth <= MAX_GRID_ROWS:
                return []
            text = _visible_text(tag)
            cell = (tag, text, row_index, source_col)
            for span_col in range(col, col + width):
                if span_col in coordinates:
                    return []
                coordinates[span_col] = cell
                if depth > 1:
                    active_spans[span_col] = cell, depth - 1
            col += width
        grid.append([coordinates.get(i) for i in range(max(coordinates, default=-1) + 1)])
    return grid


def _financial_cells(table, table_index: int, contexts: dict, units: dict) -> list[TableCell]:
    grid = _grid(table)
    nearby = _nearby_context(table)
    header = []
    results = []
    seen = set()
    for cells in grid:
        # A row whose only numeric cells are years is header material, not a
        # financial observation. Later in-table subheaders don't replace the
        # initial header unless we can tie them to inline XBRL context.
        unique_cells = list({(c[2], c[3]): c for c in cells if c is not None}.values())
        label = next((text for _, text, _, _ in unique_cells if text), '')
        values = [(col, c) for col, c in enumerate(cells) if c is not None and _numeric(c[1])]
        if not values or not label or _numeric(label) or (
                all(YEAR.fullmatch(c[1]) for _, c in values)
                and (ENDED.search(label) or AS_OF.search(label)
                     or all(c[0].name == 'th' for _, c in values)
                     or label.lower() in {'metric', 'item', 'line item', 'year', 'date'})
        ):
            if not results:
                header = [*header[-7:], cells]
            continue
        if NON_CURRENCY_METRIC.search(label):
            continue
        headings = [*nearby, *[candidate[1] for row in header for candidate in row if candidate]]
        statement_heading = next((line for line in headings if STATEMENT.search(line)), '')
        source_values = [c[1] for c in unique_cells]
        for col, cell in values:
            tag, value, row_index, source_col = cell
            key = (row_index, source_col)
            if key in seen:
                continue
            seen.add(key)
            inline = tag.find_all(re.compile(r'(?:^|:)nonfraction$'), limit=2)
            fact = inline[0] if len(inline) == 1 and _visible_text(inline[0]) == value else None
            if not fact and not (statement_heading or MONEY_METRIC.search(label)):
                continue
            heads = list(dict.fromkeys(row[col][1] for row in header
                                       if col < len(row) and row[col] and row[col][1]))
            currency, unit, unit_text, unit_conflict = _presentation_unit([*heads, *nearby])
            period_kind, start, end = _accounting_period(heads)
            header_text = ' | '.join(heads)
            context_id = fact.get('contextref', '') if fact else ''
            entity = scheme = ''
            dimensions = ()
            uncertainty = []
            if unit_conflict:
                uncertainty.append('PRESENTATION_CURRENCY_OR_SCALE_AMBIGUOUS')
            source_index = next(i for i, c in enumerate(unique_cells) if (c[2], c[3]) == key)
            before = [x for x in source_values[:source_index] if x not in {'', '$'}]
            after = [x for x in source_values[source_index + 1:] if x not in {'', '$'}]
            if (before and before[-1] in {'(', '-', '−'}) or (after and after[0] == ')'):
                uncertainty.append('SIGN_SPLIT_ACROSS_SOURCE_CELLS')
            span_headers = {
                tuple(row[span_col][1] for row in header if span_col < len(row) and row[span_col])
                for span_col, candidate in values if (candidate[2], candidate[3]) == key
            }
            if len(span_headers) > 1:
                uncertainty.append('NUMERIC_CELL_SPANS_MULTIPLE_HEADER_COLUMNS')
            if fact:
                fact_currency = units.get(fact.get('unitref', ''), '')
                scale = fact.get('scale', '0')
                fact_unit = SCALE_UNITS.get(int(scale), '') if re.fullmatch(r'-?\d{1,2}', scale) else ''
                if currency and fact_currency and currency != fact_currency:
                    uncertainty.append('PRESENTATION_CURRENCY_CONFLICTS_WITH_INLINE_XBRL')
                if unit and fact_unit and unit != fact_unit:
                    uncertainty.append('PRESENTATION_SCALE_CONFLICTS_WITH_INLINE_XBRL')
                currency, unit = fact_currency, fact_unit
                inline_context = contexts.get(context_id)
                if inline_context:
                    fact_kind, fact_start, fact_end, entity, scheme, dimensions = inline_context
                    reported_years = [year for year in heads if YEAR.fullmatch(year)]
                    if (end and end != fact_end) or (start and start != fact_start) or (
                            period_kind != 'UNRESOLVED' and period_kind != fact_kind
                    ) or (len(reported_years) == 1 and fact_end and reported_years[0] != fact_end[:4]):
                        uncertainty.append('COLUMN_PERIOD_CONFLICTS_WITH_INLINE_XBRL')
                    period_kind, start, end = fact_kind, fact_start, fact_end
                else:
                    uncertainty.append('INLINE_XBRL_CONTEXT_NOT_RESOLVED')
                if fact.get('sign') == '-' and not value.startswith(('-', '−', '(')):
                    uncertainty.append('INLINE_XBRL_SIGN_DIFFERS_FROM_PRINTED_CELL')
                transform = fact.get('format', '').split(':')[-1].lower()
                if transform and transform not in {'num-dot-decimal', 'numdotdecimal'}:
                    uncertainty.append('INLINE_XBRL_NUMBER_TRANSFORM_NOT_SUPPORTED')
            if not currency or not unit:
                uncertainty.append('CURRENCY_OR_DISPLAY_SCALE_UNRESOLVED')
            if period_kind == 'UNRESOLVED' or not end or (period_kind == 'DURATION' and not start):
                uncertainty.append('REPORTING_PERIOD_UNRESOLVED')
            if dimensions:
                uncertainty.append('INLINE_XBRL_FACT_HAS_DIMENSIONS')
            row_text = ' | '.join(c[1] for c in unique_cells)
            if len(row_text) > 350 or len(header_text) > 300:
                continue  # Preserve full quote and header, never match truncated material.
            cell_id = f'T{table_index}R{row_index}C{source_col}'
            results.append(TableCell(
                cell_id, label, value, currency, unit, start, end, period_kind, header_text,
                unit_text, f'HTML table {table_index}, row {row_index}, cell {source_col}',
                row_text, entity, scheme, dimensions, context_id, tuple(uncertainty),
                fact.get('name', '') if fact else '', statement_heading,
            ))
    return results


def _render(cell: TableCell) -> str:
    return (f'{cell.cell_id} {cell.metric_label} = {cell.value_text}\n'
            f'Quote: {cell.row_text}\n'
            f'Column: {cell.column_header}\n'
            f'Context: {cell.currency} {cell.unit} | {cell.period_kind} '
            f'{cell.period_start} {cell.period_end}')


def _passages(soup):
    contexts, units = _xbrl_resources(soup)
    for table_index, table in enumerate(soup.find_all('table', limit=MAX_TABLES), 1):
        if table.find('table'):
            continue  # Index numbering still includes layout and nested tables.
        location = f'HTML table {table_index}'
        lines = []
        records = []
        length = 0
        for cell in _financial_cells(table, table_index, contexts, units):
            rendered = _render(cell)
            if records and length + len(rendered) + 2 > PASSAGE_CHARS:
                yield TablePassage(location, '\n\n'.join(lines), tuple(records))
                lines, records, length = [], [], 0
            lines.append(rendered)
            records.append(cell)
            length += len(rendered) + 2
        if records:
            yield TablePassage(location, '\n\n'.join(lines), tuple(records))


def extract_html_tables(soup) -> list[TablePassage]:
    # Inspect the bounded table set before choosing passages so early index /
    # highlight tables cannot crowd a later detailed statement out of the budget.
    def priority(passage):
        return (any(cell.statement_heading for cell in passage.cells),
                sum(not cell.uncertainty for cell in passage.cells),
                sum(bool(cell.context_id) for cell in passage.cells))

    return nlargest(MAX_PASSAGES, _passages(soup), key=priority)


def check_table_observation(proposal: dict, passage) -> dict | None:
    """Verify a model-proposed cell against original table coordinates and context."""
    fields = ('cell_id', 'metric_label', 'value_text', 'currency', 'unit', 'period_start', 'period_end', 'quote')
    if not isinstance(proposal, dict) or any(not isinstance(proposal.get(key), str) for key in fields):
        return None
    cell = next((cell for cell in passage.cells if cell.cell_id == proposal['cell_id']), None)
    if cell is None or (
            proposal['metric_label'].strip().casefold() != cell.metric_label.casefold()
            or proposal['value_text'].strip() != cell.value_text
            or proposal['quote'].strip() != cell.row_text):
        return None
    uncertainty = list(cell.uncertainty)
    for field in ('currency', 'unit', 'period_start', 'period_end'):
        value = proposal[field].strip()
        if value and value.casefold() != getattr(cell, field).casefold():
            uncertainty.append(f'MODEL_{field.upper()}_DOES_NOT_MATCH_SOURCE')
    decimal_value = None
    uncertain_sign_or_format = {'SIGN_SPLIT_ACROSS_SOURCE_CELLS',
                                'INLINE_XBRL_SIGN_DIFFERS_FROM_PRINTED_CELL',
                                'INLINE_XBRL_NUMBER_TRANSFORM_NOT_SUPPORTED'}
    if not uncertain_sign_or_format.intersection(uncertainty):
        raw = cell.value_text.replace('−', '-')
        decimal = '-' + raw[1:-1] if raw.startswith('(') else raw
        decimal_value = format(Decimal(decimal.replace(',', '')), 'f')
    return {
        'metric_label': cell.metric_label, 'value_text': cell.value_text,
        'decimal_value_as_reported': decimal_value,
        'currency': cell.currency, 'unit': cell.unit, 'period_start': cell.period_start,
        'period_end': cell.period_end, 'period_kind': cell.period_kind,
        'supporting_text': cell.row_text, 'source_location': cell.location,
        'source_cell_id': cell.cell_id, 'source_column_header': cell.column_header,
        'source_unit_text': cell.unit_text, 'source_context_id': cell.context_id,
        'source_entity_identifier': cell.entity_identifier,
        'source_entity_identifier_scheme': cell.entity_identifier_scheme,
        'source_dimensions': cell.dimensions, 'source_xbrl_concept': cell.xbrl_concept,
        'source_statement_heading': cell.statement_heading,
        'uncertainty_reasons': uncertainty,
        'verification_status': 'PROVISIONAL_CONTEXT_UNRESOLVED' if uncertainty else 'SOURCE_TEXT_MATCH',
        'filing_verified': False,
    }
