"""Normalize a manually acquired SZSE current A-share listing workbook."""
from __future__ import annotations

import argparse
import csv
from datetime import date, datetime
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlsplit
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

from openpyxl import load_workbook
from openpyxl.utils.exceptions import InvalidFileException

SOURCE = 'https://www.szse.cn/market/product/stock/list/index.html'
HEADERS = ('板块', 'A股代码', 'A股简称', 'A股上市日期')
OUTPUT_FIELDS = ('code', 'company', 'security_type', 'as_of', 'source_url',
                 'board', 'list_status', 'list_date')
BOARDS = {'主板': ('SZSE_MAIN', re.compile(r'(?:000|001|002|003)[0-9]{3}')),
          '创业板': ('SZSE_CHINEXT', re.compile(r'(?:300|301)[0-9]{3}'))}
MAX_ARCHIVE_BYTES = 12_000_000
MAX_EXTRACTED_BYTES = 60_000_000
MAX_LIST_ROWS = 10_000
MAX_HEADER_COLUMNS = 64


def _source_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != 'https' or parsed.netloc not in {'www.szse.cn', 'szse.cn'}
            or parsed.fragment):
        raise ValueError('Expected an official HTTPS SZSE current A-share listing URL')
    if parsed.path == '/market/product/stock/list/index.html' and not parsed.query:
        return url
    params = parse_qsl(parsed.query)
    if (parsed.path == '/api/report/ShowReport' and len(params) == 3
            and dict(params) == {'SHOWTYPE': 'xlsx', 'CATALOGID': '1110', 'TABKEY': 'tab1'}):
        return url
    raise ValueError('Use the official listing page or its A-share workbook URL')


def _board_data(sheet):
    for number, rows in enumerate(sheet.iter_rows(min_row=1, max_row=15, max_col=MAX_HEADER_COLUMNS, values_only=True), 1):
        row = tuple(item.strip() if isinstance(item, str) else item for item in rows)
        if all(column in row for column in HEADERS):
            if any(row.count(column) != 1 for column in HEADERS):
                raise ValueError('SZSE workbook contains duplicate required headings')
            return number, tuple(row.index(column) for column in HEADERS)
    return None


def _listing_date(value: object) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (str, int)):
        text = str(value).strip()
        if re.fullmatch(r'(?:[0-9]{8}|[0-9]{4}[-/][0-9]{2}[-/][0-9]{2})', text):
            return date.fromisoformat(text.replace('/', '-'))
    raise ValueError('missing or invalid A-share listing date')


def normalize_szse_workbook(workbook: Path, as_of: date, expected_main: int, expected_chinext: int,
                            source_url: str = SOURCE, today: date | None = None) -> list[dict[str, str]]:
    """Validate the known listing schema against date- and scope-matched publisher totals."""
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    if not 0 <= (today - as_of).days <= 7:
        raise ValueError('SZSE snapshot date must be current or at most seven days old')
    source_url = _source_url(source_url)
    expected = {'SZSE_MAIN': expected_main, 'SZSE_CHINEXT': expected_chinext}
    if min(expected.values()) < 1 or sum(expected.values()) > MAX_LIST_ROWS:
        raise ValueError('Provide positive dated publisher counts for both SZSE boards')

    if workbook.stat().st_size > MAX_ARCHIVE_BYTES:
        raise ValueError('SZSE workbook exceeds the download limit')
    try:
        with ZipFile(workbook) as archive:
            if sum(member.file_size for member in archive.infolist()) > MAX_EXTRACTED_BYTES:
                raise ValueError('SZSE workbook exceeds the extracted size limit')
        book = load_workbook(workbook, read_only=True, data_only=False)
    except (BadZipFile, InvalidFileException, KeyError) as exc:
        raise ValueError('Expected an authentic XLSX listing workbook') from exc

    try:
        matches = [(sheet, header) for sheet in book.worksheets if (header := _board_data(sheet))]
        if len(matches) != 1:
            raise ValueError('Expected exactly one worksheet with the published SZSE A-share headings')
        sheet, (header_row, indexes) = matches[0]
        if sheet.max_row is not None and sheet.max_row - header_row > MAX_LIST_ROWS:
            raise ValueError('SZSE workbook listing range is too large')
        # Spreadsheet exporters can omit or understate worksheet dimensions.
        sheet.reset_dimensions()
        source_rows = sheet.iter_rows(min_row=header_row + 1, max_col=max(indexes) + 1, values_only=True)
        observed = dict.fromkeys(expected, 0)
        records: dict[str, dict[str, str]] = {}
        for number, row in enumerate(source_rows, header_row + 1):
            if number - header_row > MAX_LIST_ROWS:
                raise ValueError('SZSE workbook listing range is too large')
            if all(item is None or isinstance(item, str) and not item.strip() for item in row):
                continue
            board_name, raw_code, name, raw_date = (row[index] for index in indexes)
            label = BOARDS.get(board_name.strip() if isinstance(board_name, str) else '')
            if label is None:
                raise ValueError(f'SZSE worksheet row {number} has no supported publisher board label')
            board, pattern = label
            code = str(raw_code).strip()
            if not re.fullmatch(r'[0-9]{1,6}', code) or not pattern.fullmatch(code.zfill(6)):
                raise ValueError(f'SZSE worksheet row {number} has a code outside its publisher board')
            code = code.zfill(6)
            if code in records:
                raise ValueError(f'SZSE worksheet row {number} duplicates an A-share code')
            if not isinstance(name, str) or not name.strip() or name.strip().startswith(('=', '+', '-', '@')):
                raise ValueError(f'SZSE worksheet row {number} has no safe publisher security name')
            try:
                listed = _listing_date(raw_date)
            except (TypeError, ValueError) as exc:
                raise ValueError(f'SZSE worksheet row {number} has an invalid listing date') from exc
            if listed > as_of:
                raise ValueError(f'SZSE worksheet row {number} lists after the snapshot date')
            observed[board] += 1
            records[code] = dict(code=code, company=name.strip(), security_type='COMMON_EQUITY',
                                 as_of=as_of.isoformat(), source_url=source_url, board=board,
                                 list_status='ACTIVE', list_date=listed.isoformat())

        if observed != expected:
            raise ValueError(f'SZSE board counts do not reconcile with publisher references '
                             f'(observed {observed}, expected {expected})')
        return list(records.values())
    finally:
        book.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('workbook', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--as-of', required=True, type=date.fromisoformat)
    parser.add_argument('--expected-main', required=True, type=int)
    parser.add_argument('--expected-chinext', required=True, type=int)
    parser.add_argument('--source-url', default=SOURCE)
    args = parser.parse_args()
    try:
        rows = normalize_szse_workbook(args.workbook, args.as_of, args.expected_main,
                                       args.expected_chinext, args.source_url)
        with args.output.open('x', encoding='utf-8', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=OUTPUT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
