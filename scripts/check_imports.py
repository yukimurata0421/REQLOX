"""Check canonical runtime imports without loading runtime or Target code."""
import ast
import json
from pathlib import Path


def inspect(root):
    root = Path(root)
    names = {p.stem for p in (root / 'reqlox_core').glob('*.py')}
    files = [p for name in ('reqlox', 'reqlox_core', 'reqlox_demo', 'reqlox_knowledge', 'reqlox_system')
             for p in (root / name).rglob('*.py')]
    violations = []
    for path in sorted(files):
        tree = ast.parse(path.read_bytes(), filename=str(path))
        for node in ast.walk(tree):
            bad = isinstance(node, ast.Import) and any(a.name.split('.')[0] in names for a in node.names)
            bad |= (isinstance(node, ast.ImportFrom) and not node.level
                    and (node.module or '').split('.')[0] in names)
            if bad:
                violations.append(dict(path=str(path.relative_to(root)), line=node.lineno,
                                       reason='FLAT_RUNTIME_IMPORT', source=ast.unparse(node)))
    return dict(schema='reqlox.runtime-import-check.v1', inspected_files=len(files),
                passed=not violations, violations=violations, runtime_modules_imported=False,
                limits='Checks static import syntax; Target and archived-code imports have separate bindings.')


if __name__ == '__main__':
    value = inspect(Path(__file__).resolve().parents[1])
    print(json.dumps(value, indent=2))
    raise SystemExit(0 if value['passed'] else 1)
