"""Finite reliability controls and verification."""
import ast
from collections import Counter
from copy import deepcopy
import hashlib
import io
import json
from pathlib import PurePosixPath
import tokenize
import incident_reference as c
import repository_atomic_write as atomic
import reliability_context as contexts
import reliability_instance as instances
import reliability_conditions as conditions
import reliability_delegated_context as delegated
import reliability_serialized_flow as serialized
import reliability_module_graph as module_graph
FAMILIES = ('atomic_file', 'async_resource', 'elapsed_ttl', 'atomic_context')
CONTRACTS = {'atomic_file': 'owned.atomic-bytes.v1', 'atomic_context': 'owned.atomic-context.v1', 'async_resource': 'owned.async-release.v1', 'elapsed_ttl': 'owned.elapsed-ttl.v1'}
LIMITS = dict(files=1024, file_bytes=262144, total_bytes=16777216, sites=12, helper_depth=2, steps=12, probes=8, cpu_seconds=2, wall_seconds=5, memory_bytes=134217728, output_bytes=131072)
OPERATIONS = {'atomic_file': ('WRITE', 'FSYNC', 'REPLACE'), 'atomic_context': ('WRITE', 'FSYNC', 'REPLACE'), 'async_resource': ('EXCEPTION', 'TASK_CANCEL', 'ACQUIRE_CANCEL'), 'elapsed_ttl': ('BACKWARD', 'FORWARD', 'STATIONARY')}
PRIMITIVE_CAPABILITIES = {'file_write_error': ('atomic_file', 'WRITE'), 'fsync_error': ('atomic_file', 'FSYNC'), 'rename_error': ('atomic_file', 'REPLACE'), 'exception_after_acquire': ('async_resource', 'EXCEPTION'), 'task_cancellation': ('async_resource', 'TASK_CANCEL'), 'task_cancellation_while_acquiring': ('async_resource', 'ACQUIRE_CANCEL'), 'clock_backward': ('elapsed_ttl', 'BACKWARD'), 'clock_forward': ('elapsed_ttl', 'FORWARD'), 'clock_stalled': ('elapsed_ttl', 'STATIONARY')}

def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()

def validate_sources(sources):
    c.require(type(sources) is dict and 0 < len(sources) <= LIMITS['files'], 'REUSE_FILES')
    total = 0
    for member, text in sources.items():
        atomic.checked_path(member)
        c.require(member.endswith('.py') and type(text) is str and (len(text.encode()) <= LIMITS['file_bytes']), 'REUSE_FILE_BYTES')
        total += len(text.encode())
    c.require(total <= LIMITS['total_bytes'], 'REUSE_TOTAL_BYTES')

def imports(tree):
    result = {}
    for n in tree.body:
        if isinstance(n, ast.Import):
            for a in n.names:
                result[a.asname or a.name.split('.')[0]] = a.name
        elif isinstance(n, ast.ImportFrom) and n.level == 0:
            for a in n.names:
                if a.name != '*':
                    result[a.asname or a.name] = n.module + '.' + a.name
    return result

def dotted(name):
    pieces = name.split('.')
    node = ast.Name(id=pieces[0], ctx=ast.Load())
    for piece in pieces[1:]:
        node = ast.Attribute(value=node, attr=piece, ctx=ast.Load())
    return node

class AliasNormalizer(ast.NodeTransformer):

    def __init__(self, aliases):
        self.aliases = aliases

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id in self.aliases:
            name = self.aliases[node.id]
            return ast.copy_location(dotted('Path' if name == 'pathlib.Path' else name), node)
        return node

def local_names(fn):
    return {n.id for n in ast.walk(fn) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store)} | {n.arg for n in ast.walk(fn.args) if isinstance(n, ast.arg)}

def module_bindings(tree):
    """Module bindings."""
    names = set()
    mutated = set()

    def visit(node):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
            return
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            root = node.value
            while isinstance(root, ast.Attribute):
                root = root.value
            if isinstance(root, ast.Name):
                mutated.add(root.id)
        for child in ast.iter_child_nodes(node):
            visit(child)
    for row in tree.body:
        visit(row)
    return (names, mutated)

