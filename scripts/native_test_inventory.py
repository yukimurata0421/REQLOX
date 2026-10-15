"""Inventory test source without importing tests, runtime, or Target modules."""
import argparse
import ast
import hashlib
import json
from pathlib import Path


def inventory(root):
    root = Path(root).resolve()
    rows = []
    for test_root in ('tests', 'get-postmotems'):
        for path in sorted((root / test_root).glob('test_*.py')):
            source = path.read_bytes()
            tree = ast.parse(source, filename=str(path))
            aliases = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = (node.module or '') + '.' + alias.name
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        aliases[alias.asname or alias.name] = alias.name
            def qualified(call):
                text = ast.unparse(call.func)
                first, _, tail = text.partition('.')
                return aliases.get(first, first) + ('.' + tail if tail else '')
            def skipped(node):
                # Only unconditional unittest.skip counts as a retained hold.
                return any(isinstance(d, ast.Call) and ast.unparse(d.func) in ('unittest.skip', 'skip')
                           for d in getattr(node, 'decorator_list', []))
            tests = []
            fixtures = []
            for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
                for fn in (n for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))):
                    calls = [qualified(n) for n in ast.walk(fn) if isinstance(n, ast.Call)]
                    boundary = sorted(set(c for c in calls if (
                        c.startswith(('subprocess.', 'os.system', 'os.fork', 'os.exec'))
                        or c.endswith(('.execute', '.run', '.workspace', '.Popen', '.check_output')))))
                    item = dict(id=path.stem + '.' + cls.name + '.' + fn.name, line=fn.lineno,
                                held=skipped(cls) or skipped(fn), boundary_calls=boundary,
                                bases=[ast.unparse(n) for n in cls.bases])
                    if fn.name.startswith('test_'):
                        item['classification'] = ('HELD_ARCHIVED_CASE' if item['held'] else
                            'BOUNDARY_SOURCE_REVIEW' if boundary else 'NO_DIRECT_BOUNDARY_CALL')
                        tests.append(item)
                    elif boundary:
                        fixtures.append(item)
            guard_index = next((i for i, n in enumerate(tree.body) if isinstance(n, ast.Expr)
                and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == '_install_offline_guard'), None)
            imports_before_guard = [] if guard_index is None else [ast.unparse(n) for n in tree.body[:guard_index]
                if isinstance(n, (ast.Import, ast.ImportFrom)) and not (
                    isinstance(n, ast.ImportFrom) and n.module in ('__future__', 'reqlox.offline_testing'))]
            rows.append(dict(path=str(path.relative_to(root)), sha256=hashlib.sha256(source).hexdigest(),
                guard_before_runtime_imports=guard_index is not None and not imports_before_guard,
                reenabling_native_decorators=[ast.unparse(n) for n in ast.walk(tree)
                    if isinstance(n, ast.Call) and ast.unparse(n.func).endswith(('skipUnless', 'skipIf'))
                    and 'REQLOX_RUN_NATIVE_TESTS' in ast.unparse(n)], tests=tests, fixtures=fixtures))
    tests = [t for row in rows for t in row['tests']]
    return dict(schema='reqlox.static-native-test-inventory.v1', method='AST_ONLY_NO_TEST_IMPORTS',
        test_files=len(rows), defined_test_methods=len(tests), held_methods=sum(t['held'] for t in tests),
        boundary_review_methods=sum(t['classification'] == 'BOUNDARY_SOURCE_REVIEW' for t in tests),
        all_import_guards_present=all(row['guard_before_runtime_imports'] for row in rows),
        no_environment_reenable=not any(row['reenabling_native_decorators'] for row in rows),
        native_execution_verified=False, model_calls=0, native_starts=0,
        limits='Dynamic dispatch and mocked setup require source review; AST counts are not native qualification.',
        files=rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    value = inventory(args.root)
    print(json.dumps(value, indent=2))
    return 0 if value['all_import_guards_present'] and value['no_environment_reenable'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
