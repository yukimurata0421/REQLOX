"""Export a standalone, read-only publication from curated archived summaries.

This module never opens a Workspace, experiment engine, credential or history.
The exported directory needs only a static HTTP server.
"""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent
STATIC_FILES = ('public-demo.html', 'public-demo.js', 'public-demo.css')
FILES = (*STATIC_FILES, 'public-demo.json')
ROUTES = {'/demo/': 'public-demo.html', '/demo/public-demo.html': 'public-demo.html',
          '/demo/public-demo.js': 'public-demo.js', '/demo/public-demo.css': 'public-demo.css',
          '/demo/public-demo.json': 'public-demo.json'}
KINDS = {'.html': 'text/html; charset=utf-8', '.js': 'text/javascript; charset=utf-8',
         '.css': 'text/css; charset=utf-8', '.json': 'application/json; charset=utf-8'}
RECORD_IDS = ('integration-caller-v01', 'api-copy-v01', 'worker-copy-v01',
              'temppath-readme-v01', 'earlier-lock-cleanup',
              'earlier-elapsed-time-ttl', 'earlier-temporary-file-cleanup')
STAGES = ('input', 'detection', 'repair', 'reinjection', 'decision')
MAXIMUM_BYTES = 1024 * 1024


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(',', ':'), allow_nan=False).encode()


def read(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAXIMUM_BYTES:
        raise ValueError('PUBLIC_DEMO_INPUT_BOUNDARY')
    return json.loads(path.read_bytes())


def text(value, maximum=2400):
    if type(value) is not str or not 1 <= len(value) <= maximum:
        raise ValueError('PUBLIC_DEMO_TEXT_BOUNDARY')
    # Summaries, not locations, raw responses, links or credential references.
    if re.search(r'(?:https?://|file://|/home/|/mnt/|/etc/|/var/|[A-Za-z]:\\|'
                 r'-----BEGIN|Bearer\s|Basic\s|[\w.+-]+@[\w.-]+\.[A-Za-z]{2,})', value):
        raise ValueError('PUBLIC_DEMO_PRIVATE_TEXT')
    return value


def flag(value):
    if type(value) is not bool:
        raise ValueError('PUBLIC_DEMO_BOOLEAN')
    return value


def payload(data=None):
    """Project explicit fields only; private additions cannot become public keys."""
    data = Path(data) if data is not None else ROOT / 'data'
    archive = read(data / 'archived-records.json')
    if archive.get('schema') != 'reqlox.archived-ui-records.v1':
        raise ValueError('PUBLIC_DEMO_ARCHIVE_SCHEMA')
    records = []
    for identity in RECORD_IDS:
        matches = [r for r in archive['records'] if r.get('id') == identity]
        if len(matches) != 1:
            raise ValueError('PUBLIC_DEMO_RECORD_IDENTITY')
        row = matches[0]
        digest = hashlib.sha256(encode({k: v for k, v in row.items() if k != 'record_sha256'})).hexdigest()
        if row['record_sha256'] != digest:
            raise ValueError('PUBLIC_DEMO_RECORD_HASH')
        source = row['source']
        if hashlib.sha256(source['text'].encode()).hexdigest() != source['text_sha256']:
            raise ValueError('PUBLIC_DEMO_SOURCE_HASH')
        if [s['stage'] for s in row['steps']] != list(STAGES):
            raise ValueError('PUBLIC_DEMO_STAGES')
        held = row['held_atomic_bindings']
        if type(held) is not int or not 0 <= held <= 4:
            raise ValueError('PUBLIC_DEMO_HELD')
        repaired = row['temppath_repair_performed']
        if repaired is not None:
            flag(repaired)
        evidence = []
        for ref in row.get('evidence_refs', []):
            if (not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,100}', ref['id']) or
                    not re.fullmatch(r'[a-f0-9]{64}', ref['sha256'])):
                raise ValueError('PUBLIC_DEMO_EVIDENCE_REFERENCE')
            evidence.append(dict(id=ref['id'], sha256=ref['sha256']))
        records.append(dict(id=identity, title=text(row['title'], 160),
            observed_at_jst=text(row['observed_at_jst'], 40),
            source=dict(title=text(source['title'], 160), text=text(source['text']),
                        text_sha256=source['text_sha256'], binding=text(source['binding'], 100)),
            steps=[dict(stage=s['stage'], status=text(s['status'], 100),
                        description=text(s['description'])) for s in row['steps']],
            decision=text(row['decision'], 100), held_atomic_bindings=held,
            temppath_repair_performed=repaired, originals_preserved=flag(row['originals_preserved']),
            historical_raw_evidence_gap=flag(row['historical_raw_evidence_gap']),
            limits=text(row['limits']), archive_record_sha256=digest, evidence_refs=evidence))
    saved = read(data / 'copied-module-integration-summary.json')['summary']
    expected = dict(cumulative_campaigns=15, maximum_campaigns=15,
                    cumulative_charged_seconds=62, maximum_seconds=120,
                    held_atomic_bindings=4, temppath_repair_performed=False,
                    additional_execution_enabled=False)
    if any(type(saved.get(k)) is not type(v) or saved[k] != v for k, v in expected.items()):
        raise ValueError('PUBLIC_DEMO_LEDGER_DRIFT')
    result = dict(schema='reqlox.public-readonly-demo.v1', mode='ARCHIVED_READ_ONLY',
        ledger=dict(scope='COPIED_TARGET_LOCAL_20261012', campaigns=15, campaign_limit=15,
                    charged_seconds=62, seconds_limit=120, remaining_campaigns=0, state='CLOSED'),
        new_native_campaigns=0, new_model_calls=0, records=records,
        claims=dict(independent_generalization=False, source_added_value=False,
                    probability_calibration=False, human_effort_reduction=False))
    result['publication_sha256'] = hashlib.sha256(encode(result)).hexdigest()
    return result