def canonical_function(fn, aliases, helpers, depth=0, seen=()):
    """Canonical function."""
    fn = deepcopy(fn)
    fn.decorator_list = []
    fn.returns = None
    if fn.body and isinstance(fn.body[0], ast.Expr) and isinstance(fn.body[0].value, ast.Constant) and isinstance(fn.body[0].value.value, str):
        fn.body = fn.body[1:]
    for a in fn.args.args:
        a.annotation = None
    for a in fn.args.kwonlyargs:
        a.annotation = None
    shadow = local_names(fn) & set(aliases)
    c.require(not shadow, 'REUSE_SHADOWED_IMPORT')
    c.require(not local_names(fn) & set(helpers), 'REUSE_SHADOWED_HELPER')
    fn = AliasNormalizer(aliases).visit(fn)

    class InlineHelpers(ast.NodeTransformer):

        def visit_Expr(self, row):
            if not (isinstance(row.value, ast.Call) and isinstance(row.value.func, ast.Name) and (row.value.func.id in helpers)):
                return self.generic_visit(row)
            call = row.value
            helper = helpers[call.func.id]
            c.require(depth < LIMITS['helper_depth'] and helper.name not in seen, 'REUSE_HELPER_DEPTH')
            args = helper.args
            helper_rows = helper.body[1:] if helper.body and isinstance(helper.body[0], ast.Expr) and isinstance(helper.body[0].value, ast.Constant) and isinstance(helper.body[0].value.value, str) else helper.body
            c.require(not isinstance(helper, ast.AsyncFunctionDef) and (not helper.decorator_list) and (not args.posonlyargs) and (not args.kwonlyargs) and (not args.defaults) and (args.vararg is None) and (args.kwarg is None) and (not call.keywords) and (len(call.args) == len(args.args)) and (1 <= len(helper_rows) <= 3) and all((isinstance(n, ast.Expr) and isinstance(n.value, ast.Call) for n in helper_rows)) and all((isinstance(x, ast.Name) for x in call.args)), 'REUSE_HELPER_SHAPE')
            expanded = canonical_function(helper, aliases, helpers, depth + 1, (*seen, helper.name))
            mapping = {a.arg: deepcopy(v) for a, v in zip(args.args, call.args)}

            class Substitute(ast.NodeTransformer):

                def visit_Name(self, n):
                    return deepcopy(mapping.get(n.id, n))
            return [Substitute().visit(n) for n in expanded.body]
    fn = InlineHelpers().visit(fn)
    ast.fix_missing_locations(fn)
    return fn

def signature(fn, count):
    a = fn.args
    c.require(not a.posonlyargs and len(a.args) == count and (not a.kwonlyargs) and (not a.defaults) and (a.vararg is None) and (a.kwarg is None), 'REUSE_SIGNATURE')

def async_binding(fn):
    signature(fn, 2)
    resource, work = [a.arg for a in fn.args.args]
    c.require(not local_names(fn) & {'Exception', 'BaseException'}, 'REUSE_SHADOWED_BUILTIN')
    assignments = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)]
    variable = None
    if assignments:
        c.require(len(assignments) == 1 and len(assignments[0].targets) == 1 and isinstance(assignments[0].targets[0], ast.Name), 'REUSE_ASYNC_RESULT_BINDING')
        variable = assignments[0].targets[0].id
        c.require(variable not in (resource, work), 'REUSE_ASYNC_RESULT_SHADOW')

    def shape(x):
        return ast.dump(ast.Module(body=x.body, type_ignores=[]))
    value = shape(fn)
    prefix = f'async def f({resource}, {work}):\n    await {resource}.acquire()\n'
    for returns in (False, True):
        if returns and variable is None:
            continue
        operation = f'{variable} = await {work}()' if returns else f'await {work}()'
        tail = f'    return {variable}\n' if returns else ''
        templates = {'BARE': f'    {operation}\n    {resource}.release()\n' + tail, 'FINALLY': f'    try:\n        {operation}\n    finally:\n        {resource}.release()\n' + tail, 'EXCEPT_EXCEPTION': f'    try:\n        {operation}\n    except Exception:\n        {resource}.release()\n        raise\n    {resource}.release()\n' + tail, 'EXCEPT_BASE_EXCEPTION': f'    try:\n        {operation}\n    except BaseException:\n        {resource}.release()\n        raise\n    {resource}.release()\n' + tail}
        for style, body in templates.items():
            if value == shape(ast.parse(prefix + body).body[0]):
                return dict(resource_parameter=resource, work_parameter=work, style=style, protected=style in ('FINALLY', 'EXCEPT_BASE_EXCEPTION'), returns_result=returns, result_variable=variable)
    direct = prefix + f'    try:\n        return await {work}()\n    finally:\n        {resource}.release()\n'
    c.require(value == shape(ast.parse(direct).body[0]), 'REUSE_ASYNC_SHAPE')
    return dict(resource_parameter=resource, work_parameter=work, style='FINALLY_DIRECT_RETURN', protected=True, returns_result=True, result_variable=None)

