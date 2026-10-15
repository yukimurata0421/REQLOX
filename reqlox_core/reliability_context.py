"Finite reliability controls and verification."
import ast
from copy import deepcopy

from . import incident_reference as c

GENERATOR_KINDS=('GENERATOR_CONTEXT','FD_GENERATOR_CONTEXT')

def body_shape(body):
    return ast.dump(ast.Module(body=body, type_ignores=[]))


def bind_generator(fn):
    c.require(isinstance(fn, ast.FunctionDef) and len(ast.unparse(fn).encode()) <= 4096, 'CONTEXT_FUNCTION_BOUND')
    args = fn.args
    parameters = [a.arg for a in args.args] + [a.arg for a in args.kwonlyargs]
    c.require(1 <= len(parameters) <= 2 and args.args and not args.posonlyargs
              and args.vararg is None and args.kwarg is None, 'CONTEXT_SIGNATURE')
    path = args.args[0].arg
    defaults = dict(zip([a.arg for a in args.args][-len(args.defaults):], args.defaults)) if args.defaults else {}
    defaults.update(zip([a.arg for a in args.kwonlyargs], args.kw_defaults))
    c.require(path not in defaults, 'CONTEXT_PATH_DEFAULT')
    yielded = [n for n in ast.walk(fn) if isinstance(n, ast.Yield)]
    c.require(len(yielded) == 1 and isinstance(yielded[0].value, ast.Name), 'CONTEXT_SINGLE_YIELD')
    stream = yielded[0].value.id
    writes = [n for n in ast.walk(fn) if isinstance(n, ast.With)]
    c.require(len(writes) == 1 and len(writes[0].items) == 1, 'CONTEXT_SINGLE_WITH')
    write = writes[0]; item = write.items[0]; call = item.context_expr
    c.require(isinstance(item.optional_vars, ast.Name) and item.optional_vars.id == stream
              and isinstance(call, ast.Call) and ast.unparse(call.func) == 'tempfile.NamedTemporaryFile'
              and not call.args, 'CONTEXT_UNIQUE_TEMPORARY')
    values = {k.arg:k.value for k in call.keywords}
    c.require(len(values) == len(call.keywords) and set(values) >= {'mode','delete','dir'}
              and set(values) <= {'mode','delete','dir','prefix','suffix'}
              and isinstance(values['delete'], ast.Constant) and values['delete'].value is False,
              'CONTEXT_TEMPORARY_ARGUMENTS')
    c.require(ast.unparse(values['dir']) in (f'os.path.dirname({path})', f'Path({path}).parent'),
              'CONTEXT_DESTINATION_DIRECTORY')
    c.require(all(isinstance(values[k], ast.Constant) and type(values[k].value) is str
                  and len(values[k].value) <= 100 for k in ('prefix','suffix') if k in values), 'CONTEXT_TEMPORARY_NAMES')
    mode = values['mode']; mode_parameter = None
    if isinstance(mode, ast.Name):
        mode_parameter = mode.id
        c.require(mode_parameter in defaults and mode_parameter != path, 'CONTEXT_MODE_FLOW')
        mode = defaults[mode_parameter]
    c.require(isinstance(mode, ast.Constant) and mode.value in ('w','wb')
              and parameters == ([path] if mode_parameter is None else [path,mode_parameter]), 'CONTEXT_FILE_MODE')
    c.require(write.body and isinstance(write.body[0], ast.Assign) and len(write.body[0].targets) == 1
              and isinstance(write.body[0].targets[0], ast.Name), 'CONTEXT_TEMPORARY_BINDING')
    temporary = write.body[0].targets[0].id
    c.require(len({path, stream, temporary, *([mode_parameter] if mode_parameter else [])}) == 3 + bool(mode_parameter),
              'CONTEXT_LOCAL_SHADOW')
    expected = ast.parse(f'''def f():
    {temporary} = {stream}.name
    yield {stream}
    {stream}.flush()
    os.fsync({stream}.fileno())
''').body[0].body
    rename = ast.parse(f'os.replace({temporary}, {path})').body[0]
    guarded = ast.parse(f'''def f():
    {temporary} = {stream}.name
    try:
        yield {stream}
        {stream}.flush()
        os.fsync({stream}.fileno())
    except BaseException:
        os.unlink({temporary})
        raise
''').body[0].body
    guarded_rename = ast.parse(f'''def f():
    try:
        os.replace({temporary}, {path})
    except BaseException:
        os.unlink({temporary})
        raise
''').body[0].body[0]
    style = 'PLAIN' if body_shape(write.body) == body_shape(expected) else 'SPLIT_GUARDS'
    c.require(style == 'PLAIN' or body_shape(write.body) == body_shape(guarded), 'CONTEXT_FINITE_WRITE_BODY')
    original = [deepcopy(write),rename if style == 'PLAIN' else guarded_rename]
    protected = ast.parse(f'''def f():
    {temporary} = None
    try:
        pass
    finally:
        if {temporary} is not None and os.path.exists({temporary}):
            os.unlink({temporary})
''').body[0].body
    protected[1].body = deepcopy(original)
    shape = body_shape(fn.body)
    c.require(shape in (body_shape(original), body_shape(protected)), 'CONTEXT_FINITE_LIFECYCLE')
    return dict(kind='GENERATOR_CONTEXT', temporary=temporary, stream=stream, path_parameter=path,
                mode_parameter=mode_parameter, default_mode=mode.value, protected=shape == body_shape(protected),
                lifecycle_style=style)


