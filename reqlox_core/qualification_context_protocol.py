"Finite reliability controls and verification."
from qualification_adapters_v2 import _class,_methods,sha,need


def keyword_call(signature,kwargs):
    named={a['name']:a for a in [*signature['positional'],*signature['keyword_only']]}
    need(type(kwargs) is dict and len(kwargs)<=8,'CONTEXT_KEYWORD_BOUND')
    need(all(k in named and not named[k].get('positional_only',False) for k in kwargs),'CONTEXT_UNKNOWN_KEYWORD')
    need(all(not a['required'] or a['name'] in kwargs for a in named.values()),'CONTEXT_MISSING_ARGUMENT')
    need(all(type(v) in (str,int,bool,type(None)) and (type(v) is not str or len(v)<=128) for v in kwargs.values()),'CONTEXT_LITERAL_ARGUMENT')


def validate(index,binding):
    need(index['inventory_sha256']==sha({k:v for k,v in index.items() if k not in ('inventory_sha256','record_sha256')}),'CONTEXT_INVENTORY_DRIFT')
    expected={'factory_module','factory_name','owner_module','owner_class','context_method','context_module','context_class','factory_kwargs','context_kwargs','key_parameter','sync_probe','async_probe'}
    need(type(binding) is dict and set(binding)==expected,'CONTEXT_BINDING_SCHEMA')
    funcs=[r for r in index['functions'] if r['module']==binding['factory_module'] and r['name']==binding['factory_name']]
    need(len(funcs)==1,'CONTEXT_FACTORY_NOT_STATIC');keyword_call(funcs[0]['signature'],binding['factory_kwargs'])
    owner=_class(index,binding['owner_module'],binding['owner_class']);methods=_methods(index,owner)
    need(binding['context_method'] in methods,'CONTEXT_METHOD_NOT_STATIC')
    need(binding['key_parameter'] not in binding['context_kwargs'],'CONTEXT_KEY_ALREADY_FILLED')
    keyword_call(methods[binding['context_method']]['signature'],{**binding['context_kwargs'],binding['key_parameter']:'owned-test-key'})
    context=_class(index,binding['context_module'],binding['context_class']);methods=_methods(index,context)
    for name,arity,asynchronous in [('__enter__',0,False),('__exit__',3,False),('__aenter__',0,True),('__aexit__',3,True),(binding['sync_probe'],0,False),(binding['async_probe'],0,True)]:
        need(name in methods,'CONTEXT_PROTOCOL_METHOD_NOT_STATIC');sig=methods[name]['signature']
        need(sum(a['required'] for a in sig['positional'])<=arity<=len(sig['positional']) and sig['asynchronous']==asynchronous,'CONTEXT_PROTOCOL_SIGNATURE')
    return dict(binding_sha256=sha(binding),static_protocol_checked=True,arbitrary_code=False,target_name_branching=False,semantic_correctness_certified=False)


CASES=[dict(id='sync-timeout',mode='SYNC',exception='TimeoutError'),dict(id='sync-runtime',mode='SYNC',exception='RuntimeError'),
    dict(id='sync-value',mode='SYNC',exception='ValueError'),dict(id='async-timeout',mode='ASYNC',exception='TimeoutError'),
    dict(id='async-cancel',mode='ASYNC',exception='CancelledError'),dict(id='async-runtime',mode='ASYNC',exception='RuntimeError')]
STAGES=[dict(id='HEALTHY',policy='BALANCED_CONTEXT',inject_exception=False),dict(id='FAULT',policy='OMIT_EXIT',inject_exception=True),
    dict(id='REPAIR',policy='BALANCED_CONTEXT',inject_exception=False),dict(id='REINJECTION',policy='BALANCED_CONTEXT',inject_exception=True)]