def clock_binding(fn):
    signature(fn, 2)
    c.require(len(fn.body) == 1 and isinstance(fn.body[0], ast.Return) and isinstance(fn.body[0].value, ast.Call), 'REUSE_CLOCK_FACTORY')
    call = fn.body[0].value
    c.require(ast.unparse(call.func) == 'cachetools.TTLCache' and (not call.args) and (len(call.keywords) == 3) and ({k.arg for k in call.keywords} == {'maxsize', 'ttl', 'timer'}), 'REUSE_CLOCK_API')
    values = {k.arg: k.value for k in call.keywords}
    c.require(isinstance(values['maxsize'], ast.Constant) and type(values['maxsize'].value) is int and (1 <= values['maxsize'].value <= 32) and isinstance(values['ttl'], ast.Constant) and (type(values['ttl'].value) in (int, float)) and (0 < values['ttl'].value <= 32) and isinstance(values['timer'], ast.Name) and (values['timer'].id in [a.arg for a in fn.args.args]), 'REUSE_CLOCK_VALUES')
    return dict(ttl=values['ttl'].value, timer_parameter=values['timer'].id, positional_clock_roles=['civil', 'elapsed'])

def context_binding(fn, tree):
    """Context binding."""
    c.require(isinstance(fn, ast.FunctionDef) and len(fn.args.args) >= 1, 'REUSE_CONTEXT_SIGNATURE')
    body = [n for n in fn.body if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str))]
    c.require(len(body) == 1 and isinstance(body[0], ast.Return), 'REUSE_CONTEXT_FACTORY')
    outer = body[0].value
    c.require(isinstance(outer, ast.Call) and isinstance(outer.func, ast.Attribute) and (outer.func.attr == 'open') and (not outer.args) and (not outer.keywords) and isinstance(outer.func.value, ast.Call), 'REUSE_CONTEXT_OPEN')
    call = outer.func.value
    c.require(isinstance(call.func, ast.Name) and call.args and isinstance(call.args[0], ast.Name) and (call.args[0].id == fn.args.args[0].arg), 'REUSE_CONTEXT_PATH')
    factory_name = call.func.id
    defaults = dict(zip([a.arg for a in fn.args.args][-len(fn.args.defaults):], fn.args.defaults)) if fn.args.defaults else {}
    if factory_name in defaults:
        c.require(isinstance(defaults[factory_name], ast.Name), 'REUSE_CONTEXT_DEFAULT_CLASS')
        factory_name = defaults[factory_name].id
    cls = next((x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == factory_name), None)
    c.require(cls is not None and all((any((isinstance(n, ast.FunctionDef) and n.name == method for n in cls.body)) for method in ('open', 'commit', 'rollback'))), 'REUSE_CONTEXT_PROTOCOL')
    c.require(any((k.arg == 'overwrite' or (k.arg is None and isinstance(k.value, ast.Name) and (fn.args.kwarg is not None) and (k.value.id == fn.args.kwarg.arg)) for k in call.keywords)), 'REUSE_CONTEXT_OVERWRITE')
    return dict(factory_class=cls.name, path_parameter=fn.args.args[0].arg)

