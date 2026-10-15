"Finite reliability controls and verification."
import ast
from copy import deepcopy
import json

import incident_reference as c
import reliability_context as contexts

KIND = 'SERIALIZED_ATOMIC_CONTEXT'
PROFILES = ('TEXT_UTF8', 'JSON_OBJECT_UTF8')
MAXIMUM_HELPER_DEPTH = 2


def _body(fn):
    rows = fn.body
    return rows[1:] if rows and isinstance(rows[0], ast.Expr) and isinstance(rows[0].value, ast.Constant) and type(rows[0].value.value) is str else rows


def signature(fn):
    a = fn.args
    c.require(isinstance(fn, ast.FunctionDef) and not fn.decorator_list and len(a.args) == 2
              and not a.posonlyargs and not a.kwonlyargs and not a.defaults
              and a.vararg is None and a.kwarg is None and len(ast.unparse(fn).encode()) <= 4096,
              'SERIALIZED_SIGNATURE')
    c.require(a.args[0].arg != a.args[1].arg, 'SERIALIZED_PARAMETER_ALIAS')
    return [v.arg for v in a.args]


def looking(original, tree):
    "Looking."
    functions = {n.name:n for n in tree.body if isinstance(n, ast.FunctionDef)}
    aliases = {}
    for n in tree.body:
        if isinstance(n, ast.Import):
            aliases.update({a.asname or a.name:a.name for a in n.names})
        elif isinstance(n, ast.ImportFrom) and n.level==0:
            aliases.update({a.asname or a.name:n.module+'.'+a.name for a in n.names})
    def visit(fn, depth, seen):
        if fn.name in seen or depth > MAXIMUM_HELPER_DEPTH or any(isinstance(n, (ast.Yield, ast.YieldFrom)) for n in ast.walk(fn)):
            return False
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)]
        for call in calls:
            name = ast.unparse(call.func)
            if isinstance(call.func, ast.Name):name=aliases.get(name,name)
            elif isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name):
                name=aliases.get(call.func.value.id,call.func.value.id)+'.'+call.func.attr
            if name.endswith('.NamedTemporaryFile') and any(k.arg == 'mode' and isinstance(k.value, ast.Constant) and k.value.value == 'w' for k in call.keywords):
                return True
            if name.endswith('.fdopen') and len(call.args) >= 2 and isinstance(call.args[1], ast.Constant) and call.args[1].value == 'w':
                return True
        return any(isinstance(call.func, ast.Name) and call.func.id in functions
                   and visit(functions[call.func.id], depth+1, (*seen, fn.name)) for call in calls)
    return visit(original, 0, ())


def profile(expression, parameter):
    if isinstance(expression, ast.Name) and expression.id == parameter:
        return dict(format='TEXT_UTF8', options={})
    c.require(isinstance(expression, ast.Call) and ast.unparse(expression.func) == 'json.dumps'
              and len(expression.args) == 1 and isinstance(expression.args[0], ast.Name)
              and expression.args[0].id == parameter, 'SERIALIZED_PAYLOAD_FLOW')
    values = {k.arg:k.value for k in expression.keywords}
    c.require(len(values) == len(expression.keywords) and set(values) <= {'ensure_ascii', 'sort_keys', 'indent'},
              'SERIALIZED_JSON_OPTIONS')
    options = {}
    for name, value in values.items():
        c.require(isinstance(value, ast.Constant), 'SERIALIZED_JSON_OPTIONS')
        v = value.value
        c.require((type(v) is bool if name != 'indent' else v is None or type(v) is int and 0 <= v <= 8),
                  'SERIALIZED_JSON_OPTIONS')
        options[name] = v
    return dict(format='JSON_OBJECT_UTF8', options=options)


