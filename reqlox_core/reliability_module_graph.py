"""Finite frozen module graphs and public function reexports."""
import ast
from contextlib import contextmanager
from copy import deepcopy
import importlib
import importlib.abc
import importlib.util
import hashlib
from pathlib import PurePosixPath
import sys
import incident_reference as c
import reliability_serialized_flow as serialized
MAXIMUM_MODULES = 4
MAXIMUM_REEXPORT_EDGES = 2
MAXIMUM_PUBLIC_EXPORTS = 4

def relative_names(tree):
    return {a.asname or a.name for n in tree.body if isinstance(n, ast.ImportFrom) and n.level for a in n.names}

def package_exports(tree):
    """Current finite reliability method; public state remains outside the package."""
    imported = {}
    declared = None
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and (type(node.value.value) is str):
            continue
        if isinstance(node, ast.ImportFrom) and node.level and node.module:
            for alias in node.names:
                name = alias.asname or alias.name
                c.require(alias.name != '*' and name not in imported, 'MODULE_GRAPH_EXPORT_IMPORT_REBOUND')
                imported[name] = node.lineno
        elif isinstance(node, ast.Assign):
            c.require(declared is None and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name) and (node.targets[0].id == '__all__'), 'MODULE_GRAPH_EXPORT_DECLARATION')
            try:
                declared = ast.literal_eval(node.value)
            except (ValueError, TypeError):
                raise ValueError('MODULE_GRAPH_EXPORT_DECLARATION')
            c.require(type(declared) in (list, tuple) and all((type(name) is str and name.isidentifier() and (not name.startswith('_')) for name in declared)) and (len(declared) == len(set(declared))), 'MODULE_GRAPH_EXPORT_DECLARATION')
        else:
            raise ValueError('MODULE_GRAPH_PACKAGE_INITIALIZER')
    names = [name for name in imported if not name.startswith('_')] if declared is None else declared
    c.require(set(names) <= set(imported) and len(names) <= MAXIMUM_PUBLIC_EXPORTS, 'MODULE_GRAPH_PUBLIC_EXPORT_BOUND_OR_MISSING')
    return {name: imported[name] for name in names}

def build(member, sources, imports):
    trees = {}
    aliases = {}
    links = {}
    raw_links = {}
    origins = {}
    active = set()

    def parent_initializers(location):
        parent = PurePosixPath(location).parent
        rows = []
        while str(parent) != '.' and str(parent / '__init__.py') in sources:
            rows.append(str(parent / '__init__.py'))
            parent = parent.parent
        return rows

    def visit(location):
        c.require(location not in active, 'MODULE_GRAPH_IMPORT_CYCLE')
        if location in trees:
            return
        c.require(location in sources and len(trees) < MAXIMUM_MODULES, 'MODULE_GRAPH_CAPACITY_OR_MISSING')
        active.add(location)
        tree = ast.parse(sources[location])
        trees[location] = tree
        aliases[location] = imports(tree)
        raw_links[location] = {}
        if location.endswith('/__init__.py'):
            package_exports(tree)
        imports_seen = []
        for n in tree.body:
            if isinstance(n, ast.Import):
                imports_seen.extend((a.asname or a.name.split('.')[0] for a in n.names))
            elif isinstance(n, ast.ImportFrom):
                imports_seen.extend((a.asname or a.name for a in n.names))
                if not n.level:
                    continue
                c.require(n.module and all((a.name != '*' for a in n.names)), 'MODULE_GRAPH_EXPLICIT_FUNCTION_IMPORT')
                base = PurePosixPath(location).parent
                for _ in range(n.level - 1):
                    c.require(str(base) != '.' and str(base / '__init__.py') in sources, 'MODULE_GRAPH_PACKAGE_ESCAPE')
                    base = base.parent
                c.require(str(base) != '.' and str(base / '__init__.py') in sources, 'MODULE_GRAPH_PACKAGE_REQUIRED')
                parts = n.module.split('.')
                c.require(all((p.isidentifier() for p in parts)), 'MODULE_GRAPH_IMPORT_PATH')
                target = base.joinpath(*parts)
                choices = [str(target) + '.py', str(target / '__init__.py')]
                matches = [v for v in choices if v in sources]
                c.require(len(matches) == 1, 'MODULE_GRAPH_AMBIGUOUS_OR_MISSING_IMPORT')
                destination = matches[0]
                visit(destination)
                for a in n.names:
                    raw_links[location][a.asname or a.name] = (destination, a.name)
        c.require(len(imports_seen) == len(set(imports_seen)), 'MODULE_GRAPH_IMPORT_REBOUND')
        filtered = deepcopy(tree)
        filtered.body = [n for n in filtered.body if not isinstance(n, ast.ImportFrom) or not n.level]
        serialized.module_guard(filtered, {**aliases[location], **{k: 'FROZEN_FUNCTION' for k in raw_links[location]}})
        for fn in (n for n in tree.body if isinstance(n, ast.FunctionDef)):
            origins[id(fn)] = location
        active.remove(location)
    visit(member)
    pending = list(trees)
    while pending:
        location = pending.pop()
        for init in parent_initializers(location):
            if init not in trees:
                before = set(trees)
                visit(init)
                pending.extend(set(trees) - before)
    declarations = {location: {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)} for location, tree in trees.items()}
    c.require(all((len(declarations[location]) == sum((isinstance(n, ast.FunctionDef) for n in tree.body)) for location, tree in trees.items())), 'MODULE_GRAPH_FUNCTION_REBOUND')
    resolutions = {}

    def resolve(location, symbol, seen=()):
        key = (location, symbol)
        c.require(key not in seen, 'MODULE_GRAPH_REEXPORT_CYCLE')
        if symbol in declarations[location]:
            return (location, declarations[location][symbol], [])
        c.require(symbol in raw_links[location] and len(seen) < MAXIMUM_REEXPORT_EDGES, 'MODULE_GRAPH_FUNCTION_OR_REEXPORT_REQUIRED')
        destination, imported = raw_links[location][symbol]
        target, node, path = resolve(destination, imported, (*seen, key))
        return (target, node, [dict(member=location, symbol=symbol, imported_member=destination, imported_symbol=imported), *path])
    for location, rows in raw_links.items():
        links[location] = {}
        for symbol in rows:
            target, node, path = resolve(location, symbol)
            links[location][symbol] = (target, node)
            resolutions[location, symbol] = path
    modules = {}
    for location in trees:
        path = PurePosixPath(location)
        parents = parent_initializers(location)
        c.require(parents, 'MODULE_GRAPH_PACKAGE_REQUIRED')
        root = PurePosixPath(parents[-1]).parent.parent
        relative = path.relative_to(root)
        parts = list(relative.parts)
        parts[-1] = parts[-1][:-3]
        if parts[-1] == '__init__':
            parts.pop()
        c.require(parts and all((p.isidentifier() for p in parts)), 'MODULE_GRAPH_MODULE_NAME')
        name = '.'.join(parts)
        c.require(name not in modules.values() and parts[0] not in sys.stdlib_module_names, 'MODULE_GRAPH_MODULE_COLLISION')
        modules[location] = name
    return dict(trees=trees, aliases=aliases, links=links, origins=origins, modules=modules, resolutions=resolutions)