def inventory(sources):
    validate_sources(sources)
    accepted, held, index = ([], [], [])
    for member, text in sorted(sources.items()):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            held.append(dict(member=member, reason='UNSUPPORTED_SYNTAX'))
            continue
        aliases = imports(tree)
        relative_helpers = module_graph.relative_names(tree)
        bound_globals, mutated_globals = module_bindings(tree)
        reassigned = bound_globals & set(aliases)
        helpers = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}
        package_entries = {}
        if member.endswith('/__init__.py') and relative_helpers:
            try:
                package_entries = module_graph.package_exports(tree)
            except ValueError as exc:
                held.append(dict(member=member, reason=str(exc)))
        sites = [(None, n, None) for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        for cls in (n for n in tree.body if isinstance(n, ast.ClassDef)):
            sites.extend(((cls.name, n, None) for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))))
        sites.extend(((None, None, name) for name in package_entries))
        symbol_counts = Counter((exported or (owner + '.' if owner else '') + original.name for owner, original, exported in sites))
        for owner, original, exported in sites:
            symbol = exported or (owner + '.' if owner else '') + original.name
            calls = [] if exported else sorted({ast.unparse(n.func) for n in ast.walk(original) if isinstance(n, ast.Call)})
            index.append(dict(member=member, symbol=symbol, line=package_entries[exported] if exported else original.lineno, calls=calls, imports=aliases))
            if exported:
                index[-1]['kind'] = 'PACKAGE_FUNCTION_REEXPORT'
            if symbol_counts[symbol] > 1:
                held.append(dict(member=member, symbol=symbol, line=index[-1]['line'], reason='REUSE_MULTIPLE_DECLARATIONS_HELD'))
                continue
            if any((s['member'] == member and s['symbol'] == symbol for s in accepted)):
                continue
            instance_operation = owner is not None and (not original.decorator_list) and (original.name != '__init__') and bool(calls)
            generator = not exported and owner is None and (len(original.decorator_list) == 1) and (ast.unparse(AliasNormalizer(aliases).visit(deepcopy(original.decorator_list[0]))) == 'contextlib.contextmanager')
            serialized_operation = bool(exported) or (owner is None and (not generator) and (serialized.looking(original, tree) or any((isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and (n.func.id in relative_helpers) for n in ast.walk(original)))))
            if serialized_operation and symbol.startswith('_'):
                continue
            if not instance_operation and (not generator) and (not serialized_operation) and (not any((x.endswith(('.replace', '.acquire', '.release', '.TTLCache', '.open')) or (x in aliases and aliases[x].endswith('TTLCache')) for x in calls))):
                continue
            try:
                c.require(not reassigned, 'REUSE_REASSIGNED_MODULE_IMPORT')
                c.require(not mutated_globals & set(aliases), 'REUSE_MUTATED_IMPORTED_API')
                fn = None if instance_operation or serialized_operation else canonical_function(original, aliases, helpers)
                if owner and (not instance_operation):
                    c.require(len(original.decorator_list) == 1 and isinstance(original.decorator_list[0], ast.Name) and (original.decorator_list[0].id == 'staticmethod'), 'REUSE_INSTANCE_METHOD_HELD')
                elif owner is None and (not exported):
                    c.require(not original.decorator_list or generator, 'REUSE_DECORATOR_HELD')
                family, bound = (None, None)
                repair_member = member
                repair_aliases = aliases
                if serialized_operation:
                    if relative_helpers:
                        helper, fn, bound, repair_member, repair_aliases = module_graph.bind(member, exported or original, sources, canonical_function, imports)
                    else:
                        serialized.module_guard(tree, aliases)
                        helper, fn, bound = serialized.bind(original, tree, lambda node: canonical_function(node, aliases, {}))
                    c.require('os' in repair_aliases.values(), 'REUSE_CONTEXT_CLEANUP_API_REQUIRED')
                    family = 'atomic_context'
                    original = helper
                elif instance_operation:
                    c.require(owner not in mutated_globals, 'INSTANCE_CLASS_MUTATED')
                    definitions = [n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == owner]
                    c.require(len(definitions) == 1, 'INSTANCE_CLASS_REDEFINED')
                    c.require(not any((isinstance(n, ast.Assign) and any((isinstance(t, ast.Name) and t.id == owner for t in n.targets)) for n in ast.walk(ast.Module(body=[n for n in tree.body if not isinstance(n, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))], type_ignores=[])))), 'INSTANCE_CLASS_REASSIGNED')
                    cls = definitions[0]

                    def canonical_instance(node, location, module):
                        mapped = {k: v for k, v in imports(module).items() if v in ('os', 'tempfile', 'pathlib.Path')}
                        rebound, changed = module_bindings(module)
                        c.require(not set(mapped) & (rebound | changed), 'INSTANCE_IMPORT_REASSIGNED')
                        return canonical_function(node, mapped, {})
                    fn, bound = instances.bind(cls, original, member, tree, sources, canonical_instance)
                    family = 'atomic_file'
                elif owner is None and delegated.looking(original, tree):
                    c.require('os' in aliases.values(), 'REUSE_CONTEXT_CLEANUP_API_REQUIRED')
                    c.require(not bound_globals & {'Exception', 'BaseException', 'ValueError', 'object'}, 'REUSE_SHADOWED_BUILTIN')
                    helper, fn, bound = delegated.bind(original, tree, lambda node: canonical_function(node, aliases, {}))
                    c.require(bound['class_name'] not in mutated_globals, 'DELEGATED_CLASS_MUTATED')
                    family = 'atomic_context'
                    original = helper
                    owner = bound['class_name']
                    symbol = bound['repair_symbol']
                elif generator:
                    c.require('os' in aliases.values(), 'REUSE_CONTEXT_CLEANUP_API_REQUIRED')
                    c.require('BaseException' not in bound_globals, 'REUSE_SHADOWED_BUILTIN')
                    family, bound = ('atomic_context', contexts.bind(fn))
                    if bound['kind'] == 'FD_GENERATOR_CONTEXT':
                        contexts.fd_module(tree, aliases)
                elif isinstance(fn, ast.AsyncFunctionDef):
                    c.require(not bound_globals & {'Exception', 'BaseException'}, 'REUSE_SHADOWED_BUILTIN')
                    family, bound = ('async_resource', async_binding(fn))
                elif any((ast.unparse(n.func) == 'os.replace' for n in ast.walk(fn) if isinstance(n, ast.Call))):
                    family, bound = ('atomic_file', atomic.binding(ast.unparse(fn) + '\n'))
                elif any((ast.unparse(n.func) == 'cachetools.TTLCache' for n in ast.walk(fn) if isinstance(n, ast.Call))):
                    family, bound = ('elapsed_ttl', clock_binding(fn))
                elif owner is None:
                    family, bound = ('atomic_context', context_binding(fn, tree))
                else:
                    raise ValueError('REUSE_UNSUPPORTED_API')
                code = ast.unparse(fn) + '\n'
                accepted.append(dict(id=sha(member + '::' + symbol)[:20], member=member, symbol=symbol, family=family, binding=bound, original_code=ast.get_source_segment(sources[repair_member], original), aliases=repair_aliases, code=code, code_sha256=sha(code), member_sha256=sha(text), line=original.lineno, end_line=original.end_lineno, modules_imported=False, semantics_inferred=False))
                if repair_member != member or 'module_graph' in bound:
                    accepted[-1].update(repair_member=repair_member, repair_member_sha256=sha(sources[repair_member]))
            except (ValueError, SyntaxError) as exc:
                held.append(dict(member=member, symbol=symbol, reason=str(exc)))
    c.require(len(accepted) <= LIMITS['sites'], 'REUSE_SITE_LIMIT')
    return c.seal(dict(accepted=accepted, held=held, index=index, snapshot_sha256=c.digest(sources), target_name_branches=0, target_specific_adapter_count=0))

