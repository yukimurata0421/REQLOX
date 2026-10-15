"Finite reliability controls and verification."
import ast
from copy import deepcopy
import hashlib
from pathlib import PurePosixPath

from . import incident_reference as c

LIMITS = dict(files=1024, file_bytes=262144, total_bytes=16777216, function_bytes=4096,
              targets=8, child_cpu_seconds=2, child_wall_seconds=5,
              child_memory_bytes=134217728, output_bytes=131072)
FAULTS = ('WRITE', 'FSYNC', 'REPLACE')
CONTRACT = ('Write the supplied bytes atomically. On a write, fsync, or replacement exception, '
            'preserve the prior destination, remove only this invocation\'s temporary file, '
            'propagate the exception, and allow a subsequent invocation. An already existing '
            'temporary file belongs to a different invocation and must be preserved.')
SOURCE_CONTROL = ('Constructed reliability lesson: a failure during write or fsync occurs before '
                  'the replacement cleanup block. A delete=False temporary file can remain. '
                  'Check failures before replacement as well as replacement itself.')


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def checked_path(name):
    c.require(type(name) is str, 'ATOMIC_MEMBER_PATH')
    path = PurePosixPath(name)
    c.require(not path.is_absolute() and '..' not in path.parts and str(path) == name
              and '\\' not in name, 'ATOMIC_MEMBER_PATH')


def binding(code):
    "Binding."
    c.require(type(code) is str and 0 < len(code.encode()) <= LIMITS['function_bytes'], 'ATOMIC_FUNCTION_BOUND')
    tree = ast.parse(code)
    c.require(len(tree.body) == 1 and isinstance(tree.body[0], ast.FunctionDef), 'ATOMIC_FUNCTION')
    fn = tree.body[0]
    args = fn.args
    c.require(not fn.decorator_list and not args.posonlyargs and len(args.args) == 2
              and not args.defaults and not args.kwonlyargs and not args.vararg and not args.kwarg,
              'ATOMIC_SIGNATURE')
    forbidden = (ast.Import, ast.ImportFrom, ast.While, ast.For, ast.AsyncFor, ast.Lambda,
                 ast.ClassDef, ast.Global, ast.Nonlocal, ast.ListComp, ast.SetComp, ast.DictComp,
                 ast.GeneratorExp, ast.NamedExpr)
    c.require(not any(isinstance(n, forbidden) or isinstance(n, ast.Attribute) and n.attr.startswith('_')
                      for n in ast.walk(fn)), 'ATOMIC_FINITE_GRAMMAR')
    c.require(sum(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) for n in ast.walk(fn)) == 1,
              'ATOMIC_NESTED_FUNCTION')
    attrs = {'mkdir', 'with_name', 'open', 'write', 'flush', 'fileno', 'fsync', 'replace',
             'getpid', 'NamedTemporaryFile', 'exists', 'unlink'}
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
    c.require(all(isinstance(n.func, ast.Name) and n.func.id == 'Path'
                  or isinstance(n.func, ast.Attribute) and n.func.attr in attrs for n in calls),
              'ATOMIC_CALL_GRAMMAR')
    replaces = [n for n in calls if isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name)
                and n.func.value.id == 'os' and n.func.attr == 'replace']
    c.require(len(replaces) == 1 and len(replaces[0].args) == 2
              and all(isinstance(n, ast.Name) for n in replaces[0].args), 'ATOMIC_REPLACE_BINDING')
    temporary, destination = [n.id for n in replaces[0].args]
    c.require(destination == args.args[0].arg and temporary != destination, 'ATOMIC_DESTINATION')
    writes = [(i, n) for i, n in enumerate(fn.body) if isinstance(n, ast.With)]
    
    if not writes:
        writes = [(None, n) for n in ast.walk(fn) if isinstance(n, ast.With)]
    c.require(len(writes) == 1 and len(writes[0][1].items) == 1, 'ATOMIC_WITH_BINDING')
    index, write = writes[0]
    context = write.items[0].context_expr
    c.require(isinstance(context, ast.Call) and isinstance(context.func, ast.Attribute), 'ATOMIC_TEMP_BINDING')
    if isinstance(context.func.value, ast.Name) and context.func.value.id == temporary and context.func.attr == 'open':
        c.require(len(context.args) == 1 and isinstance(context.args[0], ast.Constant)
                  and context.args[0].value == 'xb', 'ATOMIC_EXCLUSIVE_CREATE')
        kind = 'EXCLUSIVE_PATH'
    else:
        c.require(isinstance(context.func.value, ast.Name) and context.func.value.id == 'tempfile'
                  and context.func.attr == 'NamedTemporaryFile'
                  and any(k.arg == 'delete' and isinstance(k.value, ast.Constant)
                          and k.value.value is False for k in context.keywords), 'ATOMIC_NAMED_TEMP')
        kind = 'NAMED_TEMP'
        c.require(any(isinstance(n, ast.Assign) and len(n.targets) == 1
                      and isinstance(n.targets[0], ast.Name) and n.targets[0].id == temporary
                      for n in write.body), 'ATOMIC_TEMP_ASSIGNMENT')
    return dict(symbol=fn.name, parameters=[n.arg for n in args.args], kind=kind,
                temporary=temporary, code_sha256=sha(code), with_index=index)


