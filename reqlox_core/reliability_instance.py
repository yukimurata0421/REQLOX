"Finite reliability controls and verification."
import ast
from copy import deepcopy
import hashlib
from pathlib import PurePosixPath

from . import incident_reference as c
from . import repository_atomic_write as atomic

DESTINATION = 'instance_destination'


def sha(value):
    return hashlib.sha256(value.encode()).hexdigest()


def literal(node):
    return isinstance(node, ast.Constant) and (node.value is None or type(node.value) in (str, int, bool))


def body(fn):
    rows = fn.body
    if rows and isinstance(rows[0], ast.Expr) and isinstance(rows[0].value, ast.Constant) and isinstance(rows[0].value.value, str):
        rows = rows[1:]
    return rows


def closed_namespace(tree):
    for node in tree.body:
        declaration = isinstance(node,(ast.Import,ast.ImportFrom,ast.FunctionDef,ast.ClassDef))
        doc = isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str)
        constant = (isinstance(node,ast.Assign) and literal(node.value)
                    and all(isinstance(t,ast.Name) for t in node.targets))
        c.require(declaration or doc or constant,'INSTANCE_MODULE_EFFECT')
        if isinstance(node,ast.FunctionDef):
            c.require(not node.decorator_list and all(literal(x) for x in (*node.args.defaults,*[d for d in node.args.kw_defaults if d is not None])),
                      'INSTANCE_MODULE_DECLARATION_EFFECT')
        if isinstance(node,ast.ClassDef):
            c.require(not node.decorator_list and not node.keywords,'INSTANCE_MODULE_DECLARATION_EFFECT')
            c.require(all(isinstance(n,ast.FunctionDef) or isinstance(n,ast.Expr)
                          and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str) for n in node.body),
                      'INSTANCE_MODULE_CLASS_EFFECT')
        declarations = ([node] if isinstance(node,ast.FunctionDef) else
                        [n for n in node.body if isinstance(n,ast.FunctionDef)] if isinstance(node,ast.ClassDef) else [])
        for fn in declarations:
            defaults = (*fn.args.defaults,*[d for d in fn.args.kw_defaults if d is not None])
            annotations = [a.annotation for a in (*fn.args.posonlyargs,*fn.args.args,*fn.args.kwonlyargs) if a.annotation is not None]
            if fn.returns is not None:annotations.append(fn.returns)
            c.require(all(literal(v) for v in defaults)
                      and not any(isinstance(n,ast.Call) for annotation in annotations for n in ast.walk(annotation)),
                      'INSTANCE_MODULE_DECLARATION_EFFECT')


def arguments(fn, call, receiver=None):
    "Arguments."
    a = fn.args
    c.require(not a.posonlyargs and a.vararg is None and a.kwarg is None, 'INSTANCE_HELPER_SIGNATURE')
    c.require(all(literal(v) for v in (*a.defaults,*[d for d in a.kw_defaults if d is not None])), 'INSTANCE_HELPER_DEFAULT')
    names = [x.arg for x in a.args] + [x.arg for x in a.kwonlyargs]
    positional = ([receiver] if receiver is not None else []) + list(call.args)
    c.require(len(positional) <= len(a.args), 'INSTANCE_HELPER_ARGUMENTS')
    defaults = dict(zip([x.arg for x in a.args][-len(a.defaults):], a.defaults)) if a.defaults else {}
    defaults.update({x.arg:v for x,v in zip(a.kwonlyargs,a.kw_defaults) if v is not None})
    values = dict(zip(names, positional))
    for keyword in call.keywords:
        c.require(keyword.arg in names and keyword.arg not in values, 'INSTANCE_HELPER_KEYWORDS')
        values[keyword.arg] = keyword.value
    for name in names:
        if name not in values:
            c.require(name in defaults and literal(defaults[name]), 'INSTANCE_HELPER_DEFAULT')
            values[name] = defaults[name]
    c.require(all(isinstance(v, ast.Name) or literal(v)
                  or isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name) for v in values.values()),
              'INSTANCE_HELPER_EFFECTFUL_ARGUMENT')
    return values