def bind_contract(site, contracts):
    family = site['family']
    record = contracts.get(family)
    c.require(type(record) is dict and set(record) == {'id', 'basis', 'scope'} and (record['id'] == CONTRACTS[family]) and (type(record['basis']) is str) and record['basis'] and (type(record['scope']) is str) and record['scope'], 'REUSE_OWNER_CONTRACT_REQUIRED')
    return c.seal(dict(family=family, declaration=record, structural_binding=site['binding'], code_sha256=site['code_sha256'], source_is_oracle=False))

def hypothesis(record, sources):
    """Hypothesis."""
    fields = {'family', 'conditions', 'faults', 'source_id', 'span'}
    c.require(type(record) is dict and set(record) in (fields, fields | {'condition_programs'}), 'REUSE_HYPOTHESIS_FIELDS')
    c.require(record['family'] in FAMILIES and type(record['conditions']) is list and (1 <= len(record['conditions']) <= 8) and all((type(s) is str and 0 < len(s) <= 300 for s in record['conditions'])), 'REUSE_HYPOTHESIS_CONDITIONS')
    faults = record['faults']
    programs = record.get('condition_programs', [])
    c.require(type(programs) is list and len(programs) <= 3, 'REUSE_CONDITION_PROGRAM_LIMIT')
    for program in programs:
        conditions.checked(program, sources)
        c.require(program['family'] == record['family'] and program['source_id'] == record['source_id'], 'REUSE_CONDITION_SOURCE')
    ids = [p['condition_id'] for p in programs]
    c.require(len(set(ids)) == len(ids), 'REUSE_CONDITION_DUPLICATE')
    c.require(type(faults) is list and 1 <= len(faults) <= LIMITS['probes'] and (len(set(faults)) == len(faults)) and all((x in (*OPERATIONS[record['family']], *ids) for x in faults)) and all((i in faults for i in ids)), 'REUSE_HYPOTHESIS_OPERATIONS')
    c.require(record['source_id'] in sources, 'REUSE_SOURCE_MISSING')
    text = sources[record['source_id']]
    c.require(type(text) is str and 0 < len(text.encode()) <= 262144, 'REUSE_SOURCE_BYTES')
    span = record['span']
    c.require(type(span) is dict and set(span) == {'start', 'end', 'sha256'} and (type(span['start']) is int) and (type(span['end']) is int) and (0 <= span['start'] < span['end'] <= len(text)) and (sha(text[span['start']:span['end']]) == span['sha256']), 'REUSE_SOURCE_SPAN')
    return c.seal(dict(**record, source_sha256=sha(text), semantic_support_certified=False, target_applicability_certified=False, execution_authority=False))