def bind_backend(fn):
    path, payload = signature(fn)
    virtual = deepcopy(fn)
    virtual.args.args = virtual.args.args[:1]
    virtual.body = deepcopy(_body(fn))
    writes = [n for n in ast.walk(virtual) if isinstance(n, ast.With)]
    c.require(len(writes) == 1 and len(writes[0].items) == 1, 'SERIALIZED_SINGLE_STREAM')
    write = writes[0]
    item = write.items[0]
    c.require(isinstance(item.optional_vars, ast.Name) and isinstance(item.context_expr, ast.Call), 'SERIALIZED_STREAM_BINDING')
    stream = item.optional_vars.id
    opened = item.context_expr
    values = {k.arg:k.value for k in opened.keywords}
    c.require(len(values) == len(opened.keywords) and 'encoding' in values
              and isinstance(values['encoding'], ast.Constant) and values['encoding'].value == 'utf-8',
              'SERIALIZED_UTF8_REQUIRED')
    opened.keywords = [k for k in opened.keywords if k.arg != 'encoding']
    payload_writes = [n for n in write.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
                      and ast.unparse(n.value.func) in (stream+'.write','json.dump')]
    c.require(1 <= len(payload_writes) <= 2, 'SERIALIZED_SINGLE_PAYLOAD_WRITE')
    operation = payload_writes[0]
    if ast.unparse(operation.value.func)=='json.dump':
        c.require(len(operation.value.args)==2 and isinstance(operation.value.args[1],ast.Name)
                  and operation.value.args[1].id==stream, 'SERIALIZED_JSON_STREAM_FLOW')
        expression=deepcopy(operation.value);expression.func=ast.parse('json.dumps',mode='eval').body
        expression.args=expression.args[:1];declared=profile(expression,payload);style='JSON_DUMP'
    else:
        c.require(len(operation.value.args) == 1 and not operation.value.keywords, 'SERIALIZED_WRITE_ARGUMENT')
        declared = profile(operation.value.args[0], payload);style='TEXT_WRITE'
    if len(payload_writes)==2:
        suffix=payload_writes[1]
        c.require(declared['format']=='JSON_OBJECT_UTF8' and ast.unparse(suffix.value.func)==stream+'.write'
                  and len(suffix.value.args)==1 and not suffix.value.keywords
                  and isinstance(suffix.value.args[0],ast.Constant) and suffix.value.args[0].value=='\n'
                  and write.body.index(suffix)==write.body.index(operation)+1, 'SERIALIZED_JSON_NEWLINE')
        declared['trailing_newline']=True;write.body.remove(suffix)
    position = write.body.index(operation)
    write.body[position] = ast.Expr(value=ast.Yield(value=ast.Name(id=stream, ctx=ast.Load())))
    ast.fix_missing_locations(virtual)
    context = contexts.bind(virtual)
    c.require(context['default_mode'] == 'w' and context['mode_parameter'] is None, 'SERIALIZED_TEXT_MODE')
    c.require(payload not in {path, context['temporary'], stream, context.get('descriptor')}, 'SERIALIZED_LOCAL_ALIAS')
    return dict(kind=KIND, io_kind=context['kind'], temporary=context['temporary'], stream=stream,
                descriptor=context.get('descriptor'), path_parameter=path, payload_parameter=payload,
                backend_profile=declared, payload_write_style=style, protected=context['protected'],
                descriptor_open_failure_qualified=False, input_domain_qualified=False)


def module_guard(tree, aliases):
    allowed = {'os', 'tempfile', 'pathlib', 'json', '__future__'}
    postponed = any(isinstance(n, ast.ImportFrom) and n.module == '__future__'
                    and any(a.name == 'annotations' for a in n.names) for n in tree.body)
    names = set()
    assigned = set()
    for n in tree.body:
        if isinstance(n, ast.Import):
            c.require(all(a.name in allowed for a in n.names), 'SERIALIZED_MODULE_IMPORT')
        elif isinstance(n, ast.ImportFrom):
            c.require(n.level == 0 and n.module in allowed and all(a.name != '*' for a in n.names), 'SERIALIZED_MODULE_IMPORT')
        elif isinstance(n, ast.Expr):
            c.require(isinstance(n.value, ast.Constant) and type(n.value.value) is str, 'SERIALIZED_MODULE_EFFECT')
        elif isinstance(n, ast.Assign):
            c.require(all(isinstance(t, ast.Name) for t in n.targets), 'SERIALIZED_MODULE_EFFECT')
            try:
                value = ast.literal_eval(n.value)
            except (ValueError, TypeError):
                raise ValueError('SERIALIZED_MODULE_EFFECT')
            c.require(type(value) in (str, int, bool, type(None)) or type(value) in (list, tuple)
                      and len(value) <= 128 and all(type(x) is str for x in value), 'SERIALIZED_MODULE_EFFECT')
            assigned.update(t.id for t in n.targets)
        elif isinstance(n, ast.FunctionDef):
            c.require(n.name not in names and not n.decorator_list, 'SERIALIZED_MODULE_DECLARATION')
            names.add(n.name)
            defaults = (*n.args.defaults, *[x for x in n.args.kw_defaults if x is not None])
            annotations = [a.annotation for a in (*n.args.posonlyargs, *n.args.args, *n.args.kwonlyargs) if a.annotation is not None]
            if n.returns is not None:
                annotations.append(n.returns)
            c.require(all(isinstance(v, ast.Constant) for v in defaults), 'SERIALIZED_DECLARATION_EFFECT')
            c.require(not any(isinstance(v,ast.Call) for a in annotations for v in ast.walk(a)), 'SERIALIZED_DECLARATION_EFFECT')
            if not postponed:
                c.require(all(isinstance(a, ast.Constant) or isinstance(a, ast.Name) and a.id in
                              ('str', 'int', 'dict', 'list', 'tuple', 'object', 'bytes', 'bool', 'float') for a in annotations),
                          'SERIALIZED_DECLARATION_EFFECT')
        else:
            raise ValueError('SERIALIZED_MODULE_EFFECT')
    c.require(not (set(aliases) & names), 'SERIALIZED_IMPORTED_API_REDEFINED')
    c.require(not (assigned & (names | set(aliases))), 'SERIALIZED_GLOBAL_REASSIGNMENT')


