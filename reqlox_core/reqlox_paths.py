"""User-owned runtime data lives outside the installed package."""
import os
from pathlib import Path


def state_root():
    configured = os.environ.get("REQLOX_STATE_DIR")
    if configured:
        root = Path(configured)
    else:
        xdg = os.environ.get("XDG_STATE_HOME")
        base = Path(xdg) if xdg else Path.home() / ".local/state"
        root = base / "reqlox"
    if not root.is_absolute() or any(p.is_symlink() for p in (root, *root.parents)):
        raise ValueError("REQLOX_STATE_DIR must be an absolute path without symlinks")
    return root


def ensure_state():
    root = state_root()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if root.stat().st_uid != os.getuid():
        raise ValueError("Runtime directory must be owned by the current user")
    if root.stat().st_mode & 0o077:
        raise ValueError("Runtime directory must have mode 0700")
    return root
