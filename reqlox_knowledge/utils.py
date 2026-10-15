"""Reusable utils methods from the development implementation."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime, timezone

def iso_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')

def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()
