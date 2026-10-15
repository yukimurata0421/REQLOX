"Finite reliability controls and verification."
import ast
import hashlib
import json
from pathlib import Path
import re


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",", ":"),
                                     ensure_ascii=False,allow_nan=False).encode()).hexdigest()


def _default(node):
    try:
        value=ast.literal_eval(node)
    except (ValueError,TypeError):
        return dict(kind="EXPRESSION_NOT_EXECUTED",ast_type=type(node).__name__)
    if type(value) in (str,int,float,bool,type(None)):
        return dict(kind="LITERAL",value=value)
    return dict(kind="LITERAL_CONTAINER_NOT_EVALUATED",ast_type=type(node).__name__)


def _signature(node, *, implicit=0):
    arguments=[*node.args.posonlyargs,*node.args.args]
    defaults=[None]*(len(arguments)-len(node.args.defaults))+list(node.args.defaults)
    positional=[dict(name=a.arg,required=d is None,positional_only=i<len(node.args.posonlyargs),
                     default=None if d is None else _default(d))
                for i,(a,d) in enumerate(zip(arguments,defaults)) if i>=implicit]
    keywords=[dict(name=a.arg,required=d is None,default=None if d is None else _default(d))
              for a,d in zip(node.args.kwonlyargs,node.args.kw_defaults)]
    return dict(positional=positional,keyword_only=keywords,
                varargs=node.args.vararg.arg if node.args.vararg else None,
                varkw=node.args.kwarg.arg if node.args.kwarg else None,
                asynchronous=isinstance(node,ast.AsyncFunctionDef))


def inventory(root):
    root=Path(root).resolve(); paths=sorted(root.rglob("*.py"))
    need(0<len(paths)<=256,"API_SOURCE_FILE_BOUND")
    classes,functions,imports,refs=[],[],[],[]
    for path in paths:
        need(path.is_file() and not path.is_symlink() and path.stat().st_size<=1048576,"API_SOURCE_SCOPE")
        raw=path.read_bytes();tree=ast.parse(raw,filename=str(path));relative=path.relative_to(root)
        parts=list(relative.with_suffix("").parts)
        if parts[-1]=="__init__":parts.pop()
        module=".".join(parts)
        if not module:continue
        refs.append(dict(path=str(relative),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw)))
        for node in tree.body:
            if isinstance(node,ast.ClassDef):
                methods=[]
                for method in node.body:
                    if isinstance(method,(ast.FunctionDef,ast.AsyncFunctionDef)):
                        methods.append(dict(name=method.name,line=method.lineno,end_line=method.end_lineno,
                                            signature=_signature(method,implicit=0 if any(isinstance(d,ast.Name) and d.id=="staticmethod" for d in method.decorator_list) else 1),
                                            doc=(ast.get_docstring(method) or "")[:600]))
                classes.append(dict(module=module,name=node.name,line=node.lineno,end_line=node.end_lineno,
                                    bases=[ast.unparse(b) for b in node.bases],methods=methods,package_module=relative.name=="__init__.py",
                                    doc=(ast.get_docstring(node) or "")[:1000],
                                    source_sha256=hashlib.sha256(raw).hexdigest()))
            elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef)):
                functions.append(dict(module=module,name=node.name,signature=_signature(node),line=node.lineno))
            elif isinstance(node,(ast.Import,ast.ImportFrom)):
                imports.append(dict(module=module,from_module=node.module if isinstance(node,ast.ImportFrom) else None,
                                    relative_level=node.level if isinstance(node,ast.ImportFrom) else 0,
                                    names=[dict(name=a.name,alias=a.asname) for a in node.names]))
    need(len(classes)<=256 and len(functions)<=512,"API_DECLARATION_BOUND")
    result=dict(schema_version="reqlox.static-api-inventory.v0.2",classes=classes,functions=functions,
                imports=imports,file_refs=refs,target_imports=0,target_executions=0,
                inventory_is_semantic_gold=False,source_expressions_executed=False)
    result["inventory_sha256"]=sha(result)
    return result


def _class(index,module,name):
    found=[c for c in index["classes"] if c["module"]==module and c["name"]==name]
    need(len(found)==1,"API_CLASS_UNKNOWN_OR_AMBIGUOUS")
    return found[0]


