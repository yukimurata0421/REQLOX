"""Bounded private runtime storage, separate from installed and public files."""
import json
import os
from pathlib import Path
import secrets
import tempfile

from .reference import canonical, check_seal, require

MAXIMUM_JSON_BYTES = 32 * 1024 * 1024


def private_directory(path):
    path = Path(path).absolute()
    require(path.resolve() == path and not any(p.is_symlink() for p in (path, *path.parents)),
            'KNOWLEDGE_PATH_LINK_OR_TRAVERSAL')
    package = Path(__file__).resolve().parents[1]
    require(not path.is_relative_to(package), 'KNOWLEDGE_STATE_INSIDE_PACKAGE')
    missing = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True, mode=0o700)
    require(path.stat().st_uid == os.getuid() and path.stat().st_mode & 0o077 == 0,
            'KNOWLEDGE_PRIVATE_STATE_PERMISSIONS')
    return path


def state_directory(state_dir=None):
    if state_dir is None:
        configured = os.environ.get('REQLOX_STATE_DIR')
        if configured:
            state_dir = Path(configured)
        else:
            xdg = os.environ.get('XDG_STATE_HOME')
            base = Path(xdg) if xdg else Path.home() / '.local/state'
            state_dir = base / 'reqlox'
        require(state_dir.is_absolute(), 'KNOWLEDGE_ABSOLUTE_STATE_REQUIRED')
    base = private_directory(state_dir)
    return private_directory(private_directory(base / 'knowledge') / 'local-private-quarantine')


def new_directory(base, prefix):
    require(prefix.replace('-', '').isalnum(), 'KNOWLEDGE_DIRECTORY_PREFIX')
    base = private_directory(base)
    return private_directory(base / (prefix + '-' + secrets.token_hex(16)))


def private_path(base, relative):
    base = Path(base).absolute()
    relative = Path(relative)
    require(not relative.is_absolute() and '..' not in relative.parts, 'KNOWLEDGE_RELATIVE_PATH')
    path = base / relative
    require(path.resolve().is_relative_to(base) and
            not any(p.is_symlink() for p in (path, *path.parents)), 'KNOWLEDGE_PATH_ESCAPE')
    return path


def write_bytes(path, payload, *, replace=False):
    path = Path(path).absolute()
    private_directory(path.parent)
    require(not path.is_symlink() and (replace or not path.exists()), 'KNOWLEDGE_IMMUTABLE_OUTPUT')
    if not replace:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def save(path, value, *, replace=False):
    write_bytes(path, canonical(value) + b'\n', replace=replace)


def read(path, *, maximum_bytes=MAXIMUM_JSON_BYTES):
    path = Path(path).absolute()
    require(not any(p.is_symlink() for p in (path, *path.parents)) and path.is_file() and path.stat().st_size <= maximum_bytes,
            'KNOWLEDGE_INPUT_BOUND')
    with path.open('rb') as stream:
        payload = stream.read(maximum_bytes + 1)
    require(len(payload) <= maximum_bytes, 'KNOWLEDGE_INPUT_BOUND')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'KNOWLEDGE_DUPLICATE_JSON_FIELD')
            result[key] = value
        return result
    return json.loads(payload, object_pairs_hook=unique,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('KNOWLEDGE_NONFINITE_JSON')))


def checked_record(path):
    value = read(path)
    check_seal(value)
    return value
