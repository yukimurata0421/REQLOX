"Finite reliability controls and verification."
import ast
from copy import deepcopy
import sys

import incident_reference as c

KIND = 'DELEGATED_GENERATOR_CONTEXT'


def rows(fn):
    body = fn.body
    return body[1:] if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str) else body


def shape(body):
    return ast.dump(ast.Module(body=body, type_ignores=[]))


def constant(node, tree, seen=()):
    "Constant."
    if isinstance(node, ast.Constant): return node.value
    if isinstance(node, ast.Name):
        c.require(node.id not in seen and len(seen)<4, 'DELEGATED_DEFAULT_CYCLE')
        found=[r.value for r in tree.body if isinstance(r,ast.Assign) and len(r.targets)==1
               and isinstance(r.targets[0],ast.Name) and r.targets[0].id==node.id]
        c.require(len(found)==1, 'DELEGATED_DEFAULT_BINDING')
        return constant(found[0],tree,(*seen,node.id))
    if isinstance(node,ast.Compare):
        c.require(ast.unparse(node)=='sys.version_info[0] == 2', 'DELEGATED_DEFAULT_EXPRESSION')
        return sys.version_info[0]==2
    if isinstance(node,ast.IfExp):
        condition=constant(node.test,tree,seen)
        c.require(type(condition) is bool,'DELEGATED_DEFAULT_EXPRESSION')
        return constant(node.body if condition else node.orelse,tree,seen)
    raise ValueError('DELEGATED_DEFAULT_EXPRESSION')


def lifecycle(fn):
    a=fn.args
    c.require(not fn.decorator_list and not a.posonlyargs and len(a.args)==2 and not a.defaults
              and not a.kwonlyargs and a.vararg is None and a.kwarg is None,
              'DELEGATED_GENERATOR_SIGNATURE')
    receiver,factory=[p.arg for p in a.args]
    c.require(len(ast.unparse(fn).encode())<=4096,'DELEGATED_GENERATOR_BOUND')
    body=rows(fn)
    c.require(body and isinstance(body[0],ast.Assign) and len(body[0].targets)==1
              and isinstance(body[0].targets[0],ast.Name) and isinstance(body[0].value,ast.Constant)
              and body[0].value.value is None,'DELEGATED_STREAM_INITIALIZATION')
    stream=body[0].targets[0].id
    guard=ast.parse(f'''def f():
    try:
        pass
    finally:
        if {stream} is not None and os.path.exists({stream}.name):
            os.unlink({stream}.name)
''').body[0].body[0]
    protected=(len(body)==2 and isinstance(body[1],ast.Try) and not body[1].handlers
               and not body[1].orelse and shape(body[1].finalbody)==shape(guard.finalbody))
    inner=body[1].body if protected else body[1:]
    withs=[n for row in inner for n in ast.walk(row) if isinstance(n,ast.With)]
    c.require(len(withs)==1 and len(withs[0].items)==1,'DELEGATED_SINGLE_WITH')
    item=withs[0].items[0];call=item.context_expr
    c.require(isinstance(item.optional_vars,ast.Name) and item.optional_vars.id==stream
              and isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id==factory
              and not call.args and len(call.keywords)==1 and call.keywords[0].arg is None
              and isinstance(call.keywords[0].value,ast.Attribute)
              and isinstance(call.keywords[0].value.value,ast.Name)
              and call.keywords[0].value.value.id==receiver,'DELEGATED_FACTORY_ARGUMENTS')
    options=call.keywords[0].value.attr
    sync_calls=[n for n in ast.walk(withs[0]) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)
                and isinstance(n.func.value,ast.Name) and n.func.value.id==receiver]
    c.require(len(sync_calls)==1,'DELEGATED_SYNC_BINDING');sync=sync_calls[0].func.attr
    
    block=inner[0].body if len(inner)==1 and isinstance(inner[0],ast.Try) else inner
    position=next((i for i,n in enumerate(block) if n is withs[0]),None)
    c.require(position is not None and position+1<len(block),'DELEGATED_COMMIT_BINDING')
    commit_node=block[position+1]
    c.require(isinstance(commit_node,ast.Expr) and isinstance(commit_node.value,ast.Call)
              and isinstance(commit_node.value.func,ast.Attribute)
              and isinstance(commit_node.value.func.value,ast.Name)
              and commit_node.value.func.value.id==receiver,'DELEGATED_COMMIT_BINDING')
    commit=commit_node.value.func.attr
    plain=ast.parse(f'''def f():
    with {factory}(**{receiver}.{options}) as {stream}:
        yield {stream}
        {receiver}.{sync}({stream})
    {receiver}.{commit}({stream})
''').body[0].body
    style='PLAIN';rollback=None
    if shape(inner)!=shape(plain):
        c.require(len(inner)==1 and isinstance(inner[0],ast.Try) and not inner[0].handlers
                  and not inner[0].orelse and inner[0].body and isinstance(inner[0].body[0],ast.Assign)
                  and len(inner[0].body[0].targets)==1 and isinstance(inner[0].body[0].targets[0],ast.Name),
                  'DELEGATED_FINITE_LIFECYCLE')
        success=inner[0].body[0].targets[0].id
        rollback_calls=[n for row in inner[0].finalbody for n in ast.walk(row) if isinstance(n,ast.Call)
                        and isinstance(n.func,ast.Attribute) and isinstance(n.func.value,ast.Name)
                        and n.func.value.id==receiver]
        c.require(len(rollback_calls)==1,'DELEGATED_ROLLBACK_BINDING');rollback=rollback_calls[0].func.attr
        expected=ast.parse(f'''def f():
    try:
        {success} = False
        with {factory}(**{receiver}.{options}) as {stream}:
            yield {stream}
            {receiver}.{sync}({stream})
        {receiver}.{commit}({stream})
        {success} = True
    finally:
        if not {success}:
            try:
                {receiver}.{rollback}({stream})
            except Exception:
                pass
''').body[0].body
        c.require(shape(inner)==shape(expected),'DELEGATED_FINITE_LIFECYCLE');style='SUCCESS_FLAG_ROLLBACK'
    c.require(len({receiver,factory,stream})==3,'DELEGATED_LOCAL_COLLISION')
    return dict(receiver=receiver,factory_parameter=factory,stream=stream,options_field=options,
                sync_method=sync,commit_method=commit,rollback_method=rollback,lifecycle_style=style,protected=protected)


