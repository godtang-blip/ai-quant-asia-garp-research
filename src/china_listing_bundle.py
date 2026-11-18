"""Validate a pinned China listing bundle before materializing workflow inputs."""
import argparse
import csv
from datetime import date, datetime
from hashlib import sha256
from io import StringIO
import json
import os
from pathlib import Path
import re
from tempfile import TemporaryDirectory
from urllib.parse import parse_qsl, urlsplit
from zoneinfo import ZoneInfo

from .china_coverage_report import BOARDS
from .china_vendor_exports import load_tushare_export
from .listing_exports import FIELDS, VENUES, load_listing_export
from .venue_sources import ListingError

BOARD_SCOPE = {'SZSE': {'SZSE_MAIN', 'SZSE_CHINEXT'}, 'BSE': {'BSE'}}
FILES = {f'{kind}/{venue}.csv': (kind, venue)
         for kind in ('publisher', 'tushare') for venue in BOARD_SCOPE}
MAX_FILE = 8_000_000


def read_bounded(root, name, limit):
    path = root / name
    if path.is_symlink() or path.resolve() != path or not path.is_file():
        raise ListingError('MISSING_OR_UNSAFE_FILE', 'Expected a regular file within the bundle')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ListingError('FILE_LIMIT_EXCEEDED', 'Bundle file exceeds byte limit')
    return raw


def check_url(url, host):
    if not isinstance(url, str) or any(character.isspace() for character in url):
        return False
    try:
        parts = urlsplit(url)
        hostname = parts.hostname or ''
        return (parts.scheme == 'https' and parts.netloc == hostname and not parts.fragment
                and (hostname == host or hostname.endswith('.' + host))
                and not any(re.search(r'token|secret|pass|key|auth|signature', key, re.I)
                            for key, _ in parse_qsl(parts.query)))
    except (TypeError, ValueError):
        return False


def decode_manifest(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or type(data.get('schema_version')) is not int or data['schema_version'] != 1:
        raise ValueError('Unsupported listing bundle manifest')
    entries = data.get('files')
    if not isinstance(entries, list) or not entries or len(entries) > len(FILES):
        raise ValueError('Manifest must declare one to four supported listing files')
    used = set()
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get('path'), str):
            raise ValueError('Manifest entry has no listing file path')
        name = entry['path']
        if name not in FILES or name in used:
            raise ValueError('Manifest has an unsupported or duplicate file path')
        used.add(name)
    return entries


def normalize_publisher(raw, venue, as_of):
    reader = csv.DictReader(StringIO(raw.decode('utf-8-sig')), strict=True)
    required = FIELDS | {'board', 'list_status', 'list_date'}
    if set(reader.fieldnames or ()) != required or len(reader.fieldnames) != len(required):
        raise ListingError('SCHEMA_DRIFT', 'Publisher bundle needs explicit board, status and listing date')
    output = StringIO()
    writer = csv.DictWriter(output, sorted(FIELDS), lineterminator='\n')
    writer.writeheader()
    counts = dict.fromkeys(BOARD_SCOPE[venue], 0)
    _, publisher, _, suffix = VENUES[venue]
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ListingError('SCHEMA_DRIFT', 'Malformed publisher bundle CSV')
        row = {field: value.strip() for field, value in row.items()}
        if not check_url(row['source_url'], publisher):
            raise ListingError('SOURCE_CONFLICT', 'Publisher listing URL must match the exchange')
        if row['board'] not in counts or not re.fullmatch(BOARDS[row['board']][0], row['code'] + suffix):
            raise ListingError('SOURCE_CONFLICT', 'Publisher board, code and exchange do not agree')
        if (row['list_status'] != 'ACTIVE' or row['security_type'] != 'COMMON_EQUITY'
                or row['as_of'] != str(as_of) or date.fromisoformat(row['list_date']) > as_of
                or not row['company']):
            raise ListingError('SOURCE_CONFLICT', 'Publisher row lacks active ordinary-equity or date evidence')
        counts[row['board']] += 1
        writer.writerow({field: row[field] for field in FIELDS})
    return output.getvalue().encode(), counts