def bind_fd_generator(fn):
    "Bind fd generator."
    c.require(isinstance(fn,ast.FunctionDef) and len(ast.unparse(fn).encode())<=4096,'FD_CONTEXT_FUNCTION_BOUND')
    args=fn.args;parameters=[a.arg for a in args.args]+[a.arg for a in args.kwonlyargs]
    c.require(1<=len(parameters)<=2 and args.args and not args.posonlyargs
              and args.vararg is None and args.kwarg is None,'FD_CONTEXT_SIGNATURE')
    path=args.args[0].arg
    defaults=dict(zip([a.arg for a in args.args][-len(args.defaults):],args.defaults)) if args.defaults else {}
    defaults.update(zip([a.arg for a in args.kwonlyargs],args.kw_defaults))
    c.require(path not in defaults,'FD_CONTEXT_PATH_DEFAULT')
    acquisitions=[n for n in ast.walk(fn) if isinstance(n,ast.Assign) and isinstance(n.value,ast.Call)
                  and ast.unparse(n.value.func)=='tempfile.mkstemp']
    c.require(len(acquisitions)==1,'FD_CONTEXT_UNIQUE_ACQUISITION');acquire=acquisitions[0];call=acquire.value
    c.require(len(acquire.targets)==1 and isinstance(acquire.targets[0],ast.Tuple)
              and len(acquire.targets[0].elts)==2 and all(isinstance(n,ast.Name) for n in acquire.targets[0].elts)
              and not call.args,'FD_CONTEXT_OWNED_DESCRIPTOR')
    descriptor,temporary=[n.id for n in acquire.targets[0].elts]
    values={k.arg:k.value for k in call.keywords}
    c.require(len(values)==len(call.keywords) and 'dir' in values and set(values)<={'dir','prefix','suffix'},
              'FD_CONTEXT_TEMPORARY_ARGUMENTS')
    c.require(ast.unparse(values['dir']) in (f'os.path.dirname({path})',f'Path({path}).parent'),
              'FD_CONTEXT_DESTINATION_DIRECTORY')
    c.require(all(isinstance(values[k],ast.Constant) and type(values[k].value) is str
                  and len(values[k].value)<=100 for k in ('prefix','suffix') if k in values),'FD_CONTEXT_TEMPORARY_NAMES')
    writes=[n for n in ast.walk(fn) if isinstance(n,ast.With)]
    c.require(len(writes)==1 and len(writes[0].items)==1,'FD_CONTEXT_SINGLE_WITH');write=writes[0];item=write.items[0]
    opened=item.context_expr
    c.require(isinstance(item.optional_vars,ast.Name) and isinstance(opened,ast.Call)
              and ast.unparse(opened.func)=='os.fdopen' and len(opened.args)==2 and not opened.keywords
              and isinstance(opened.args[0],ast.Name) and opened.args[0].id==descriptor,'FD_CONTEXT_FDOPEN_FLOW')
    stream=item.optional_vars.id;mode=opened.args[1];mode_parameter=None
    if isinstance(mode,ast.Name):
        mode_parameter=mode.id;c.require(mode_parameter in defaults and mode_parameter!=path,'FD_CONTEXT_MODE_FLOW')
        mode=defaults[mode_parameter]
    c.require(isinstance(mode,ast.Constant) and mode.value in ('w','wb')
              and parameters==([path] if mode_parameter is None else [path,mode_parameter]),'FD_CONTEXT_MODE')
    c.require(len({path,descriptor,temporary,stream,*([mode_parameter] if mode_parameter else [])})==4+bool(mode_parameter),
              'FD_CONTEXT_LOCAL_SHADOW')
    expected=ast.parse(f'''def f():
    yield {stream}
    {stream}.flush()
    os.fsync({stream}.fileno())
''').body[0].body
    c.require(body_shape(write.body)==body_shape(expected),'FD_CONTEXT_FINITE_WRITE_BODY')
    rename=ast.parse(f'os.replace({temporary}, {path})').body[0]
    original=[deepcopy(acquire),deepcopy(write),rename]
    protected=ast.parse(f'''def f():
    {temporary} = None
    try:
        pass
    finally:
        if {temporary} is not None and os.path.exists({temporary}):
            os.unlink({temporary})
''').body[0].body
    protected[1].body=deepcopy(original);shape=body_shape(fn.body)
    c.require(shape in (body_shape(original),body_shape(protected)),'FD_CONTEXT_FINITE_LIFECYCLE')
    return dict(kind='FD_GENERATOR_CONTEXT',temporary=temporary,stream=stream,descriptor=descriptor,
                path_parameter=path,mode_parameter=mode_parameter,default_mode=mode.value,
                protected=shape==body_shape(protected),lifecycle_style='PLAIN',
                descriptor_open_failure_qualified=False)


