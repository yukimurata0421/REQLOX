"""Package-aware test doubles; no production flat-module aliases."""
import contextlib
import importlib
import sys
from unittest.mock import patch

@contextlib.contextmanager
def patched_runtime_modules(modules, **options):
    with contextlib.ExitStack() as stack:
        for name, module in modules.items():
            parent, separator, child = name.rpartition('.')
            if separator and parent == 'reqlox_core':
                package = importlib.import_module(parent)
                stack.enter_context(patch.object(package, child, module, create=True))
        stack.enter_context(patch.dict(sys.modules, modules, **options))
        yield
