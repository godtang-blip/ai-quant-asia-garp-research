import csv
from datetime import date, datetime

from openpyxl import Workbook
import pytest

from src.szse_publisher_export import HEADERS, OUTPUT_FIELDS, SOURCE, main, normalize_szse_workbook


AS_OF = date(2026, 11, 18)
TODAY = date(2026, 11, 19)


def workbook(path, records, *, columns=HEADERS):
    book = Workbook()
    sheet = book.active
    sheet.append(['深圳证券交易所上市公司名单'])
    sheet.append(['文档来源：深圳证券交易所'])
    sheet.append(columns)
    for record in records:
        sheet.append(record)
    book.save(path)
    return path


def test_normalizes_dated_workbook_with_explicit_publisher_boards(tmp_path):
    path = workbook(tmp_path/'szse.xlsx', [
        ('主板', 1, '平安银行', datetime(1991, 4, 3)),
        ('创业板', '300750', '宁德时代', '2018-06-11'),
    ])
    rows = normalize_szse_workbook(path, AS_OF, 1, 1, today=TODAY)
    assert [row['code'] for row in rows] == ['000001', '300750']
    assert [row['board'] for row in rows] == ['SZSE_MAIN', 'SZSE_CHINEXT']
    assert rows[0]['list_date'] == '1991-04-03'
    assert rows[0]['source_url'] == SOURCE
    assert rows[1]['list_status'] == 'ACTIVE'


@pytest.mark.parametrize(('records', 'match'), [
    ([('主板', '000001', '股票', '19910403')], 'do not reconcile'),
    ([('主板', '000001', '股票', '19910403'), ('主板', '000001', '重复', '19910403')], 'duplicates'),
    ([('主板', '200001', 'B股', '19910403')], 'outside its publisher board'),
    ([('主板', '300750', '股票', '20180611')], 'outside its publisher board'),
    ([('未注明', '000001', '股票', '19910403')], 'board label'),
    ([('主板', '000001', '股票', '20261120')], 'lists after'),
    ([('主板', '000001', '股票', 'invalid')], 'invalid listing date'),
])
def test_rejects_truncated_mixed_or_invalid_inventory(tmp_path, records, match):
    path = workbook(tmp_path/'manual.xlsx', records)
    with pytest.raises(ValueError, match=match):
        normalize_szse_workbook(path, AS_OF, 1, 1, today=TODAY)


def test_rejects_expired_or_unattributed_export(tmp_path):
    path = workbook(tmp_path/'manual.xlsx', [])
    with pytest.raises(ValueError, match='seven days'):
        normalize_szse_workbook(path, date(2026, 11, 1), 1, 1, today=TODAY)
    with pytest.raises(ValueError, match='official HTTPS'):
        normalize_szse_workbook(path, AS_OF, 1, 1, source_url='https://szse.cn.example.net', today=TODAY)


def test_cli_writes_normalized_csv(tmp_path, monkeypatch):
    import sys
    from zoneinfo import ZoneInfo

    path = workbook(tmp_path/'manual.xlsx', [
        ('主板', '000001', '平安银行', '1991-04-03'),
        ('创业板', '300750', '宁德时代', '2018-06-11'),
    ])
    output = tmp_path/'SZSE.csv'
    today = datetime.now(ZoneInfo('Asia/Shanghai')).date()
    monkeypatch.setattr(sys, 'argv', ['normalize-szse', str(path), str(output),
                                    '--as-of', str(today), '--expected-main', '1', '--expected-chinext', '1'])
    main()
    with output.open(encoding='utf-8', newline='') as stream:
        reader = csv.DictReader(stream)
        assert tuple(reader.fieldnames) == OUTPUT_FIELDS
        assert {row['code'] for row in reader} == {'000001', '300750'}
