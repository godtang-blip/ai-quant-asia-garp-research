import csv
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from hashlib import sha256
import json

import pandas as pd
import pytest

from src.china_listing_bundle import validate_bundle
from src import discovery_v031 as discovery

TODAY = datetime.now(ZoneInfo('Asia/Shanghai')).date()
AS_OF = str(TODAY)
HEADER = 'code,company,security_type,as_of,source_url,board,list_status,list_date\n'
SZSE = ('https://www.szse.cn/market/product/stock/list/index.html', {'SZSE_MAIN': 1, 'SZSE_CHINEXT': 1})
BSE = ('https://www.bse.cn/nq/listedcompany.html', {'BSE': 1})


def publisher_row(code, name, source, board, status='ACTIVE'):
    return f'{code},{name},COMMON_EQUITY,{AS_OF},{source},{board},{status},2024-01-01\n'


def add(root, path, body, url, counts, **overrides):
    file = root/path
    file.parent.mkdir(exist_ok=True)
    file.write_text(body, encoding='utf-8')
    return dict(path=path, sha256=sha256(file.read_bytes()).hexdigest(),
                as_of=AS_OF, scope_as_of=AS_OF, scope_url=url, board_counts=counts, **overrides)


def manifest(root, entries):
    (root/'manifest.json').write_text(json.dumps(dict(schema_version=1, files=entries)))


def test_independent_validated_imports_feed_existing_discovery(tmp_path, monkeypatch):
    root = tmp_path/'source'
    root.mkdir()
    szse = add(root, 'publisher/SZSE.csv', HEADER +
               publisher_row('000001', 'SZ Main', SZSE[0], 'SZSE_MAIN') +
               publisher_row('300001', 'SZ ChiNext', SZSE[0], 'SZSE_CHINEXT'), *SZSE)
    bse = add(root, 'publisher/BSE.csv', HEADER + publisher_row('920001','BJ company',BSE[0],'BSE'), *BSE)
    manifest(root, [szse, bse])
    ready = tmp_path/'ready'
    result = validate_bundle(root, ready, TODAY)
    assert all(file['status'] == 'VALIDATED_IMPORT_READY' for file in result['files'])
    assert result['unresolved_venues'] == []
    with (ready/'publisher'/'SZSE.csv').open() as stream:
        assert 'board' not in csv.DictReader(stream).fieldnames

    def blocked(*_):
        raise ConnectionError('fixture exchange unavailable')

    for name in ('fetch_listing', 'source_jpx_list', 'source_twse_list', 'source_nikkei225'):
        monkeypatch.setattr(discovery, name, blocked)
    for key in ('PUBLIC_DATA_API_KEY','DART_API_KEY','TUSHARE_TOKEN','GARP_TUSHARE_EXPORT_DIR','GARP_ENABLE_BAOSTOCK'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('GARP_VALIDATED_CHINA_PUBLISHER_DIR', str(ready/'publisher'))
    curated = pd.DataFrame([dict(ticker='600000.SS', market='China')])
    universe, logs = discovery.discover_five_markets(curated, 'all5_official', 0, china_only=True)
    symbols = universe.set_index('ticker')
    assert symbols.loc['000001.SZ', 'listing_source_ids'] == '["export_SZSE"]'
    assert symbols.loc['920001.BJ', 'listing_source_ids'] == '["export_BSE"]'
    assert symbols.loc['920001.BJ', 'security_type_status'] == 'OFFICIAL_ISSUER_LIST_TYPE_CHECK_VENDOR'
    audits = logs.set_index('source')
    assert audits.loc['export_SZSE', 'source_asof'] == AS_OF
    assert audits.loc['export_BSE', 'source_url'] == BSE[0]


@pytest.mark.parametrize('problem', ['stale', 'count', 'inactive', 'board', 'hash', 'symlink'])
def test_bad_bse_never_blocks_valid_shenzhen(tmp_path, problem):
    root = tmp_path/'source'
    root.mkdir()
    szse = add(root, 'tushare/SZSE.csv',
               'as_of,ts_code,symbol,name,exchange,market,list_status,list_date,delist_date\n'
               f'{AS_OF},000001.SZ,000001,Main,SZSE,主板,L,19910403,\n'
               f'{AS_OF},300001.SZ,300001,ChiNext,SZSE,创业板,L,20091030,\n',
               'https://tushare.pro/document/2?doc_id=25', SZSE[1])
    body = HEADER + publisher_row('920001', 'BJ company', BSE[0],
                                  'NEEQ' if problem == 'board' else 'BSE',
                                  'DELISTED' if problem == 'inactive' else 'ACTIVE')
    bse = add(root, 'publisher/BSE.csv', body, BSE[0], {'BSE': 2 if problem == 'count' else 1})
    if problem == 'stale':
        stale = str(TODAY - timedelta(days=8))
        bse.update(as_of=stale, scope_as_of=stale)
    if problem == 'hash':
        bse['sha256'] = '0' * 64
    if problem == 'symlink':
        (tmp_path/'external.csv').write_text(body)
        (root/'publisher/BSE.csv').unlink()
        (root/'publisher/BSE.csv').symlink_to(tmp_path/'external.csv')
    manifest(root, [szse, bse])
    ready = tmp_path/'ready'
    summary = validate_bundle(root, ready, TODAY)
    assert [entry['status'] for entry in summary['files']] == ['VALIDATED_IMPORT_READY', 'REJECTED']
    assert summary['unresolved_venues'] == ['BSE']
    assert (ready/'tushare/SZSE.csv').is_file()
    assert not (ready/'publisher/BSE.csv').exists()


def test_manifest_cannot_reference_other_files(tmp_path):
    manifest(tmp_path, [{'path':'../unexpected.csv'}])
    with pytest.raises(ValueError, match='unsupported'):
        validate_bundle(tmp_path, tmp_path/'out', TODAY)
    assert not (tmp_path/'out').exists()


def test_validated_file_preserves_other_configured_exchange_fallbacks(tmp_path):
    staged = tmp_path/'staged'
    staged.mkdir()
    legacy = tmp_path/'legacy'
    legacy.mkdir()
    (staged/'SZSE.csv').touch()
    (staged/'TWSE.csv').touch()
    assert discovery._configured_export_path('SZSE', str(legacy), str(staged)) == staged/'SZSE.csv'
    assert discovery._configured_export_path('BSE', str(legacy), str(staged)) == legacy/'BSE.csv'
    assert discovery._configured_export_path('TWSE', str(legacy), str(staged)) == legacy/'TWSE.csv'
