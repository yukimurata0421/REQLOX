"""Load hash-bound method code without changing the global module search path.

Only saved verifier entry points should be called. This loader is not a sandbox
and does not authorize Target execution or recover missing historical evidence.
"""
import ast
from contextlib import contextmanager
import hashlib
import importlib
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_loader
from pathlib import Path
import re
import sys
from types import ModuleType


class _SavedSource(Loader):
    def __init__(self, path, source):
        self.path, self.source = path, source

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        module.__file__ = str(self.path)
        exec(compile(self.source, str(self.path), 'exec'), module.__dict__)


@contextmanager
def archived_method(directory, expected_hashes):
    """Support both historical flat methods and current relative imports.

    Source bytes are verified before any module is loaded. Flat archives require
    a fresh module namespace; neither form borrows a current runtime module.
    """
    directory = Path(directory)
    sources = {}
    for filename, digest in expected_hashes.items():
        if not re.fullmatch(r'[A-Za-z_]\w*\.py', filename):
            raise ValueError('REUSE_AUDIT_METHOD_DRIFT')
        path = directory / filename
        if path.is_symlink():
            raise ValueError('REUSE_AUDIT_METHOD_DRIFT')
        source = path.read_bytes()
        if hashlib.sha256(source).hexdigest() != digest:
            raise ValueError('REUSE_AUDIT_METHOD_DRIFT')
        sources[path.stem] = (path, source)
    relative = any(isinstance(node, ast.ImportFrom) and node.level
                   for _, source in sources.values() for node in ast.walk(ast.parse(source)))
    prefix = '_reqlox_saved_method'
    owned_names = {prefix, *(prefix + '.' + name for name in sources)} if relative else set(sources)
    if owned_names.intersection(sys.modules) or set(sources).intersection(sys.stdlib_module_names):
        raise ValueError('REUSE_AUDIT_FRESH_PROCESS_REQUIRED')

    class Finder(MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            name = fullname.removeprefix(prefix + '.') if relative else fullname
            if relative and not fullname.startswith(prefix + '.'):
                return None
            if name not in sources:
                return None
            saved_path, source = sources[name]
            return spec_from_loader(fullname, _SavedSource(saved_path, source))

    finder = Finder()
    if relative:
        package = ModuleType(prefix)
        package.__path__ = []  # Siblings are resolved exclusively from verified bytes.
        package.__package__ = prefix
        sys.modules[prefix] = package
    sys.meta_path.insert(0, finder)
    try:
        def load(name):
            if name not in sources:
                raise ValueError('REUSE_AUDIT_METHOD_MISSING')
            return importlib.import_module(prefix + '.' + name if relative else name)
        yield load
    finally:
        sys.meta_path.remove(finder)
        for name in owned_names:
            sys.modules.pop(name, None)