def imported_helper(member, tree, name, sources):
    "Imported helper."
    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)
               and any((a.asname or a.name) == name for a in n.names)]
    c.require(len(imports) == 1, 'INSTANCE_HELPER_UNRESOLVED')
    declaration = imports[0]
    selected = next(a for a in declaration.names if (a.asname or a.name) == name)
    c.require(selected.name != '*' and declaration.module, 'INSTANCE_HELPER_MODULE')
    if declaration.level:
        parent = PurePosixPath(member).parent
        c.require(declaration.level <= len(parent.parts), 'INSTANCE_HELPER_RELATIVE_ROOT')
        for _ in range(declaration.level-1):
            parent = parent.parent
        stems = [str(parent / declaration.module.replace('.', '/'))]
    else:
        stem = declaration.module.replace('.', '/')
        stems = [stem, 'src/'+stem]
    candidates = [p for stem in stems for p in (stem+'.py',stem+'/__init__.py') if p in sources]
    c.require(len(candidates) == 1, 'INSTANCE_HELPER_MODULE_AMBIGUOUS')
    target = candidates[0]; module = ast.parse(sources[target])
    definitions = [n for n in module.body if isinstance(n, ast.FunctionDef) and n.name == selected.name]
    c.require(len(definitions) == 1, 'INSTANCE_HELPER_DEFINITION')
    return target, module, definitions[0]