def creator_binding(fn):
    a=fn.args;body=rows(fn)
    c.require(not a.posonlyargs and len(a.args)==4 and len(a.defaults)==3 and not a.kwonlyargs
              and a.vararg is None and a.kwarg is not None and len(body)==6,'DELEGATED_TEMPORARY_CREATOR')
    receiver,suffix,prefix,directory=[p.arg for p in a.args];kwargs=a.kwarg.arg
    c.require(isinstance(a.defaults[0],ast.Constant) and a.defaults[0].value==''
              and (isinstance(a.defaults[1],ast.Constant) and type(a.defaults[1].value) is str
                   or ast.unparse(a.defaults[1])=='tempfile.gettempprefix()')
              and isinstance(a.defaults[2],ast.Constant) and a.defaults[2].value is None,
              'DELEGATED_TEMPORARY_DEFAULTS')
    c.require(isinstance(body[0],ast.If) and len(body[0].body)==1
              and isinstance(body[0].body[0],ast.Assign),'DELEGATED_TEMPORARY_DIRECTORY')
    paths=[n.attr for n in ast.walk(body[0]) if isinstance(n,ast.Attribute)
           and isinstance(n.value,ast.Name) and n.value.id==receiver]
    c.require(len(paths)==1,'DELEGATED_TEMPORARY_DIRECTORY');path_field=paths[0]
    assignment=body[1]
    c.require(isinstance(assignment,ast.Assign) and len(assignment.targets)==1
              and isinstance(assignment.targets[0],ast.Tuple) and len(assignment.targets[0].elts)==2
              and all(isinstance(n,ast.Name) for n in assignment.targets[0].elts),'DELEGATED_TEMPORARY_CREATOR')
    descriptor,temporary=[n.id for n in assignment.targets[0].elts]
    c.require(isinstance(body[3],ast.Assign) and isinstance(body[3].value,ast.Attribute)
              and isinstance(body[3].value.value,ast.Name) and body[3].value.value.id==receiver,
              'DELEGATED_TEMPORARY_MODE')
    mode_field=body[3].value.attr
    expected=ast.parse(f'''def f():
    if {directory} is None:
        {directory} = os.path.normpath(os.path.dirname({receiver}.{path_field}))
    {descriptor}, {temporary} = tempfile.mkstemp(suffix={suffix}, prefix={prefix}, dir={directory})
    os.close({descriptor})
    {kwargs}['mode'] = {receiver}.{mode_field}
    {kwargs}['file'] = {temporary}
    return io.open(**{kwargs})
''').body[0].body
    c.require(shape(body)==shape(expected),'DELEGATED_TEMPORARY_CREATOR')
    return dict(temporary=temporary,path_field=path_field,mode_field=mode_field)