def expand_creator(fn, functions, canonical):
    "Expand creator."
    revised = deepcopy(fn)
    creators = [n for n in ast.walk(revised) if isinstance(n, ast.Assign)
                and isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
                and n.value.func.id in functions]
    if not creators:
        return revised, None
    c.require(len(creators) == 1, 'SERIALIZED_CREATOR_COUNT')
    assignment = creators[0]; call = assignment.value
    c.require(len(call.args) == 1 and not call.keywords and isinstance(call.args[0], ast.Name)
              and call.args[0].id == revised.args.args[0].arg, 'SERIALIZED_CREATOR_PATH')
    helper = canonical(functions[call.func.id]); a = helper.args; rows = _body(helper)
    c.require(not helper.decorator_list and len(a.args) == 1 and not a.posonlyargs and not a.kwonlyargs
              and not a.defaults and a.vararg is None and a.kwarg is None
              and len(rows) == 1 and isinstance(rows[0], ast.Return)
              and isinstance(rows[0].value, ast.Call)
              and ast.unparse(rows[0].value.func) == 'tempfile.mkstemp', 'SERIALIZED_CREATOR_OWNERSHIP')
    parameter = a.args[0].arg
    class Substitute(ast.NodeTransformer):
        def visit_Name(self, node):
            return ast.copy_location(deepcopy(call.args[0]), node) if node.id == parameter else node
    expression = Substitute().visit(deepcopy(rows[0].value))
    assignment.value = expression
    ast.fix_missing_locations(revised)
    
    bind_backend(revised)
    return revised, dict(kind='EXCLUSIVE_MKSTEMP_FACTORY_V1', symbol=call.func.id,
                         original_call=ast.unparse(call), expanded_call=ast.unparse(expression),
                         helper_code_sha256=c.digest(ast.dump(helper)),
                         exclusive_creation=True, concurrent_behavior_qualified=False,
                         creation_failure_qualified=False)


