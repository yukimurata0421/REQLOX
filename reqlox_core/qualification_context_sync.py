"Finite reliability controls and verification."
import ast
import hashlib
from pathlib import Path
from qualification_adapters_v2 import inventory as previous_inventory,_signature,_class,_methods,sha,need
from qualification_context_protocol import keyword_call


def inventory(root):
    root=Path(root).resolve();result=previous_inventory(root)
    for path in sorted(root.rglob('*.py')):
        parts=list(path.relative_to(root).with_suffix('').parts)
        if parts[-1]=='__init__':parts.pop()
        module='.'.join(parts)
        if not module:continue
        tree=ast.parse(path.read_bytes())
        def visit(node,parents):
            if not isinstance(node,ast.ClassDef):return
            name='.'.join([*parents,node.name])
            if parents:
                methods=[]
                for m in node.body:
                    if isinstance(m,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        methods.append(dict(name=m.name,line=m.lineno,end_line=m.end_lineno,signature=_signature(m,implicit=1),doc=(ast.get_docstring(m) or '')[:600]))
                result['classes'].append(dict(module=module,name=name,line=node.lineno,end_line=node.end_lineno,bases=[ast.unparse(b) for b in node.bases],
                    methods=methods,package_module=path.name=='__init__.py',doc=(ast.get_docstring(node) or '')[:1000],source_sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
            for child in node.body:visit(child,[*parents,node.name])
        for node in tree.body:visit(node,[])
    need(len(result['classes'])<=256,'CONTEXT_NESTED_CLASS_BOUND')
    result['schema_version']='reqlox.static-nested-context-api.v0.1';result.pop('inventory_sha256');result['inventory_sha256']=sha(result)
    return result


def validate(index,binding):
    need(index['inventory_sha256']==sha({k:v for k,v in index.items() if k not in ('inventory_sha256','record_sha256')}),'SYNC_CONTEXT_INVENTORY_DRIFT')
    fields={'factory_module','factory_class','factory_kwargs','context_method','context_module','context_class','context_kwargs','probe_method','next_acquire_method','next_acquire_kwargs','next_release_method'}
    need(type(binding) is dict and set(binding)==fields,'SYNC_CONTEXT_BINDING_SCHEMA')
    cls=_class(index,binding['factory_module'],binding['factory_class']);owner=_methods(index,cls)
    if '__init__' in owner:keyword_call(owner['__init__']['signature'],binding['factory_kwargs'])
    else:need(not binding['factory_kwargs'],'SYNC_CONTEXT_CONSTRUCTOR_UNRESOLVED')
    need(binding['context_method'] in owner,'SYNC_CONTEXT_FACTORY_METHOD');keyword_call(owner[binding['context_method']]['signature'],binding['context_kwargs'])
    context=_class(index,binding['context_module'],binding['context_class']);methods=_methods(index,context)
    for name,arity in [('__enter__',0),('__exit__',3),(binding['probe_method'],0),(binding['next_release_method'],0)]:
        need(name in methods,'SYNC_CONTEXT_PROTOCOL_METHOD');sig=methods[name]['signature']
        need(not sig['asynchronous'] and sum(a['required'] for a in sig['positional'])<=arity<=len(sig['positional']),'SYNC_CONTEXT_PROTOCOL_SIGNATURE')
    need(binding['next_acquire_method'] in methods,'SYNC_CONTEXT_ACQUIRE_METHOD');keyword_call(methods[binding['next_acquire_method']]['signature'],binding['next_acquire_kwargs'])
    need(binding['next_acquire_kwargs'].get('blocking') is False,'SYNC_CONTEXT_UNBOUNDED_SECOND_ACQUIRE')
    return dict(binding_sha256=sha(binding),static_protocol_checked=True,nested_source_class_supported=True,second_acquisition_nonblocking=True,target_name_branching=False,semantic_correctness_certified=False)


def evidence(root,index,binding):
    rows=[]
    for module,name,method in [(binding['factory_module'],binding['factory_class'],'__init__'),(binding['factory_module'],binding['factory_class'],binding['context_method']),
        (binding['context_module'],binding['context_class'],'__enter__'),(binding['context_module'],binding['context_class'],'__exit__'),
        (binding['context_module'],binding['context_class'],binding['next_acquire_method']),(binding['context_module'],binding['context_class'],binding['next_release_method'])]:
        cls=_class(index,module,name);definition=_methods(index,cls)[method]
        
        owners=[r for r in index['classes'] if any(m==definition for m in r['methods'])]
        need(len(owners)==1,'SYNC_CONTEXT_EVIDENCE_OWNER')
        path=Path(root)/(owners[0]['module'].replace('.','/')+'.py');lines=path.read_text().splitlines(keepends=True)
        statement=''.join(lines[definition['line']-1:definition['end_line']])
        need(0<len(statement)<=8192,'SYNC_CONTEXT_EVIDENCE_BOUND')
        rows.append(dict(class_name=owners[0]['name'],method=method,start_line=definition['line'],end_line=definition['end_line'],
            source_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),exact_source=statement))
    return rows
