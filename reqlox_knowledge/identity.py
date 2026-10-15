"""Reusable identity methods from the development implementation."""
from __future__ import annotations
from .utils import sha256_bytes

def stable_id(prefix: str, *parts: str) -> str:
    payload = '\n'.join(parts).encode('utf-8')
    return prefix + sha256_bytes(payload)[:20]