def _resolve_base(index,cls,base):
    found=[c for c in index["classes"] if c["module"]==cls["module"] and c["name"]==base]
    if found:return found
    for row in index["imports"]:
        if row["module"]!=cls["module"]:continue
        for alias in row["names"]:
            visible=alias["alias"] or alias["name"]
            if row["from_module"] is not None and base==visible:
                target=row["from_module"]
                if row["relative_level"]:
                    parts=cls["module"].split(".")
                    remove=row["relative_level"]-1 if cls.get("package_module") else row["relative_level"]
                    prefix=parts if remove==0 else parts[:-remove]
                    target=".".join(prefix+([target] if target else []))
                found.extend(c for c in index["classes"] if c["module"]==target and c["name"]==alias["name"])
            elif row["from_module"] is None and base.startswith(visible+"."):
                name=base[len(visible)+1:]
                found.extend(c for c in index["classes"] if c["module"]==alias["name"] and c["name"]==name)
    need(len(found)<=1,"API_BASE_AMBIGUOUS")
    return found


def _mro(index,cls,seen=None):
    seen=set() if seen is None else seen;key=(cls["module"],cls["name"])
    need(key not in seen and len(seen)<32,"API_INHERITANCE_BOUND")
    parents=[]
    for base in cls["bases"]:
        resolved=_resolve_base(index,cls,base)
        if resolved:parents.append(resolved[0])
        else:parents.append(dict(module="<external>",name=base,bases=[],methods=[]))
    sequences=[_mro(index,p,seen|{key}) for p in parents]+[list(parents)]
    ordered=[cls]
    def identity(c):return (c["module"],c["name"])
    while any(sequences):
        sequences=[s for s in sequences if s]
        candidate=next((s[0] for s in sequences if all(identity(s[0]) not in [identity(x) for x in other[1:]] for other in sequences)),None)
        need(candidate is not None,"API_INCONSISTENT_MRO")
        ordered.append(candidate)
        for sequence in sequences:
            if identity(sequence[0])==identity(candidate):sequence.pop(0)
    return ordered


def _methods(index,cls,seen=None):
    methods={}
    for member in reversed(_mro(index,cls)):
        if member["module"]=="<external>" and member["name"] in ("dict","collections.UserDict","UserDict","MutableMapping","collections.abc.MutableMapping"):
            for name,args in [("__getitem__",["key"]),("__setitem__",["key","value"]),("__delitem__",["key"]),("items",[])]:
                methods[name]=dict(name=name,signature=dict(positional=[dict(name=a,required=True,positional_only=False,default=None) for a in args],keyword_only=[],varargs=None,varkw=None,asynchronous=False),builtin_protocol=True)
        methods.update({m["name"]:m for m in member["methods"]})
    return methods


def validate_plan(index,plan):
    need(index.get("inventory_sha256")==sha({k:v for k,v in index.items() if k not in ("inventory_sha256","record_sha256")}),"API_INVENTORY_DRIFT")
    need(type(plan) is dict and set(plan)=={"family","module","class","constructor","bindings","normalizer","key_codec","iteration_order"},"API_PLAN_SCHEMA")
    need(plan["family"] in ("MAPPING","QUEUED_ASYNC"),"API_FAMILY_UNSUPPORTED")
    need(plan["normalizer"] in ("IDENTITY","CASEFOLD"),"API_NORMALIZER_UNSUPPORTED")
    need(plan["key_codec"] in ("IDENTITY","TYPED_JSON_STRING") and plan["iteration_order"] in ("NATIVE","OWNED_INSERTION"),"API_STATE_TRANSLATION_UNSUPPORTED")
    cls=_class(index,plan["module"],plan["class"]);methods=_methods(index,cls)
    ctor=plan["constructor"]
    need(type(ctor) is dict and set(ctor)=={"positional","keywords"} and type(ctor["positional"]) is list
         and type(ctor["keywords"]) is dict and len(ctor["positional"])+len(ctor["keywords"])<=12,"API_CONSTRUCTOR_SCHEMA")
    for value in [*ctor["positional"],*ctor["keywords"].values()]:
        need(type(value) in (str,int,float,bool,type(None)) and (type(value) is not str or len(value)<=128),"API_ARGUMENT_LITERAL")
        if type(value) is str and ("/" in value or "\\" in value):
            need(value.startswith("/tmp/owned-") and ".." not in Path(value).parts,"API_PATH_OUTSIDE_OWNED_TMP")
    if "__init__" in methods:
        sig=methods["__init__"]["signature"];named={a["name"]:a for a in [*sig["positional"],*sig["keyword_only"]]}
        need(all(k in named or sig["varkw"] is not None for k in ctor["keywords"]),"API_CONSTRUCTOR_UNKNOWN_KEYWORD")
        need(all(not named.get(k,{}).get("positional_only",False) or sig["varkw"] is not None
                 for k in ctor["keywords"]),"API_CONSTRUCTOR_POSITIONAL_ONLY_KEYWORD")
        need(sig["varargs"] is not None or len(ctor["positional"])<=len(sig["positional"]),"API_CONSTRUCTOR_ARITY")
        filled={a["name"] for a in sig["positional"][:len(ctor["positional"])]}
        need(not {k for k in filled & set(ctor["keywords"]) if not named[k].get("positional_only",False)},"API_CONSTRUCTOR_DUPLICATE_ARGUMENT")
        need(all(not a["required"] or a["name"] in filled or
                 (not a.get("positional_only",False) and a["name"] in ctor["keywords"])
                 for a in named.values()),"API_CONSTRUCTOR_MISSING_ARGUMENT")
    elif ctor["positional"] or ctor["keywords"]:
        raise ValueError("API_CONSTRUCTOR_NOT_STATICALLY_RESOLVED")
    required={"PUT","GET","DELETE","ITEMS"} if plan["family"]=="MAPPING" else {"WAIT","CANCEL"}
    need(type(plan["bindings"]) is dict and set(plan["bindings"])==required,"API_BINDING_COVERAGE")
    for op,call in plan["bindings"].items():
        need(type(call) is dict and set(call)=={"method","arguments"} and call["method"] in methods,"API_METHOD_UNKNOWN")
        need(type(call["arguments"]) is list and all(a in ("KEY","VALUE") for a in call["arguments"]),"API_METHOD_ARGUMENT")
        sig=methods[call["method"]]["signature"];args=call["arguments"]
        need(not any(a["required"] for a in sig["keyword_only"]),"API_METHOD_KEYWORD_REQUIRED")
        need(sig["varargs"] is not None or len(args)<=len(sig["positional"]),"API_METHOD_ARITY")
        need(len(args)>=sum(a["required"] for a in sig["positional"]),"API_METHOD_MISSING_ARGUMENT")
        need(sig["asynchronous"]==(plan["family"]=="QUEUED_ASYNC" and op=="WAIT"),"API_ASYNC_BINDING")
    return dict(plan_sha256=sha(plan),inventory_sha256=index["inventory_sha256"],
                static_bindings_complete=True,semantic_correctness_certified=False,
                native_probe_required=True,arbitrary_code=False,target_name_branching=False)


