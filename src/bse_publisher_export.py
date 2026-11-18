"""Normalize archived responses from the BSE currently-listed company page."""
import argparse
import csv
from datetime import date, datetime
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from .regional_listings import BSE_PAGE, json_document


FIELDNAMES = ('code', 'company', 'security_type', 'as_of', 'source_url',
              'board', 'list_status', 'list_date')
MAX_PAGE_BYTES = 12_000_000
BSE_CODE = re.compile(r'(?:[48][0-9]{5}|920[0-9]{3})')


def page_integer(value):
    if type(value) is int and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r'[0-9]{1,8}', value):
        return int(value)
    raise ValueError('expected a nonnegative publisher pagination integer')


def read_page(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_PAGE_BYTES + 1)
    if len(raw) > MAX_PAGE_BYTES:
        raise ValueError('publisher response exceeds the per-page byte limit')
    document = json_document(raw)
    if not (isinstance(document, list) and len(document) == 1 and isinstance(document[0], dict)):
        raise ValueError('unexpected BSE listing response envelope')
    return document[0]


def normalize_bse_pages(paths, as_of, expected_total=None):
    """Preserve observed codes from the active BSE scope and reject partial archives."""
    if not 1 <= len(paths) <= 100:
        raise ValueError('provide 1 to 100 BSE response pages in zero-based order')
    if not 0 <= (datetime.now(ZoneInfo('Asia/Shanghai')).date() - as_of).days <= 7:
        raise ValueError('BSE snapshot date must be current or at most seven days old')
    if expected_total is not None and expected_total < 1:
        raise ValueError('expected total must be a positive count from the same dated BSE scope')
    reported_totals = set()
    names = set()
    codes = set()
    rows = []
    for position, path in enumerate(paths):
        try:
            page = read_page(path)
            if page_integer(page['totalPages']) != len(paths):
                raise ValueError('publisher page count does not match the supplied archive')
            if 'number' in page and page_integer(page['number']) != position:
                raise ValueError('publisher page number does not match the supplied order')
            reported_totals.add(page_integer(page['totalElements']) if 'totalElements' in page else None)
            content = page['content']
            if not isinstance(content, list) or not content:
                raise ValueError('publisher page is empty or has an invalid content array')
            if 'numberOfElements' in page and page_integer(page['numberOfElements']) != len(content):
                raise ValueError('publisher page row count does not match its content')
            for item in content:
                if not isinstance(item, dict):
                    raise ValueError('publisher row is not an object')
                code, company, listing = (item[key] for key in ('xxzqdm', 'xxzqjc', 'fxssrq'))
                if not isinstance(code, str) or not BSE_CODE.fullmatch(code.strip()):
                    raise ValueError('unexpected BSE listing code')
                if not isinstance(company, str) or not company.strip():
                    raise ValueError('publisher listing lacks a company name')
                if not isinstance(listing, str):
                    raise ValueError('publisher listing lacks a text listing date')
                code, company = code.strip(), ' '.join(company.split())
                try:
                    parsed_date = date.fromisoformat(listing.strip().replace('/', '-'))
                except ValueError:
                    raise ValueError('publisher listing date is invalid') from None
                if parsed_date > as_of:
                    raise ValueError('security listing date is after the snapshot date')
                if code in codes or company.casefold() in names:
                    raise ValueError('duplicate code or issuer name; review pages and any legacy/current alias')
                codes.add(code)
                names.add(company.casefold())
                rows.append(dict(code=code, company=company, security_type='COMMON_EQUITY',
                                 as_of=as_of.isoformat(), source_url=BSE_PAGE,
                                 board='BSE', list_status='ACTIVE', list_date=parsed_date.isoformat()))
        except (KeyError, TypeError, UnicodeError, ValueError) as exc:
            raise ValueError(f'BSE archived page {position}: {exc}') from None
    if len(reported_totals) != 1:
        raise ValueError('publisher row totals or their availability changed between pages')
    reported = reported_totals.pop()
    if reported is None and expected_total is None:
        raise ValueError('missing publisher row total; supply an independently documented same-scope total')
    if ((reported is not None and len(rows) != reported) or
            (expected_total is not None and len(rows) != expected_total)):
        raise ValueError('collected rows do not match the publisher or independently documented total')
    return sorted(rows, key=lambda row: row['code'])


def main():
    parser = argparse.ArgumentParser(
        description='Normalize JSON/JSONP pages saved during authorized use of the official public BSE '
                    'currently-listed company page. No network automation, browser impersonation, or '
                    'automatic 920-code remapping is performed.')
    parser.add_argument('--as-of', type=date.fromisoformat, required=True, help='Publisher snapshot date in ISO format')
    parser.add_argument('--expected-total', type=int,
                        help='Independently documented BSE listed-equity count for the same scope and date')
    parser.add_argument('--confirm-active-bse-list', action='store_true', required=True,
                        help='Confirm these pages are the dated currently-listed BSE list, excluding NEEQ')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('pages', type=Path, nargs='+', help='Saved response pages in zero-based order')
    args = parser.parse_args()
    try:
        rows = normalize_bse_pages(args.pages, args.as_of, args.expected_total)
        with args.output.open('x', newline='', encoding='utf-8') as stream:
            writer = csv.DictWriter(stream, FIELDNAMES)
            writer.writeheader()
            writer.writerows(rows)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(f'Normalized {len(rows)} BSE publisher records')


if __name__ == '__main__':
    main()