def bind(member, original, sources, canonical, imports):
    graph = build(member, sources, imports)
    symbol = original if type(original) is str else original.name
    definitions = [n for n in graph['trees'][member].body if isinstance(n, ast.FunctionDef) and n.name == symbol]
    c.require(len(definitions) == 1 or (not definitions and symbol in graph['links'][member]), 'MODULE_GRAPH_PUBLIC_FUNCTION_REQUIRED')
    entry = definitions[0] if definitions else graph['links'][member][symbol][1]

    def canonical_node(node):
        return canonical(node, graph['aliases'][graph['origins'][id(node)]], {})

    def module_for(node):
        location = graph['origins'][id(node)]
        functions = {n.name: n for n in graph['trees'][location].body if isinstance(n, ast.FunctionDef)}
        functions.update({name: value[1] for name, value in graph['links'][location].items()})
        return (functions, canonical_node)
    entry_member = graph['origins'][id(entry)]
    helper, fn, bound = serialized.bind(entry, graph['trees'][entry_member], canonical_node, module_for=module_for)
    bound['entry_symbol'] = symbol
    repair_member = graph['origins'][id(helper)]
    if 'temporary_creator' in bound:
        functions, _ = module_for(helper)
        creator = functions[bound['temporary_creator']['symbol']]
        bound['temporary_creator']['member'] = graph['origins'][id(creator)]
    bound['module_graph'] = dict(kind='CLOSED_RELATIVE_FUNCTION_GRAPH_V1', entry_member=member, repair_member=repair_member, modules=graph['modules'], source_sha256={n: hashlib.sha256(sources[n].encode()).hexdigest() for n in graph['trees']}, maximum_modules=MAXIMUM_MODULES, dynamic_imports_qualified=False, import_side_effects_qualified=False, execution_authority=False)
    if not definitions:
        bound['module_graph']['public_entry_resolution'] = dict(kind='DECLARED_PACKAGE_FUNCTION_REEXPORT_V1', public_member=member, public_symbol=symbol, function_member=entry_member, function_symbol=entry.name, reexport_path=graph['resolutions'][member, symbol], maximum_reexport_edges=MAXIMUM_REEXPORT_EDGES)
    return (helper, fn, bound, repair_member, graph['aliases'][repair_member])

@contextmanager
def loaded(sources, binding):
    """Current finite reliability method; public state remains outside the package."""
    graph = binding['module_graph']
    names = graph['modules']
    c.require(set(sources) == set(names), 'MODULE_GRAPH_EXECUTION_SOURCE_SET')
    reverse = {name: member for member, name in names.items()}
    roots = {name.split('.')[0] for name in reverse}
    c.require(not any((name.split('.')[0] in roots for name in sys.modules)), 'MODULE_GRAPH_RUNTIME_COLLISION')

    class FrozenLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):

        def find_spec(self, fullname, path=None, target=None):
            if fullname in reverse:
                return importlib.util.spec_from_loader(fullname, self, is_package=reverse[fullname].endswith('/__init__.py'))
            if fullname.split('.')[0] in roots:
                raise ModuleNotFoundError('UNFROZEN_MODULE_IMPORT')
            return None

        def create_module(self, spec):
            return None

        def exec_module(self, module):
            member = reverse[module.__name__]
            module.__file__ = '/tmp/frozen/' + member
            exec(compile(sources[member], module.__file__, 'exec'), module.__dict__)
    loader = FrozenLoader()
    sys.meta_path.insert(0, loader)
    try:
        entry = importlib.import_module(names[graph['entry_member']])
        namespaces = [sys.modules[n].__dict__ for n in reverse if n in sys.modules]
        yield (entry.__dict__, namespaces)
    finally:
        sys.meta_path.remove(loader)
        for name in list(sys.modules):
            if name.split('.')[0] in roots:
                del sys.modules[name]
