"""Finite reliability experiment implementation; use the reqlox public API."""

# Static child entry points inherit the test fence before importing runtime code.
import os as _os
if _os.environ.get("REQLOX_OFFLINE_TESTING") == "1":
    from reqlox.offline_testing import install as _install
    _install()