def discover(sources):
    c.require(type(sources) is dict and 0 < len(sources) <= LIMITS['files'], 'ATOMIC_REPO_FILES')
    total = 0
    for name, text in sources.items():
        checked_path(name)
        c.require(type(text) is str and len(text.encode()) <= LIMITS['file_bytes'], 'ATOMIC_REPO_FILE_BYTES')
        total += len(text.encode())
    c.require(total <= LIMITS['total_bytes'], 'ATOMIC_REPO_BYTES')
    accepted, held = [], []
    for name, text in sorted(sources.items()):
        if not name.endswith('.py') or any(p.startswith('test') for p in PurePosixPath(name).parts):
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError:
            held.append(dict(member=name, reason='UNSUPPORTED_SYNTAX'))
            continue
        for fn in tree.body:
            if not isinstance(fn, ast.FunctionDef):
                continue
            if not any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                       and isinstance(n.func.value, ast.Name) and n.func.value.id == 'os'
                       and n.func.attr == 'replace' for n in ast.walk(fn)):
                continue
            code = ast.get_source_segment(text, fn)
            try:
                found = binding(code)
            except (ValueError, SyntaxError) as exc:
                held.append(dict(member=name, symbol=fn.name, reason=str(exc)))
                continue
            accepted.append(dict(member=name, line=fn.lineno, end_line=fn.end_lineno,
                                 source_sha256=sha(text), code=code, **found))
    c.require(len(accepted) <= LIMITS['targets'], 'ATOMIC_TARGET_BOUND')
    return c.seal(dict(accepted=accepted, held=held, files_scanned=len(sources), bytes_scanned=total,
                       snapshot_sha256=c.digest(sources), modules_imported=False,
                       target_specific_adapter_count=0, owner_semantics_inferred=False))


def repair(code):
    bound = binding(code)
    fn = ast.parse(code).body[0]
    if bound['with_index'] is None:
        final = ast.parse('if temporary_created:\n    ' + bound['temporary'] + '.unlink(missing_ok=True)').body
        wrappers = [n for n in fn.body if isinstance(n, ast.Try)
                    and ast.dump(ast.Module(body=n.finalbody, type_ignores=[]))
                    == ast.dump(ast.Module(body=final, type_ignores=[]))]
        flag_false = ast.dump(ast.parse('temporary_created = False').body[0])
        flag_true = ast.dump(ast.parse('temporary_created = True').body[0])
        c.require(len(wrappers) == 1 and fn.body[-1] is wrappers[0]
                  and ast.dump(fn.body[-2]) == flag_false
                  and isinstance(wrappers[0].body[0], ast.With), 'ATOMIC_ALREADY_WRAPPED_OR_UNSUPPORTED')
        write = wrappers[0].body[0]
        guard_index = 0 if bound['kind'] == 'EXCLUSIVE_PATH' else 1
        c.require(len(write.body) > guard_index and ast.dump(write.body[guard_index]) == flag_true,
                  'ATOMIC_ALREADY_WRAPPED_OR_UNSUPPORTED')
        return code
    names = {n.id for n in ast.walk(fn) if isinstance(n, ast.Name)}
    flag = 'temporary_created'
    c.require(flag not in names, 'ATOMIC_REPAIR_NAME_COLLISION')
    index = bound['with_index']
    write = fn.body[index]
    set_flag = ast.parse(flag + ' = True').body[0]
    if bound['kind'] == 'EXCLUSIVE_PATH':
        write.body.insert(0, set_flag)
    else:
        assignment = next(i for i, n in enumerate(write.body) if isinstance(n, ast.Assign)
                          and isinstance(n.targets[0], ast.Name) and n.targets[0].id == bound['temporary'])
        write.body.insert(assignment + 1, set_flag)
    final = ast.parse('if ' + flag + ':\n    ' + bound['temporary'] + '.unlink(missing_ok=True)').body
    wrapped = ast.Try(body=fn.body[index:], handlers=[], orelse=[], finalbody=final)
    fn.body[index:] = [ast.parse(flag + ' = False').body[0], wrapped]
    ast.fix_missing_locations(fn)
    result = ast.unparse(fn) + '\n'
    binding(result)
    return result


def compile_function(code, scope):
    bound = binding(code)
    fn = deepcopy(ast.parse(code).body[0])
    
    fn.returns = None
    for arg in fn.args.args:
        arg.annotation = None
    tree = ast.Module(body=[fn], type_ignores=[])
    ast.fix_missing_locations(tree)
    namespace = dict(scope, __builtins__={})
    exec(compile(tree, '<owned-atomic-write>', 'exec'), namespace)
    return namespace[bound['symbol']]


def probe_order(source):
    "Probe order."
    if source is None:
        return ['REPLACE', 'WRITE', 'FSYNC']
    c.require(type(source) is str and len(source.encode()) <= 4096, 'ATOMIC_SOURCE_BOUND')
    lower = source.lower()
    first = 'FSYNC' if 'fsync' in lower else 'WRITE' if 'write' in lower else 'REPLACE'
    return [first] + [n for n in ('REPLACE', 'WRITE', 'FSYNC') if n != first]