def export(destination, *, source=None, data=None):
    """Create only the fixed files in an empty, non-symlink destination."""
    source = Path(source) if source is not None else ROOT / 'static'
    destination = Path(destination)
    if destination.is_symlink() or (destination.exists() and any(destination.iterdir())):
        raise ValueError('PUBLIC_DEMO_OUTPUT_NOT_EMPTY')
    content = {}
    for name in STATIC_FILES:
        p = source / name
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAXIMUM_BYTES:
            raise ValueError('PUBLIC_DEMO_ASSET_BOUNDARY')
        content[name] = p.read_bytes()
    content['public-demo.json'] = encode(payload(data)) + b'\n'
    destination.mkdir(mode=0o700, parents=True, exist_ok=True)
    rows = []
    for name, raw in content.items():
        with (destination / name).open('xb') as out:
            out.write(raw)
        rows.append(dict(name=name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest()))
    return dict(schema='reqlox.public-demo-export.v1', files=rows,
                workspace_exported=False, private_history_exported=False,
                new_native_campaigns=0, new_model_calls=0)


def asset(path):
    name = ROUTES.get(path)
    if name is None:
        return None
    raw = encode(payload()) if name.endswith('.json') else (ROOT / 'static' / name).read_bytes()
    return raw, KINDS[Path(name).suffix]


class PreviewHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def request(self):
        self.connection.settimeout(5)
        if self.headers.get('Host') not in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}'):
            status, raw, kind = 403, b'{}', KINDS['.json']
        else:
            if self.path == '/demo' and self.command in ('GET', 'HEAD'):
                self.send_response(308)
                self.send_header('Location', '/demo/')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            value = asset(urlsplit(self.path).path)
            status = 405 if self.command not in ('GET', 'HEAD') else 200 if value else 404
            raw, kind = value if status == 200 else (b'{}', KINDS['.json'])
        self.send_response(status)
        for k, v in [('Content-Type', kind), ('Content-Length', str(len(raw))),
                     ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                     ('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'")]:
            self.send_header(k, v)
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(raw)

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--output-dir', type=Path)
    group.add_argument('--serve', type=int, metavar='LOOPBACK_PORT')
    args = parser.parse_args()
    if args.output_dir is not None:
        print(json.dumps(export(args.output_dir)))
    else:
        server = ThreadingHTTPServer(('127.0.0.1', args.serve), PreviewHandler)
        server.daemon_threads = True
        print(f'http://127.0.0.1:{server.server_port}/demo/', flush=True)
        try:
            server.serve_forever()
        finally:
            server.server_close()


if __name__ == '__main__':
    main()
