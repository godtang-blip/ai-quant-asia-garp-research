import csv
from datetime import datetime, timedelta
import json
import subprocess
import sys
from zoneinfo import ZoneInfo

import pytest

from src.bse_publisher_export import FIELDNAMES, normalize_bse_pages
from src.regional_listings import BSE_PAGE


AS_OF = datetime.now(ZoneInfo('Asia/Shanghai')).date()


def page(tmp_path, position, rows, pages=2, total=2, callback=False):
    data = {'totalPages': pages, 'number': position, 'numberOfElements': len(rows), 'content': rows}
    if total is not None:
        data['totalElements'] = total
    body = json.dumps([data])
    path = tmp_path / f'page-{position}.json'
    path.write_text(f'callback({body});' if callback else body, encoding='utf-8')
    return path


def issuer(code, company='Listed equity', listed='2021-11-15'):
    return {'xxzqdm': code, 'xxzqjc': company, 'fxssrq': listed}


def test_normalize_pages_preserves_published_920_and_legacy_codes(tmp_path):
    paths = [page(tmp_path, 0, [issuer('920001')], callback=True),
             page(tmp_path, 1, [issuer('430002', 'Legacy code listing')])]
    rows = normalize_bse_pages(paths, AS_OF)
    assert rows == [
        dict(code='430002', company='Legacy code listing', security_type='COMMON_EQUITY',
             as_of=AS_OF.isoformat(), source_url=BSE_PAGE, board='BSE', list_status='ACTIVE',
             list_date='2021-11-15'),
        dict(code='920001', company='Listed equity', security_type='COMMON_EQUITY',
             as_of=AS_OF.isoformat(), source_url=BSE_PAGE, board='BSE', list_status='ACTIVE',
             list_date='2021-11-15'),
    ]


def test_missing_publisher_total_requires_documented_total(tmp_path):
    path = page(tmp_path, 0, [issuer('920001')], pages=1, total=None)
    with pytest.raises(ValueError, match='documented same-scope total'):
        normalize_bse_pages([path], AS_OF)
    assert len(normalize_bse_pages([path], AS_OF, expected_total=1)) == 1
    with pytest.raises(ValueError, match='collected rows do not match'):
        normalize_bse_pages([path], AS_OF, expected_total=2)


@pytest.mark.parametrize(('other', 'reason'), [
    (issuer('920001', 'Duplicate code'), 'duplicate code'),
    (issuer('830001'), 'duplicate code or issuer'),
    (issuer('000001', 'Wrong exchange'), 'unexpected BSE listing code'),
    (issuer('920002', 'Future listing', str(AS_OF + timedelta(days=1))), 'after the snapshot date'),
])
def test_rejects_duplicates_wrong_market_and_future_listing(tmp_path, other, reason):
    paths = [page(tmp_path, 0, [issuer('920001')]), page(tmp_path, 1, [other])]
    with pytest.raises(ValueError, match=reason):
        normalize_bse_pages(paths, AS_OF)


def test_rejects_missing_pages_and_mismatched_totals(tmp_path):
    first = page(tmp_path, 0, [issuer('920001')])
    with pytest.raises(ValueError, match='page count'):
        normalize_bse_pages([first], AS_OF)
    second = page(tmp_path, 1, [issuer('920002', 'More equity')], total=3)
    with pytest.raises(ValueError, match='row totals'):
        normalize_bse_pages([first, second], AS_OF)


def test_cli_requires_confirmation_and_writes_output_exclusively(tmp_path):
    source = page(tmp_path, 0, [issuer('920001')], pages=1, total=1)
    destination = tmp_path / 'BSE.csv'
    args = [sys.executable, '-m', 'src.bse_publisher_export', '--as-of', str(AS_OF),
            '--output', str(destination), str(source)]
    assert subprocess.run(args, capture_output=True).returncode == 2
    assert not destination.exists()
    assert subprocess.run([*args, '--confirm-active-bse-list'], capture_output=True).returncode == 0
    with destination.open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        assert reader.fieldnames == list(FIELDNAMES)
        assert next(reader)['code'] == '920001'
    assert subprocess.run([*args, '--confirm-active-bse-list'], capture_output=True).returncode == 2
