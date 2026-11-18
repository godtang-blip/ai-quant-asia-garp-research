"""Small, non-acquiring probes for independent China data providers."""
import json
from time import monotonic
from typing import NamedTuple

import requests

EASTMONEY = 'https://push2.eastmoney.com/api/qt/clist/get'
TUSHARE = 'https://api.tushare.pro'
SELECTORS = {'SZSE_MAIN': 'm:0+t:6', 'SZSE_CHINEXT': 'm:0+t:80', 'BSE': 'm:0+t:81+s:2048'}
RESPONSE_LIMIT = 16_384


class Target(NamedTuple):
    provider: str
    scope: str
    url: str
    method: str
    params: dict | None = None


def run_probe(target, session=requests):
    result = dict(provider=target.provider, scope=target.scope, source_url=target.url,
                  http_status='', status='', schema_status='NOT_CHECKED', reported_total='',
                  sample_rows='', json_content_type='')
    try:
        with session.request(target.method, target.url, params=target.params, timeout=(4, 4),
                             allow_redirects=False, stream=True) as response:
            result['http_status'] = response.status_code
            result['json_content_type'] = 'json' in response.headers.get('Content-Type', '').lower()
            if response.status_code != 200 or target.method == 'HEAD':
                result['status'] = {401: 'HTTP_ACCESS_DENIED', 403: 'HTTP_ACCESS_DENIED',
                                    429: 'HTTP_RATE_LIMITED'}.get(response.status_code, 'HTTP_ENDPOINT_REACHED')
                return result
            started = monotonic()
            raw = bytearray()
            for chunk in response.iter_content(chunk_size=4096):
                if monotonic() - started > 6:
                    result['status'] = 'TIMEOUT'
                    return result
                raw.extend(chunk)
                if len(raw) > RESPONSE_LIMIT:
                    result['status'] = 'RESPONSE_LIMIT_EXCEEDED'
                    return result
    except requests.exceptions.ProxyError:
        result['status'] = 'PROXY_CONNECTION_FAILED'
        return result
    except requests.exceptions.Timeout:
        result['status'] = 'TIMEOUT'
        return result
    except requests.exceptions.RequestException:
        result['status'] = 'CONNECTION_FAILED'
        return result
    result['status'] = 'HTTP_ENDPOINT_REACHED'
    try:
        data = json.loads(raw)['data']
        total, sample = data['total'], data['diff']
        if type(total) is not int or total < 0 or not isinstance(sample, list) or len(sample) > 1:
            raise ValueError
        result['reported_total'] = total
        result['sample_rows'] = len(sample)
        result['schema_status'] = ('EXPECTED_FIELDS_PRESENT' if sample and isinstance(sample[0], dict)
                                   and {'f12', 'f13', 'f14'}.issubset(sample[0]) else 'NO_VALID_SAMPLE')
    except (ValueError, TypeError, KeyError):
        result['schema_status'] = 'UNRECOGNIZED_SCHEMA'
    return result


def probe_providers(eastmoney_allowed, session=requests):
    # Status-only, unauthenticated request. A reachable HTTP endpoint does not prove entitlement.
    results = [run_probe(Target('Tushare Pro', 'SZSE/BSE API transport only', TUSHARE, 'HEAD'), session)]
    for board, selector in SELECTORS.items():
        scope = f'{board} reported selector; board membership unverified'
        if not eastmoney_allowed:
            results.append(dict(provider='Eastmoney', scope=scope, source_url=EASTMONEY,
                                status='NOT_RUN_PERMISSION_UNCONFIRMED', schema_status='NOT_CHECKED'))
            continue
        results.append(run_probe(Target('Eastmoney', scope, EASTMONEY, 'GET', {
            'pn': 1, 'pz': 1, 'fs': selector, 'fields': 'f12,f13,f14',
        }), session))
    return results