def construct(module,plan):
    cls=getattr(module,plan["class"])
    return cls(*plan["constructor"]["positional"],**plan["constructor"]["keywords"])


def _encode_key(key,plan):
    if plan["normalizer"]=="CASEFOLD":
        need(type(key) is str,"API_CASEFOLD_INPUT");key=key.casefold()
    need(type(key) in (int,str),"API_KEY_DOMAIN")
    return json.dumps(["int" if type(key) is int else "str",key],ensure_ascii=False,separators=(",", ":")) if plan["key_codec"]=="TYPED_JSON_STRING" else key


def _decode_key(key,plan):
    if plan["key_codec"]=="IDENTITY":return key
    need(type(key) is str,"API_ENCODED_KEY_TYPE")
    pair=json.loads(key)
    need(type(pair) is list and len(pair)==2 and pair[0] in ("int","str")
         and type(pair[1]) is (int if pair[0]=="int" else str),"API_ENCODED_KEY_SCHEMA")
    return pair[1]


def mapping_step(handle,plan,event,*,owned_order=None,native_counter=None):
    "Mapping step."
    op=event["op"];key=_encode_key(event["key"],plan)
    need(plan["iteration_order"]=="NATIVE" or type(owned_order) is list,"API_ORDER_STATE_REQUIRED")
    def call(method,args=()):
        if native_counter is not None:native_counter[0]+=1
        return getattr(handle,method)(*args)
    def state():
        raw=list(call(plan["bindings"]["ITEMS"]["method"]))
        if plan["iteration_order"]=="OWNED_INSERTION":
            keys=[k for k,v in raw]
            need(len(keys)==len(set(keys)) and set(keys)==set(owned_order),"API_ORDER_STATE_DRIFT")
            values=dict(raw);raw=[(k,values[k]) for k in owned_order]
        return [[_decode_key(k,plan),v] for k,v in raw]
    items=dict(call(plan["bindings"]["ITEMS"]["method"]))
    found=key in items
    if op in ("GET","DELETE") and not found:
        return dict(result=dict(found=False,value=None),state=state())
    invocation=plan["bindings"][op];args=[key if a=="KEY" else event["value"] for a in invocation["arguments"]]
    raw=call(invocation["method"],args)
    if plan["iteration_order"]=="OWNED_INSERTION":
        if op=="PUT" and key not in owned_order:owned_order.append(key)
        elif op=="DELETE":owned_order.remove(key)
    result=dict(found=True,value=event["value"] if op=="PUT" else raw if op=="GET" else None)
    return dict(result=result,state=state())