def materialize_file(entry, root, staging, today):
    name = entry['path']
    kind, venue = FILES[name]
    raw = read_bounded(root, name, MAX_FILE)
    digest = sha256(raw).hexdigest()
    if entry.get('sha256') != digest:
        raise ListingError('SOURCE_HASH_MISMATCH', 'Data file digest does not match manifest')
    as_of = date.fromisoformat(entry['as_of'])
    if entry['as_of'] != str(as_of) or not 0 <= (today - as_of).days <= 7:
        raise ListingError('INCOMPLETE_OR_STALE_SOURCE', 'Bundle date must be within seven days')
    host = VENUES[venue][1] if kind == 'publisher' else 'tushare.pro'
    if entry.get('scope_as_of') != str(as_of) or not check_url(entry.get('scope_url', ''), host):
        raise ListingError('SCOPE_REFERENCE_INVALID', 'Require a same-date source reference of the correct provider')
    expected = entry.get('board_counts')
    if (not isinstance(expected, dict) or set(expected) != BOARD_SCOPE[venue] or
            any(type(value) is not int or value <= 0 for value in expected.values())):
        raise ListingError('SCOPE_REFERENCE_INVALID', 'Require a positive expected count for each board')
    if kind == 'publisher':
        ready, observed = normalize_publisher(raw, venue, as_of)
    else:
        ready, observed = raw, None

    path = staging / name
    path.parent.mkdir(exist_ok=True)
    path.write_bytes(ready)
    try:
        if kind == 'publisher':
            listings, details = load_listing_export(path, venue, today)
            if sum(observed.values()) != len(listings):
                raise ListingError('SOURCE_CONFLICT', 'Publisher normalization and accepted count disagree')
        else:
            listings, details = load_tushare_export(path, venue, today)
            observed = json.loads(details['scope_counts'])
        if details['source_asof'] != str(as_of) or expected != observed:
            raise ListingError('SCOPE_COUNT_MISMATCH', 'Accepted counts or date differ from the manifest scope')
    except Exception:
        path.unlink()
        raise
    return dict(
        path=name, status='VALIDATED_IMPORT_READY', as_of=str(as_of),
        source_url=details['source_url'], scope_reference_url=entry['scope_url'],
        expected_board_counts=expected, accepted_board_counts=observed,
        received=details['received'], accepted=len(listings),
        excluded=details['received'] - len(listings),
        input_sha256=digest, staged_sha256=details['source_sha256'],
        evidence='PUBLISHER_SNAPSHOT' if kind == 'publisher' else 'THIRD_PARTY_SNAPSHOT',
        scope_check='OPERATOR_DECLARED_SCOPE_COUNTS_RECONCILED',
    )


def validate_bundle(root, output, today=None):
    root = root.resolve(strict=True)
    output = output.absolute()
    if output.exists() or not output.parent.is_dir():
        raise ValueError('Output must be a new directory inside an existing directory')
    if '\n' in str(output) or '\r' in str(output):
        raise ValueError('Output path cannot contain a newline')
    today = today or datetime.now(ZoneInfo('Asia/Shanghai')).date()
    raw_manifest = read_bounded(root, 'manifest.json', 32_768)
    entries = decode_manifest(raw_manifest)
    report = {'manifest_sha256': sha256(raw_manifest).hexdigest(),
              'files': [], 'unresolved_venues': []}
    with TemporaryDirectory(prefix='china-bundle-', dir=output.parent) as tmp:
        staging = Path(tmp) / 'validated'
        staging.mkdir()
        for entry in entries:
            try:
                result = materialize_file(entry, root, staging, today)
            except ListingError as exc:
                result = dict(path=entry['path'], status='REJECTED', failure_code=exc.code, reason=str(exc))
            except (ValueError, KeyError, TypeError, UnicodeError, csv.Error):
                result = dict(path=entry['path'], status='REJECTED', failure_code='SCHEMA_DRIFT',
                              reason='Invalid date, fields, listing schema or duplicate security')
            report['files'].append(result)
        approved = [row['path'] for row in report['files'] if row['status'] == 'VALIDATED_IMPORT_READY']
        ready_venues = {FILES[name][1] for name in approved}
        report['unresolved_venues'] = sorted(set(BOARD_SCOPE) - ready_venues)
        (staging/'bundle_validation.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        staging.rename(output)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = validate_bundle(args.input, args.output)
    except (OSError, ValueError):
        parser.exit(1, 'Listing bundle could not be opened or its manifest is invalid.\n')
    approved = {row['path'].split('/')[0] for row in report['files'] if row['status'] == 'VALIDATED_IMPORT_READY'}
    if os.environ.get('GITHUB_OUTPUT'):
        with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as stream:
            for kind, key in [('publisher', 'publisher_dir'), ('tushare', 'vendor_dir')]:
                if kind in approved:
                    stream.write(f'{key}={args.output.absolute() / kind}\n')
    print(f"Validated listing files: {sum(row['status'] == 'VALIDATED_IMPORT_READY' for row in report['files'])}; "
          f"unresolved venues: {', '.join(report['unresolved_venues']) or 'none for staged imports'}")


if __name__ == '__main__':
    main()
