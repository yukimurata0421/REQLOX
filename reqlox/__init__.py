"""Inspect finite reliability bindings without importing target code."""
from pathlib import Path
import sys

__version__ = "0.1.0"


def _runtime():
    import reqlox_core
    root = Path(reqlox_core.__file__).resolve().parent
    for source in root.glob('*.py'):
        loaded = sys.modules.get(source.stem)
        origin = getattr(loaded, '__file__', None)
        if loaded is not None and (not origin or Path(origin).resolve() != source):
            raise ImportError('Conflicting runtime module: ' + source.stem)
    directory = str(root)
    if directory not in sys.path:
        sys.path.insert(0, directory)


def inventory(sources):
    """Return accepted and held bindings for a mapping of paths to Python text."""
    _runtime()
    import reliability_reuse
    return reliability_reuse.inventory(sources)


def source_conditions(source_id, text):
    """Extract bounded condition candidates; this does not certify support."""
    _runtime()
    import reliability_source_conditions
    return reliability_source_conditions.project(source_id, text)