def constructor_binding(fn,tree):
    "Constructor binding."
    a=fn.args
    c.require(not a.posonlyargs and len(a.args)==4 and not a.kwonlyargs and a.vararg is None
              and a.kwarg is not None,'DELEGATED_CONSTRUCTOR_SIGNATURE')
    receiver,path,mode,overwrite=[p.arg for p in a.args]
    c.require((mode,overwrite)==('mode','overwrite'),'DELEGATED_CONSTRUCTOR_OPTIONS')
    assignments={}
    for row in rows(fn):
        if isinstance(row,ast.If):
            conversion=ast.parse(f'''def f():
    if fspath is not None:
        {path} = fspath({path})
''').body[0].body[0]
            if ast.dump(row)==ast.dump(conversion):
                imports=[n for n in ast.walk(tree) if isinstance(n,ast.ImportFrom) and not n.level
                         and n.module=='os' and any(t.name=='fspath' and (t.asname or t.name)=='fspath' for t in n.names)]
                c.require(len(imports)==1,'DELEGATED_PATH_CONVERSION_SCOPE')
                rebindings=[n for n in ast.walk(tree) if isinstance(n,ast.Assign)
                            and any(isinstance(t,ast.Name) and t.id=='fspath' for t in n.targets)]
                c.require(all(isinstance(n.value,ast.Constant) and n.value.value is None for n in rebindings),
                          'DELEGATED_PATH_CONVERSION_SCOPE')
                continue
            c.require(not row.orelse and len(row.body)==1 and isinstance(row.body[0],ast.Raise)
                      and row.body[0].cause is None and isinstance(row.body[0].exc,ast.Call)
                      and isinstance(row.body[0].exc.func,ast.Name) and row.body[0].exc.func.id=='ValueError'
                      and len(row.body[0].exc.args)==1 and not row.body[0].exc.keywords
                      and isinstance(row.body[0].exc.args[0],ast.Constant)
                      and type(row.body[0].exc.args[0].value) is str
                      and isinstance(row.test,ast.Compare) and len(row.test.ops)==1
                      and isinstance(row.test.ops[0],(ast.In,ast.NotIn))
                      and isinstance(row.test.left,ast.Constant) and type(row.test.left.value) is str
                      and len(row.test.comparators)==1 and isinstance(row.test.comparators[0],ast.Name)
                      and row.test.comparators[0].id==mode,'DELEGATED_CONSTRUCTOR_EFFECT')
            continue
        c.require(isinstance(row,ast.Assign) and len(row.targets)==1
                  and isinstance(row.targets[0],ast.Attribute) and isinstance(row.targets[0].value,ast.Name)
                  and row.targets[0].value.id==receiver and isinstance(row.value,ast.Name)
                  and row.value.id in (path,mode,overwrite,a.kwarg.arg),'DELEGATED_CONSTRUCTOR_EFFECT')
        field=row.targets[0].attr
        c.require(field not in assignments,'DELEGATED_CONSTRUCTOR_FIELD_REBINDING')
        assignments[field]=row.value.id
    c.require(len(assignments)==4,'DELEGATED_CONSTRUCTOR_FIELD_FLOW')
    return assignments