def project_incident_set(ir, text):
    """Project incident set."""
    c.check_seal(ir)
    c.require(ir['contract_type'] == 'IncidentHypothesisSet' and ir['status'] == 'SILVER_CANDIDATE' and (ir['source']['source_document_sha256'] == sha(text)), 'REUSE_INCIDENT_SOURCE')
    spans = {s['evidence_id']: s for s in ir['evidence_spans']}
    c.require(len(spans) == len(ir['evidence_spans']), 'REUSE_INCIDENT_SPAN_DUPLICATE')
    source_id = ir['source']['source_record_id']
    hs = []
    held = []
    for assertion in ir['observed_assertions']:
        primitive = [a['value'] for a in assertion['arguments'] if a['role'] == 'primitive']
        if len(primitive) != 1 or primitive[0] not in PRIMITIVE_CAPABILITIES:
            held.append(dict(assertion_id=assertion['assertion_id'], reason='UNSUPPORTED_PRIMITIVE'))
            continue
        c.require(assertion['evidence_ids'] and all((e in spans for e in assertion['evidence_ids'])), 'REUSE_INCIDENT_EVIDENCE_MISSING')
        for evidence_id in assertion['evidence_ids']:
            s = spans[evidence_id]
            quote = text[s['start_char']:s['end_char']]
            c.require(quote == s['text'] and sha(quote) == s['content_hash'], 'REUSE_INCIDENT_SPAN_DRIFT')
        if len(assertion['statement']) > 300:
            held.append(dict(assertion_id=assertion['assertion_id'], reason='CONDITION_LENGTH_UNSUPPORTED'))
            continue
        family, fault = PRIMITIVE_CAPABILITIES[primitive[0]]
        s = spans[assertion['evidence_ids'][0]]
        hs.append(hypothesis(dict(family=family, conditions=[assertion['statement']], faults=[fault], source_id=source_id, span=dict(start=s['start_char'], end=s['end_char'], sha256=s['content_hash'])), {source_id: text}))
    return c.seal(dict(incident_ir_sha256=c.digest(ir), hypotheses=hs, held=held, canonicalization_authorized=False, semantic_support_certified=False, schema_validation_not_performed=True))

def hypothesis_input(value):
    return {k: value[k] for k in ('family', 'conditions', 'faults', 'source_id', 'span', 'condition_programs') if k in value}

def propose(site, hypotheses, maximum_probes=3, qualification_hypotheses=None, include_owned_grid=False):
    c.require(type(maximum_probes) is int and 1 <= maximum_probes <= LIMITS['probes'], 'REUSE_PROBE_LIMIT')
    ordered = []
    refs = []
    programs = conditions.pool(hypotheses if qualification_hypotheses is None else qualification_hypotheses)
    if include_owned_grid:
        generic, _ = conditions.owned_qualification()
        geometry = lambda p: (p['operation'], p['phase'], p['occurrence'])
        for program in conditions.pool(generic).values():
            if conditions.supported(site, program) and len(programs) < 3 and (not any((geometry(p) == geometry(program) for p in programs.values()))):
                programs[program['condition_id']] = program
    supported = {k: v for k, v in programs.items() if conditions.supported(site, v)}
    held = [dict(condition_id=k, reason='UNSUPPORTED_CONDITION_BINDING') for k in programs if k not in supported]
    for h in hypotheses:
        c.check_seal(h)
        if h['family'] == site['family']:
            refs.append(c.digest(h))
            ordered.extend((x for x in h['faults'] if x not in ordered and (x in OPERATIONS[site['family']] or x in supported)))
    ordered.extend((x for x in OPERATIONS[site['family']] if x not in ordered))
    ordered.extend((x for x in supported if x not in ordered))
    proposal = dict(family=site['family'], faults=ordered[:maximum_probes], hypotheses=refs, condition_generation='STRUCTURED_HYPOTHESIS_COMPOSITION', probability=None)
    if programs:
        proposal.update(condition_programs=supported, held_conditions=held, qualification_faults=[*OPERATIONS[site['family']], *supported], condition_generation='BOUNDED_LIFECYCLE_CONDITION_COMPOSITION', source_text_to_program_automatic=False, qualification_envelope_shared=True)
    if include_owned_grid:
        proposal['generic_program_pool_source_input_independent'] = True
        proposal['qualification_envelope_shared'] = False
    return c.seal(proposal)