def bind(fn):
    return bind_fd_generator(fn) if any(isinstance(n,ast.Call) and ast.unparse(n.func)=='tempfile.mkstemp'
                                      for n in ast.walk(fn)) else bind_generator(fn)


def fd_module(tree,aliases):
    "Fd module."
    allowed={'os','tempfile','contextlib','pathlib','__future__'}
    for node in tree.body:
        if isinstance(node,ast.Import):
            c.require(all(a.name in allowed for a in node.names),'FD_CONTEXT_MODULE_IMPORT')
        elif isinstance(node,ast.ImportFrom):
            c.require(node.level==0 and node.module in allowed and all(a.name!='*' for a in node.names),
                      'FD_CONTEXT_MODULE_IMPORT')
        elif isinstance(node,ast.Expr):
            c.require(isinstance(node.value,ast.Constant) and type(node.value.value) is str,'FD_CONTEXT_MODULE_EFFECT')
        elif isinstance(node,ast.Assign):
            c.require(isinstance(node.value,ast.Constant) and all(isinstance(t,ast.Name) for t in node.targets),
                      'FD_CONTEXT_MODULE_EFFECT')
        elif isinstance(node,ast.FunctionDef):
            for decorator in node.decorator_list:
                name=ast.unparse(decorator)
                canonical=aliases.get(name,name) if isinstance(decorator,ast.Name) else (
                    aliases.get(decorator.value.id,decorator.value.id)+'.'+decorator.attr
                    if isinstance(decorator,ast.Attribute) and isinstance(decorator.value,ast.Name) else '')
                c.require(canonical=='contextlib.contextmanager','FD_CONTEXT_MODULE_DECLARATION_EFFECT')
            defaults=(*node.args.defaults,*[d for d in node.args.kw_defaults if d is not None])
            annotations=[a.annotation for a in (*node.args.posonlyargs,*node.args.args,*node.args.kwonlyargs) if a.annotation is not None]
            if node.returns is not None:annotations.append(node.returns)
            c.require(all(isinstance(v,ast.Constant) for v in defaults)
                      and not any(isinstance(n,ast.Call) for annotation in annotations for n in ast.walk(annotation)),
                      'FD_CONTEXT_MODULE_DECLARATION_EFFECT')
        else:raise ValueError('FD_CONTEXT_MODULE_EFFECT')


def repair(code):
    fn = ast.parse(code).body[0]; bound = bind(fn)
    if bound['protected']: return code
    name = bound['temporary']
    body = ast.parse(f'''def f():
    {name} = None
    try:
        pass
    finally:
        if {name} is not None and os.path.exists({name}):
            os.unlink({name})
''').body[0].body
    body[1].body = deepcopy(fn.body); fn.body = body
    ast.fix_missing_locations(fn)
    fixed = ast.unparse(fn) + '\n'; bind(fn)
    return fixed
