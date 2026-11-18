from types import SimpleNamespace

from src.china_connectivity import probe_providers


def test_no_eastmoney_requests_without_explicit_permission():
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, url))
        return Reply(405)

    rows = probe_providers(False, SimpleNamespace(request=request))
    assert calls == [('HEAD', 'https://api.tushare.pro')]
    assert all(row['status'] == 'NOT_RUN_PERMISSION_UNCONFIRMED' for row in rows[1:])


def test_probe_queries_one_row_and_never_emits_listing_content():
    calls = []

    def request(method, url, **kwargs):
        calls.append((method, kwargs))
        return Reply(200)

    rows = probe_providers(True, SimpleNamespace(request=request))
    assert len(calls) == 4
    for method, kwargs in calls[1:]:
        assert method == 'GET' and kwargs['params']['pz'] == 1
        assert kwargs['allow_redirects'] is False
        assert 'headers' not in kwargs
    assert all(row['schema_status'] == 'EXPECTED_FIELDS_PRESENT' for row in rows[1:])
    assert 'Issuer example' not in str(rows) and '920001' not in str(rows)


class Reply:
    def __init__(self, status):
        self.status_code = status
        self.headers = {'Content-Type': 'application/json'}

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def iter_content(self, chunk_size):
        yield b'{"data":{"total":100,"diff":[{"f12":"920001","f13":0,"f14":"Issuer example"}]}}'