def qualification_faults(site, proposal):
    return proposal.get('qualification_faults', list(OPERATIONS[site['family']]))

def candidate(site):
    family = site['family']
    code = site['code']
    fn = ast.parse(code).body[0]
    if family == 'atomic_file':
        return atomic.repair(code)
    if family == 'async_resource':
        if site['binding']['protected']:
            return code
        bound = site['binding']
        resource = bound['resource_parameter']
        work = bound['work_parameter']
        operation = f"{bound['result_variable']} = await {work}()" if bound['returns_result'] else f'await {work}()'
        tail = f"    return {bound['result_variable']}\n" if bound['returns_result'] else ''
        fixed = f'async def f({resource}, {work}):\n    await {resource}.acquire()\n    try:\n        {operation}\n    finally:\n        {resource}.release()\n' + tail
        fn.body = ast.parse(fixed).body[0].body
    elif family == 'elapsed_ttl':
        call = fn.body[0].value
        next((k for k in call.keywords if k.arg == 'timer')).value = ast.Name(id=fn.args.args[1].arg, ctx=ast.Load())
    elif family == 'atomic_context':
        kind = site['binding'].get('kind')
        return contexts.repair(code) if kind in contexts.GENERATOR_KINDS else delegated.repair(code) if kind == delegated.KIND else serialized.repair(code) if kind == serialized.KIND else None
    ast.fix_missing_locations(fn)
    return ast.unparse(fn) + '\n'

