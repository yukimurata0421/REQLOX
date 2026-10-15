"""Retain private test evidence across return, exception and interruption.

The caller supplies a durable private directory. This module neither authorizes
execution nor releases reservations, retries a campaign, or deletes evidence.
"""
from contextlib import contextmanager
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


def _save(path, value):
    with path.open('x', encoding='utf-8') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, sort_keys=True, allow_nan=False)
        stream.write('\n')
        stream.flush()
        os.fsync(stream.fileno())
    descriptor = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def inventory(root):
    """Hash only regular files within the newly owned workspace, with bounds."""
    files = {}; total = 0; count = 0
    for directory, folders, names in os.walk(root, followlinks=False):
        for name in sorted(folders + names):
            path = Path(directory) / name
            count += 1
            if count > 1024 or path.is_symlink():
                raise ValueError('NATIVE_EVIDENCE_ENTRY_BOUND_OR_LINK')
            if name in folders:
                continue
            metadata = path.stat()
            if not stat.S_ISREG(metadata.st_mode):
                raise ValueError('NATIVE_EVIDENCE_REGULAR_FILE_REQUIRED')
            total += metadata.st_size
            if metadata.st_size > 16777216 or total > 67108864:
                raise ValueError('NATIVE_EVIDENCE_BYTES_BOUND')
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                while chunk := stream.read(65536):
                    digest.update(chunk)
            files[str(path.relative_to(root))] = dict(bytes=metadata.st_size, sha256=digest.hexdigest())
    return files


@contextmanager
def retained_workspace(base, label):
    """Create a unique workspace and always keep it; an OPEN record is durable."""
    base = Path(os.path.abspath(base))
    if (not base.is_dir() or any(p.is_symlink() for p in (base, *base.parents))
            or base.stat().st_uid != os.getuid() or base.stat().st_mode & 0o077):
        raise ValueError('NATIVE_EVIDENCE_PRIVATE_BASE_REQUIRED')
    if type(label) is not str or not re.fullmatch('[a-zA-Z0-9_.-]{1,160}', label):
        raise ValueError('NATIVE_EVIDENCE_LABEL')
    root = Path(tempfile.mkdtemp(prefix=label + '-', dir=base))
    os.chmod(root, 0o700)
    now = lambda: datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9))).isoformat()
    _save(root / 'workspace.json', dict(schema='reqlox.retained-test-workspace.v1',
        status='OPEN', created_at_jst=now(), label=label, automatic_cleanup=False,
        execution_authority=False, automatic_retry=False, reservation_release=False))
    outcome = 'BODY_RETURNED'; failure = None
    try:
        yield root
    except BaseException as exc:
        outcome = 'INTERRUPTED' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'BODY_FAILED'
        failure = type(exc).__name__
        raise
    finally:
        audit_error = None
        try:
            files = inventory(root)
        except (ValueError, OSError) as exc:
            files = None; audit_error = type(exc).__name__
        _save(root / 'retention-terminal.json', dict(schema='reqlox.retained-test-evidence.v1',
            body_outcome=outcome, exception_type=failure, recorded_at_jst=now(), files=files,
            inventory_status='VERIFIED' if files is not None else 'UNCONFIRMED',
            inventory_error_type=audit_error, automatic_cleanup=False, execution_authority=False,
            automatic_retry=False, reservation_release=False, native_result_certified=False,
            trust_boundary='Local file hashes only; no trusted timestamp or execution attestation'))