def bind(entry,tree,canonical):
    "Bind."
    factory=canonical(entry)
    body=rows(factory)
    c.require(len(body)==1 and isinstance(body[0],ast.Return),'DELEGATED_PUBLIC_FACTORY')
    outer=body[0].value
    c.require(isinstance(outer,ast.Call) and isinstance(outer.func,ast.Attribute) and outer.func.attr=='open'
              and not outer.args and not outer.keywords and isinstance(outer.func.value,ast.Call),
              'DELEGATED_PUBLIC_FACTORY')
    constructor=outer.func.value;a=factory.args
    c.require(not a.posonlyargs and len(a.args) in (1,2) and not a.kwonlyargs and a.vararg is None
              and len(a.defaults)==len(a.args)-1,'DELEGATED_PUBLIC_SIGNATURE')
    c.require(a.args and len(constructor.args)==1 and isinstance(constructor.args[0],ast.Name)
              and constructor.args[0].id==a.args[0].arg and a.kwarg is not None
              and len(constructor.keywords)==1 and constructor.keywords[0].arg is None
              and isinstance(constructor.keywords[0].value,ast.Name)
              and constructor.keywords[0].value.id==a.kwarg.arg,'DELEGATED_PUBLIC_PATH')
    defaults=dict(zip([p.arg for p in a.args][-len(a.defaults):],a.defaults)) if a.defaults else {}
    name=constructor.func.id if isinstance(constructor.func,ast.Name) else None
    if name in defaults:name=defaults[name].id if isinstance(defaults[name],ast.Name) else None
    classes=[r for r in tree.body if isinstance(r,ast.ClassDef) and r.name==name]
    c.require(len(classes)==1,'DELEGATED_CLASS_BINDING');cls=classes[0]
    statements=ast.Module(body=[n for n in tree.body if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef))],type_ignores=[])
    c.require(not any(isinstance(n,ast.Name) and n.id==cls.name and isinstance(n.ctx,(ast.Store,ast.Del))
                      for n in ast.walk(statements)),'DELEGATED_CLASS_REASSIGNED')
    references=[r for r in tree.body if isinstance(r,ast.FunctionDef)
                and any(isinstance(n,ast.Name) and n.id==cls.name for n in ast.walk(r))]
    c.require(references==[entry],'DELEGATED_AMBIGUOUS_PUBLIC_ENTRY')
    c.require(not cls.decorator_list and not cls.keywords and len(cls.bases)<=1
              and all(isinstance(base,ast.Name) and base.id=='object' for base in cls.bases),'DELEGATED_CLASS_PROTOCOL')
    c.require(all(isinstance(m,ast.FunctionDef) or isinstance(m,ast.Expr)
                  and isinstance(m.value,ast.Constant) and isinstance(m.value.value,str) for m in cls.body),
                  'DELEGATED_CLASS_NAMESPACE')
    methods={m.name:m for m in cls.body if isinstance(m,ast.FunctionDef)}
    c.require(len(methods)==sum(isinstance(m,ast.FunctionDef) for m in cls.body)
              and {'__init__','open'}<=set(methods),'DELEGATED_METHOD_BINDING')
    c.require(not any(name.startswith('__') and name.endswith('__') and name!='__init__' for name in methods),
              'DELEGATED_CLASS_PROTOCOL')
    opened=canonical(methods['open']);b=rows(opened)
    c.require(len(b)==1 and isinstance(b[0],ast.Return) and isinstance(b[0].value,ast.Call), 'DELEGATED_OPEN_BINDING')
    call=b[0].value
    c.require(len(opened.args.args)==1 and not opened.args.defaults and not opened.args.kwonlyargs
              and opened.args.vararg is None and opened.args.kwarg is None and not call.keywords
              and isinstance(call.func,ast.Attribute) and isinstance(call.func.value,ast.Name)
              and call.func.value.id==opened.args.args[0].arg and len(call.args)==1
              and isinstance(call.args[0],ast.Attribute) and isinstance(call.args[0].value,ast.Name)
              and call.args[0].value.id==opened.args.args[0].arg,'DELEGATED_OPEN_BINDING')
    helper=methods.get(call.func.attr);creator=methods.get(call.args[0].attr)
    c.require(helper is not None and creator is not None and len(helper.decorator_list)==1
              and ast.unparse(canonical_decorator(helper.decorator_list[0],tree))=='contextlib.contextmanager',
              'DELEGATED_GENERATOR_DECORATOR')
    fn=canonical(helper);bound=lifecycle(fn)
    c.require(bound['sync_method'] in methods and bound['commit_method'] in methods
              and (bound['rollback_method'] is None or bound['rollback_method'] in methods),'DELEGATED_METHOD_BINDING')
    
    creation=canonical(creator);created=creator_binding(creation)
    imports=[n for n in ast.walk(tree) if isinstance(n,(ast.Import,ast.ImportFrom))]
    c.require(all((not n.level and (n.module or '').split('.')[0] in sys.stdlib_module_names)
                  if isinstance(n,ast.ImportFrom) else all(a.name.split('.')[0] in sys.stdlib_module_names for a in n.names)
                  for n in imports),'DELEGATED_EXTERNAL_DEPENDENCY')
    init=methods['__init__'];defaults=dict(zip([p.arg for p in init.args.args][-len(init.args.defaults):],init.args.defaults))
    c.require('mode' in defaults and 'overwrite' in defaults and constant(defaults['mode'],tree) in ('w','wb')
              and type(constant(defaults['overwrite'],tree)) is bool,'DELEGATED_CONSTRUCTOR_OPTIONS')
    c.require(all(not m.decorator_list or m is helper for m in methods.values()),'DELEGATED_UNKNOWN_DECORATOR')
    assignments=constructor_binding(init,tree)
    for field,parameter in ((created['path_field'],init.args.args[1].arg),(created['mode_field'],'mode'),
                            (bound['options_field'],init.args.kwarg.arg)):
        c.require(assignments.get(field)==parameter,'DELEGATED_CONSTRUCTOR_FIELD_FLOW')
    bound.update(kind=KIND,entry_symbol=entry.name,class_name=cls.name,repair_symbol=cls.name+'.'+helper.name,
                 path_parameter=factory.args.args[0].arg,mode_parameter='mode',default_mode=constant(defaults['mode'],tree),
                 creator_method=creator.name,temporary=created['temporary'],creator_sha256=c.digest(ast.dump(creation)),
                 invocation_policy='PUBLIC_FACTORY_OVERWRITE_TRUE_BINARY_OR_DECLARED_TEXT_DEFAULT',
                 dependency_scope='FROZEN_MEMBER_AND_STDLIB',ownership_semantics_certified=False)
    return helper,fn,bound