def bind(original, tree, canonical, *, module_for=None):
    functions = {n.name:n for n in tree.body if isinstance(n, ast.FunctionDef)}
    entry = canonical(original)
    path, payload = signature(entry)
    chain = []
    selected = None
    fn = entry
    raw = original
    seen = []
    for depth in range(MAXIMUM_HELPER_DEPTH+1):
        c.require(id(raw) not in seen, 'SERIALIZED_HELPER_CYCLE')
        seen.append(id(raw))
        if module_for is not None:
            functions, canonical = module_for(raw)
        rows = _body(fn)
        
        if any(isinstance(n, ast.With) for n in ast.walk(fn)):
            fn, creator = expand_creator(fn, functions, canonical)
            bound = bind_backend(fn)
            if creator is not None:
                bound['temporary_creator'] = creator
            if selected is None:
                selected = bound['backend_profile']
            else:
                c.require(bound['backend_profile']['format'] == 'TEXT_UTF8', 'SERIALIZED_DOUBLE_SERIALIZATION')
            bound.update(entry_symbol=entry.name, repair_symbol=fn.name, caller_profile=selected,
                         entry_path_parameter=path, entry_payload_parameter=payload,
                         call_graph=chain, serialized_flow_ir=dict(kind='BOUNDED_SERIALIZED_FILE_FLOW_V1',
                             operations=['SERIALIZE' if selected['format'] == 'JSON_OBJECT_UTF8' else 'TEXT_INPUT',
                                         'OWNED_TEMP_CREATE', 'PAYLOAD_WRITE', 'STREAM_FLUSH', 'FSYNC',
                                         'STREAM_CLOSE', 'REPLACE', 'OWNED_TEMP_CLEANUP'],
                             helper_depth=depth, cleanup_present=bound['protected'],
                             semantic_support_certified=False, execution_authority=False))
            return raw, fn, bound
        signature(fn)
        c.require(not (set(signature(fn)) & set(functions)), 'SERIALIZED_SHADOWED_HELPER')
        c.require(depth < MAXIMUM_HELPER_DEPTH and len(rows) in (1,2) and isinstance(rows[-1], (ast.Expr, ast.Return)),
                  'SERIALIZED_WRAPPER_SHAPE')
        assigned_profile=None;argument=fn.args.args[1].arg
        if len(rows)==2:
            assignment=rows[0]
            c.require(isinstance(assignment,ast.Assign) and len(assignment.targets)==1
                      and isinstance(assignment.targets[0],ast.Name), 'SERIALIZED_WRAPPER_ASSIGNMENT')
            argument=assignment.targets[0].id
            c.require(argument not in {*signature(fn),*functions}, 'SERIALIZED_WRAPPER_ASSIGNMENT')
            assigned_profile=profile(assignment.value,fn.args.args[1].arg)
            c.require(assigned_profile['format']=='JSON_OBJECT_UTF8', 'SERIALIZED_WRAPPER_ASSIGNMENT')
        call = rows[-1].value
        c.require(isinstance(call, ast.Call) and isinstance(call.func, ast.Name) and call.func.id in functions
                  and len(call.args) == 2 and not call.keywords and isinstance(call.args[0], ast.Name)
                  and call.args[0].id == fn.args.args[0].arg, 'SERIALIZED_WRAPPER_FLOW')
        local_profile = profile(call.args[1], argument)
        if assigned_profile is not None:
            c.require(local_profile['format']=='TEXT_UTF8','SERIALIZED_DOUBLE_SERIALIZATION')
            local_profile=assigned_profile
        if local_profile['format'] == 'JSON_OBJECT_UTF8':
            c.require(selected is None, 'SERIALIZED_DOUBLE_SERIALIZATION')
            selected = local_profile
        chain.append(dict(caller=fn.name, callee=call.func.id,
                          path_argument=fn.args.args[0].arg, payload_argument=fn.args.args[1].arg,
                          input_profile=local_profile, serialized_variable=argument if assigned_profile is not None else None,
                          return_style='RETURN' if isinstance(rows[-1], ast.Return) else 'IMPLICIT_NONE'))
        raw = functions[call.func.id]
        fn = canonical(raw)
    raise ValueError('SERIALIZED_HELPER_DEPTH')


def repair(code):
    fn = ast.parse(code).body[0]
    bound = bind_backend(fn)
    if bound['protected']:
        return code
    temporary = bound['temporary']
    body = ast.parse(f'''def f():
    {temporary} = None
    try:
        pass
    finally:
        if {temporary} is not None and os.path.exists({temporary}):
            os.unlink({temporary})
''').body[0].body
    body[1].body = deepcopy(fn.body)
    fn.body = body
    ast.fix_missing_locations(fn)
    fixed = ast.unparse(fn)+'\n'
    bind_backend(fn)
    return fixed


def sample(declared, case='BASE'):
    "Sample."
    c.require(declared['format'] in PROFILES and case in ('BASE', 'EMPTY', 'UNICODE'), 'SERIALIZED_INPUT_PROFILE')
    payload = ({'record': 7} if case == 'BASE' else {} if case == 'EMPTY' else {'\u8a18\u9332': '\u5024', 'items': [1, None, True]}) \
              if declared['format'] == 'JSON_OBJECT_UTF8' else ('new' if case == 'BASE' else '' if case == 'EMPTY' else '\u8a18\u9332\n\u5024')
    content = json.dumps(payload, **declared['options']) if declared['format'] == 'JSON_OBJECT_UTF8' else payload
    if declared.get('trailing_newline'):content+='\n'
    return payload, content.encode('utf-8')