def bind(cls, original, member, tree, sources, canonical):
    closed_namespace(tree)
    c.require(not cls.bases and not cls.keywords and not cls.decorator_list, 'INSTANCE_CLASS_PROTOCOL')
    c.require(all(isinstance(n, ast.FunctionDef) or isinstance(n, ast.Expr)
                  and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str) for n in cls.body),
              'INSTANCE_CLASS_NAMESPACE')
    methods = {n.name:n for n in cls.body if isinstance(n, ast.FunctionDef)}
    c.require(len(methods) == sum(isinstance(n, ast.FunctionDef) for n in cls.body)
              and '__init__' in methods and all(not n.decorator_list for n in methods.values())
              and not any(n.startswith('__') and n != '__init__' for n in methods), 'INSTANCE_DYNAMIC_PROTOCOL')
    init = methods['__init__']; a = init.args
    c.require(not a.posonlyargs and a.vararg is None and a.kwarg is None
              and 2 <= len(a.args)+len(a.kwonlyargs) <= 5 and a.args,
              'INSTANCE_CONSTRUCTOR_SIGNATURE')
    receiver = a.args[0].arg
    parameters = [n.arg for n in a.args][1:]+[n.arg for n in a.kwonlyargs]
    defaults = dict(zip([n.arg for n in a.args][-len(a.defaults):],a.defaults)) if a.defaults else {}
    defaults.update({n.arg:v for n,v in zip(a.kwonlyargs,a.kw_defaults) if v is not None})
    required = [name for name in parameters if name not in defaults]
    c.require(len(required) == 1 and all(literal(v) for v in defaults.values()), 'INSTANCE_CONSTRUCTOR_DEFAULTS')
    path = required[0]
    fields = {}; path_field = None; conversion = None
    normalized_init = canonical(init, member, tree)
    for row in body(normalized_init):
        c.require(isinstance(row, ast.Assign) and len(row.targets) == 1
                  and isinstance(row.targets[0], ast.Attribute) and isinstance(row.targets[0].value, ast.Name)
                  and row.targets[0].value.id == receiver, 'INSTANCE_CONSTRUCTOR_EFFECT')
        field = row.targets[0].attr
        c.require(field not in fields and not field.startswith('__'), 'INSTANCE_FIELD_REBINDING')
        value = row.value
        converted = isinstance(value, ast.Call) and ast.unparse(value.func) == 'Path' and len(value.args) == 1 and not value.keywords
        input_value = value.args[0] if converted else value
        if isinstance(input_value, ast.Name) and input_value.id == path:
            c.require(path_field is None, 'INSTANCE_DESTINATION_AMBIGUOUS')
            path_field = field; conversion = 'Path' if converted else None
            fields[field] = ast.Name(id=DESTINATION, ctx=ast.Load())
        else:
            if isinstance(value,ast.Name) and value.id in defaults:
                value = defaults[value.id]
            c.require(literal(value), 'INSTANCE_FIELD_VALUE')
            fields[field] = deepcopy(value)
    c.require(path_field is not None and len(fields) <= 5, 'INSTANCE_DESTINATION_FIELD')
    a = original.args
    c.require(not original.decorator_list and not a.posonlyargs and not a.defaults
              and not a.vararg and not a.kwarg and a.args and len(a.args)+len(a.kwonlyargs) == 2
              and all(v is None for v in a.kw_defaults), 'INSTANCE_OPERATION_SIGNATURE')
    operation_receiver = a.args[0].arg
    payload = ([n.arg for n in a.args]+[n.arg for n in a.kwonlyargs])[1]
    names = {n.id for n in ast.walk(cls) if isinstance(n, ast.Name)}
    c.require(DESTINATION not in names and payload != DESTINATION, 'INSTANCE_RESERVED_NAME')
    projections = []
    for field,value in list(fields.items()):
        if field == path_field:continue
        name = 'instance_field_'+str(len(projections))
        c.require(name not in names,'INSTANCE_RESERVED_NAME')
        projections.append(dict(field=field,name=name,value=value.value))
        fields[field] = ast.Name(id=name,ctx=ast.Load())
    closure = []

    def expand(fn, location, module, level=0, seen=()):
        c.require(level <= 2 and len(ast.unparse(fn).encode()) <= 4096, 'INSTANCE_HELPER_BOUND')
        identity = location+'::'+fn.name
        c.require(identity not in seen, 'INSTANCE_HELPER_CYCLE')
        local_receiver = fn.args.args[0].arg if methods.get(fn.name) is fn and fn.args.args else operation_receiver
        class Expand(ast.NodeTransformer):
            def visit_Expr(self, row):
                call = row.value
                if not isinstance(call, ast.Call):
                    return self.generic_visit(row)
                self_call = (isinstance(call.func, ast.Attribute) and isinstance(call.func.value, ast.Name)
                             and call.func.value.id == local_receiver and call.func.attr in methods)
                local = [n for n in module.body if isinstance(n, ast.FunctionDef)
                         and isinstance(call.func, ast.Name) and n.name == call.func.id]
                imported = (isinstance(call.func, ast.Name) and any(isinstance(n, ast.ImportFrom)
                            and any((a.asname or a.name) == call.func.id for a in n.names) for n in module.body))
                if not (self_call or local or imported):
                    return self.generic_visit(row)
                c.require(level < 2, 'INSTANCE_HELPER_DEPTH')
                if self_call:
                    helper = methods[call.func.attr]; origin = location; mod = module
                    runtime_name = helper.name; owner = cls.name; actual_receiver = call.func.value
                elif local:
                    c.require(len(local) == 1, 'INSTANCE_HELPER_DEFINITION')
                    helper = local[0]; origin = location; mod = module
                    runtime_name = call.func.id; owner = None; actual_receiver = None
                else:
                    origin, mod, helper = imported_helper(location, module, call.func.id, sources)
                    runtime_name = call.func.id; owner = None; actual_receiver = None
                c.require(not helper.decorator_list and len(body(helper)) == 1 and isinstance(body(helper)[0], ast.Expr),
                          'INSTANCE_HELPER_SHAPE')
                closed_namespace(mod)
                
                def assignments(node):
                    if isinstance(node, (ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
                        return []
                    return [n.id for n in ast.walk(node) if isinstance(n,ast.Name) and isinstance(n.ctx,ast.Store)]
                c.require(not any(helper.name in assignments(n) or runtime_name in assignments(n) for n in mod.body),
                          'INSTANCE_HELPER_REASSIGNED')
                values = arguments(helper, call, actual_receiver)
                expanded = expand(helper, origin, mod, level+1, (*seen, identity))
                class Substitute(ast.NodeTransformer):
                    def visit_Name(self, n):
                        return deepcopy(values.get(n.id,n))
                result = Substitute().visit(deepcopy(body(expanded)[0]))
                raw = canonical(helper, origin, mod)
                raw.name = runtime_name
                entry = dict(owner=owner,name=runtime_name,member=origin,member_sha256=sha(sources[origin]),code=ast.unparse(raw)+'\n')
                c.require(all((e['owner'],e['name']) != (owner,runtime_name) or e == entry for e in closure),
                          'INSTANCE_HELPER_RUNTIME_COLLISION')
                if entry not in closure:
                    c.require(len(closure) < 8, 'INSTANCE_HELPER_COUNT'); closure.append(entry)
                return result
        return canonical(Expand().visit(deepcopy(fn)), location, module)

    projected = expand(original, member, tree)
    class Fields(ast.NodeTransformer):
        def visit_Attribute(self, node):
            if isinstance(node.value, ast.Name) and node.value.id == operation_receiver:
                c.require(isinstance(node.ctx, ast.Load) and node.attr in fields, 'INSTANCE_FIELD_MUTATION_OR_UNKNOWN')
                return deepcopy(fields[node.attr])
            return self.generic_visit(node)
    projected = Fields().visit(projected)
    c.require(not any(isinstance(n, ast.ExceptHandler) for n in ast.walk(projected)), 'INSTANCE_EXCEPTION_HANDLER_HELD')
    c.require(not any(isinstance(n,ast.Name) and n.id == operation_receiver for n in ast.walk(ast.Module(body=projected.body,type_ignores=[]))),
              'INSTANCE_UNRESOLVED_RECEIVER')
    c.require(not any(isinstance(n,ast.Return) and n.value is not None for n in ast.walk(projected)), 'INSTANCE_RETURN_SEMANTICS')
    projected.args = ast.arguments(posonlyargs=[],args=[ast.arg(arg=DESTINATION),ast.arg(arg=payload)],
                                   kwonlyargs=[],kw_defaults=[],defaults=[],vararg=None,kwarg=None)
    if conversion:
        projected.body.insert(0,ast.parse(f'{DESTINATION} = Path({DESTINATION})').body[0])
    offset = bool(conversion)
    for index,projection in enumerate(projections):
        projected.body.insert(offset+index,ast.Assign(targets=[ast.Name(id=projection['name'],ctx=ast.Store())],value=ast.Constant(value=projection['value'])))
    ast.fix_missing_locations(projected); code = ast.unparse(projected)+'\n'; bound = atomic.binding(code)
    target = canonical(original, member, tree)
    bound['instance'] = dict(kind='CLOSED_INSTANCE_OPERATION',class_name=cls.name,operation=original.name,
        receiver=operation_receiver,path_field=path_field,payload_parameter=payload,
        constructor_parameter=path,constructor_keyword_only=path in [n.arg for n in init.args.kwonlyargs],
        payload_keyword_only=bool(original.args.kwonlyargs),path_conversion=conversion,
        field_projections=projections,constructor_options='DECLARED_LITERAL_DEFAULTS_ONLY',
        constructor_code=ast.unparse(normalized_init)+'\n',operation_code=ast.unparse(target)+'\n',
        helper_closure=closure,projected_code=code,closure_semantics_inferred=False)
    return projected, bound


def restore(fn, bound):
    result = deepcopy(fn)
    if bound['path_conversion']:
        expected = ast.parse(f'{DESTINATION} = Path({DESTINATION})').body[0]
        c.require(result.body and ast.dump(result.body[0]) == ast.dump(expected), 'INSTANCE_PATCH_CONSTRUCTOR_FLOW')
        result.body = result.body[1:]
    fields = {DESTINATION:bound['path_field']}
    for projection in bound.get('field_projections',[]):
        expected = ast.Assign(targets=[ast.Name(id=projection['name'],ctx=ast.Store())],value=ast.Constant(value=projection['value']))
        c.require(result.body and ast.dump(result.body[0]) == ast.dump(expected),'INSTANCE_PATCH_FIELD_FLOW')
        result.body = result.body[1:];fields[projection['name']] = projection['field']
    class Fields(ast.NodeTransformer):
        def visit_Name(self, node):
            if node.id in fields:
                c.require(isinstance(node.ctx, ast.Load), 'INSTANCE_PATCH_DESTINATION_MUTATION')
                return ast.Attribute(value=ast.Name(id=bound['receiver'],ctx=ast.Load()),attr=fields[node.id],ctx=ast.Load())
            return node
    result = Fields().visit(result)
    result.args = deepcopy(ast.parse(bound['operation_code']).body[0].args)
    ast.fix_missing_locations(result)
    return result


def callable_factory(bound, code, scope):
    "Callable factory."
    functions = [ast.parse(bound['constructor_code']).body[0]]
    target = (ast.parse(bound['operation_code']).body[0] if code == bound['projected_code']
              else restore(ast.parse(code).body[0], bound))
    functions.append(target); globals_ = []
    for helper in bound['helper_closure']:
        node = ast.parse(helper['code']).body[0]
        (functions if helper['owner'] is not None else globals_).append(node)
    cls = ast.ClassDef(name=bound['class_name'],bases=[],keywords=[],body=functions,decorator_list=[])
    module = ast.Module(body=[*globals_,cls],type_ignores=[]);ast.fix_missing_locations(module)
    ns = dict(scope,__name__='closed_instance',__builtins__={'__build_class__':__build_class__})
    exec(compile(module,'<closed-instance-operation>','exec'),ns)
    def invoke(destination, payload):
        instance = (ns[bound['class_name']](**{bound['constructor_parameter']:destination})
                    if bound['constructor_keyword_only'] else ns[bound['class_name']](destination))
        operation = getattr(instance,bound['operation'])
        return operation(**{bound['payload_parameter']:payload}) if bound['payload_keyword_only'] else operation(payload)
    return invoke