def apply_candidate(sources, site, code):
    c.require(type(code) is str and (site['family'] != 'atomic_context' or site['binding'].get('kind') in (*contexts.GENERATOR_KINDS, delegated.KIND, serialized.KIND)), 'REUSE_PATCH_SCOPE')
    c.require(sha(sources[site['member']]) == site['member_sha256'], 'REUSE_PATCH_SOURCE_DRIFT')
    repair_member = site.get('repair_member', site['member'])
    if 'module_graph' in site['binding']:
        graph = site['binding']['module_graph']
        c.require(graph['entry_member'] == site['member'] and graph['repair_member'] == repair_member and (set(graph['modules']) == set(graph['source_sha256'])), 'REUSE_PATCH_MODULE_IDENTITY')
        c.require(all((n in sources and sha(sources[n]) == h for n, h in graph['source_sha256'].items())), 'REUSE_PATCH_DEPENDENCY_DRIFT')
        c.require(sha(sources[repair_member]) == site['repair_member_sha256'], 'REUSE_PATCH_SOURCE_DRIFT')
    tree = ast.parse(code)
    c.require(len(tree.body) == 1 and isinstance(tree.body[0], (ast.FunctionDef, ast.AsyncFunctionDef)), 'REUSE_PATCH_SINGLE_FUNCTION')
    fn = tree.body[0]
    c.require(not fn.decorator_list and fn.returns is None, 'REUSE_PATCH_CANONICAL_FUNCTION')
    original = ast.parse(site['code']).body[0]
    c.require(type(fn) is type(original) and fn.name == original.name and (ast.dump(fn.args) == ast.dump(original.args)), 'REUSE_PATCH_SIGNATURE')
    if site['family'] == 'atomic_file':
        atomic.binding(code)
    elif site['family'] == 'async_resource':
        bound = async_binding(fn)
        c.require(bound['returns_result'] == site['binding']['returns_result'], 'REUSE_PATCH_RETURN_SEMANTICS')
    elif site['family'] == 'elapsed_ttl':
        clock_binding(fn)
    elif site['family'] == 'atomic_context':
        if site['binding'].get('kind') == serialized.KIND:
            bound = serialized.bind_backend(fn)
            fields = ('kind', 'io_kind', 'temporary', 'stream', 'descriptor', 'path_parameter', 'payload_parameter', 'backend_profile', 'payload_write_style')
        elif site['binding'].get('kind') == delegated.KIND:
            bound = delegated.lifecycle(fn)
            fields = ('receiver', 'factory_parameter', 'stream', 'options_field', 'sync_method', 'commit_method', 'rollback_method', 'lifecycle_style')
        else:
            bound = contexts.bind(fn)
            fields = ('kind', 'temporary', 'stream', 'path_parameter', 'mode_parameter', 'default_mode')
            if bound['kind'] == 'FD_GENERATOR_CONTEXT':
                fields = (*fields, 'descriptor')
        c.require(all((bound[k] == site['binding'][k] for k in fields)), 'REUSE_PATCH_CONTEXT_SEMANTICS')
    inverse = {'Path' if v == 'pathlib.Path' else v: k for k, v in site['aliases'].items()}

    class RestoreAliases(ast.NodeTransformer):

        def visit_Attribute(self, n):
            name = ast.unparse(n)
            if name in inverse:
                return ast.copy_location(ast.Name(id=inverse[name], ctx=n.ctx), n)
            return self.generic_visit(n)

        def visit_Name(self, n):
            if isinstance(n.ctx, ast.Load) and n.id in inverse:
                return ast.copy_location(ast.Name(id=inverse[n.id], ctx=n.ctx), n)
            return n
    if site['binding'].get('instance'):
        fn = instances.restore(fn, site['binding']['instance'])
    restored = RestoreAliases().visit(fn)
    creator = site['binding'].get('temporary_creator')
    if creator is not None:
        creations = [n for n in ast.walk(fn) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call) and (ast.unparse(n.value.func) in ('tempfile.mkstemp', inverse.get('tempfile.mkstemp')))]
        c.require(len(creations) == 1, 'REUSE_PATCH_CREATOR_COUNT')
        expected = RestoreAliases().visit(ast.parse(creator['expanded_call'], mode='eval').body)
        c.require(ast.dump(creations[0].value) == ast.dump(expected), 'REUSE_PATCH_CREATOR_SEMANTICS')
        creations[0].value = ast.parse(creator['original_call'], mode='eval').body
    raw_fn = next((n for n in ast.walk(ast.parse(sources[repair_member])) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.lineno == site['line']))
    restored.args = deepcopy(raw_fn.args)
    restored.returns = deepcopy(raw_fn.returns)
    if site['family'] == 'atomic_context':
        restored.decorator_list = deepcopy(raw_fn.decorator_list)
    if raw_fn.body and isinstance(raw_fn.body[0], ast.Expr) and isinstance(raw_fn.body[0].value, ast.Constant) and isinstance(raw_fn.body[0].value.value, str):
        restored.body.insert(0, deepcopy(raw_fn.body[0]))
    ast.fix_missing_locations(restored)
    code = ast.unparse(restored) + '\n'
    lines = sources[repair_member].splitlines(keepends=True)
    declaration = lines[site['line'] - 1]
    indent = declaration[:len(declaration) - len(declaration.lstrip(' \t'))] if '.' in site['symbol'] else ''
    if indent:
        decorator = '' if site['binding'].get('instance') or site['binding'].get('kind') == delegated.KIND else indent + '@staticmethod\n'
        code = decorator + ''.join((indent + x + '\n' for x in code.rstrip().splitlines()))
    start = site['line'] - 1
    if raw_fn.decorator_list:
        first = min((n.lineno for n in raw_fn.decorator_list))
        starts = [token.start[0] - 1 for token in tokenize.generate_tokens(io.StringIO(sources[repair_member]).readline) if token.type == tokenize.OP and token.string == '@' and (token.start[1] == raw_fn.col_offset) and (token.start[0] <= first)]
        c.require(starts, 'REUSE_PATCH_DECORATOR_SPAN')
        start = max(starts)
    result = dict(sources)
    result[repair_member] = ''.join(lines[:start]) + code.rstrip() + '\n' + ''.join(lines[site['end_line']:])
    ast.parse(result[repair_member])
    return result

def dependency_key(site, sources, contract, proposal, method, runtime, dependency=None):
    return c.digest(dict(site=site, snapshot=c.digest(sources), contract=contract, proposal=proposal, method=method, runtime=runtime, dependency=dependency))

def compose_patches(sources, rows):
    """Compose patches."""
    selected = {}
    for row in rows:
        if row['observed']['repair_pass'] is not True:
            continue
        identifier = row['site_id']
        code = row['observed']['candidate_code']
        c.require(identifier not in selected or selected[identifier] == code, 'REUSE_CONFLICTING_REPAIRS')
        selected[identifier] = code
    revised = dict(sources)
    for identifier, code in sorted(selected.items()):
        site = next((s for s in inventory(revised)['accepted'] if s['id'] == identifier), None)
        c.require(site is not None, 'REUSE_COMPOSE_BINDING_LOST')
        revised = apply_candidate(revised, site, code)
    return {member: text for member, text in revised.items() if text != sources[member]}
