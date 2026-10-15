"""Inspect finite reliability bindings without importing Target code."""
from importlib import import_module
from pathlib import Path

__version__ = "0.1.0"


def _runtime():
    """Resolve the named runtime package without changing the import search path."""
    package = import_module('reqlox_core')
    origin = getattr(package, '__file__', None)
    expected = Path(__file__).resolve().parents[1] / 'reqlox_core'
    if not origin or Path(origin).resolve().parent != expected:
        raise ImportError('Conflicting runtime package: ' + 'reqlox_core')
    return package


def inventory(sources):
    """Inspect source syntax; do not import or execute the Target."""
    _runtime()
    from reqlox_core import reliability_reuse
    return reliability_reuse.inventory(sources)


def source_conditions(source_id, text):
    """Project bounded condition candidates without execution authority."""
    _runtime()
    from reqlox_core import reliability_source_conditions
    return reliability_source_conditions.project(source_id, text)