def looking(entry,tree):
    "Looking."
    body=rows(entry)
    if len(body)!=1 or not isinstance(body[0],ast.Return):return False
    call=body[0].value
    if not (isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute) and call.func.attr=='open'
            and isinstance(call.func.value,ast.Call) and isinstance(call.func.value.func,ast.Name)):return False
    defaults=dict(zip([p.arg for p in entry.args.args][-len(entry.args.defaults):],entry.args.defaults)) if entry.args.defaults else {}
    name=call.func.value.func.id
    if name in defaults:name=defaults[name].id if isinstance(defaults[name],ast.Name) else None
    for cls in tree.body:
        if not isinstance(cls,ast.ClassDef) or cls.name!=name:continue
        opened=next((n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='open'),None)
        b=rows(opened) if opened else []
        if len(b)==1 and isinstance(b[0],ast.Return) and isinstance(b[0].value,ast.Call):return True
    return False


def canonical_decorator(node,tree):
    imports={a.asname or a.name:a.name for n in tree.body if isinstance(n,ast.Import) for a in n.names}
    imports.update({a.asname or a.name:n.module+'.'+a.name for n in tree.body if isinstance(n,ast.ImportFrom)
                    and not n.level for a in n.names})
    class Normalize(ast.NodeTransformer):
        def visit_Name(self,n):
            return ast.parse(imports[n.id],mode='eval').body if n.id in imports else n
    return Normalize().visit(deepcopy(node))


def repair(code):
    fn=ast.parse(code).body[0];bound=lifecycle(fn)
    if bound['protected']:return code
    stream=bound['stream'];body=rows(fn)
    guard=ast.parse(f'''def f():
    try:
        pass
    finally:
        if {stream} is not None and os.path.exists({stream}.name):
            os.unlink({stream}.name)
''').body[0].body[0]
    guard.body=deepcopy(body[1:]);fn.body=[deepcopy(body[0]),guard]
    ast.fix_missing_locations(fn);lifecycle(fn)
    return ast.unparse(fn)+'\n'
