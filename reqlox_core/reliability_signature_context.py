"Discover finite callers from authored documentation and public signatures."
import ast
import hashlib
from pathlib import PurePosixPath
import re


def _literal(value):
    try:value=ast.literal_eval(value)
    except (ValueError,TypeError):return False
    return type(value) in (str,int,float,bool,type(None)) and (type(value) is not str or len(value)<=100) \
        and (type(value) is not float or abs(value)<=60)


def _span(text,node):
    lines=text.splitlines(keepends=True)
    def position(line,column):
        return sum(len(v) for v in lines[:line-1])+len(lines[line-1].encode()[:column].decode())
    start=position(node.lineno,node.col_offset);end=position(node.end_lineno,node.end_col_offset)
    return dict(start=start,end=end,sha256=hashlib.sha256(text[start:end].encode()).hexdigest())


def _binding_count(tree,name):
    "Binding count."
    return sum(isinstance(v,ast.Name) and v.id==name and isinstance(v.ctx,(ast.Store,ast.Del))
        or isinstance(v,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and v.name==name
        or isinstance(v,ast.alias) and (v.asname or v.name.split('.')[0])==name
        for v in ast.walk(tree))


def _path_type(argument,tree,documentation):
    paths=set();modules=set()
    for node in tree.body:
        if isinstance(node,ast.ImportFrom) and node.module=='pathlib' and not node.level:
            paths.update(v.asname or v.name for v in node.names if v.name=='Path'
                and _binding_count(tree,v.asname or v.name)==1)
        elif isinstance(node,ast.Import):modules.update(v.asname or v.name for v in node.names if v.name=='pathlib'
                and _binding_count(tree,v.asname or v.name)==1)
    builtin_string=_binding_count(tree,'str')==0
    annotation=argument.annotation
    if annotation is None:
        return 'PATHLIB_PATH' if re.search(r'(?m)^\s*'+re.escape(argument.arg)+r'\s*\(Path\)\s*:',documentation) and 'Path' in paths else 'STR'
    if isinstance(annotation,ast.Constant) and type(annotation.value) is str:
        try:annotation=ast.parse(annotation.value,mode='eval').body
        except SyntaxError:return None
    if isinstance(annotation,ast.Name):
        return 'STR' if annotation.id=='str' and builtin_string else ('PATHLIB_PATH' if annotation.id in paths else None)
    if isinstance(annotation,ast.Attribute) and isinstance(annotation.value,ast.Name) \
            and annotation.value.id in modules and annotation.attr=='Path':return 'PATHLIB_PATH'
    if isinstance(annotation,ast.BinOp) and isinstance(annotation.op,ast.BitOr):
        branches=[annotation.left,annotation.right]
        if builtin_string and any(isinstance(v,ast.Name) and v.id=='str' for v in branches):return 'STR'
    return None


def discover(sources,*,profile,path_keywords,directory_keywords,allowed_modules):
    rows=[]
    for member,text in sorted(sources.items()):
        parts=list(PurePosixPath(member).parts)
        if parts[0]=='src':parts=parts[1:]
        parts[-1]=parts[-1][:-3]
        if parts[-1]=='__init__':parts=parts[:-1]
        if not parts or any(not p.isidentifier() or p.startswith('_') or p.startswith(('test','example','bench')) for p in parts):continue
        module='.'.join(parts)
        if module not in allowed_modules:continue
        try:tree=ast.parse(text)
        except SyntaxError:continue
        context_aliases=set();context_modules=set()
        for node in tree.body:
            if isinstance(node,ast.ImportFrom) and node.module=='contextlib' and not node.level:
                context_aliases.update(a.asname or a.name for a in node.names if a.name=='contextmanager'
                    and _binding_count(tree,a.asname or a.name)==1)
            elif isinstance(node,ast.Import):
                context_modules.update(a.asname or a.name for a in node.names if a.name=='contextlib'
                    and _binding_count(tree,a.asname or a.name)==1)
        for node in tree.body:
            if not isinstance(node,(ast.ClassDef,ast.FunctionDef)) or node.name.startswith('_'):continue
            if sum(isinstance(v,(ast.ClassDef,ast.FunctionDef,ast.AsyncFunctionDef)) and v.name==node.name
                or isinstance(v,ast.Name) and v.id==node.name and isinstance(v.ctx,(ast.Store,ast.Del))
                or isinstance(v,ast.alias) and (v.asname or v.name.split('.')[0])==node.name
                for v in ast.walk(tree))!=1:continue
            if isinstance(node,ast.ClassDef):
                if node.decorator_list or node.bases or node.keywords:continue
                functions={v.name:v for v in node.body if isinstance(v,ast.FunctionDef)}
                if not {'__enter__','__exit__'}<=set(functions):continue
                signature=functions.get('__init__')
                if signature is None or signature.decorator_list:continue
                arguments=signature.args;positional=[*arguments.posonlyargs,*arguments.args]
                if not positional or positional[0].arg!='self':continue
                positional=positional[1:]
                docs=[v for v in (node,signature) if ast.get_docstring(v)]
            else:
                if len(node.decorator_list)!=1:continue
                decorator=node.decorator_list[0]
                if not (isinstance(decorator,ast.Name) and decorator.id in context_aliases
                    or isinstance(decorator,ast.Attribute) and decorator.attr=='contextmanager'
                    and isinstance(decorator.value,ast.Name) and decorator.value.id in context_modules):continue
                signature=node;arguments=node.args;positional=[*arguments.posonlyargs,*arguments.args]
                docs=[node] if ast.get_docstring(node) else []
            if not docs or arguments.vararg or arguments.kwarg:continue
            if any(not _literal(v) for v in arguments.defaults) or any(v is not None and not _literal(v)
                    for v in arguments.kw_defaults):continue
            required=[v.arg for v in positional[:len(positional)-len(arguments.defaults)]]
            required.extend(v.arg for v,default in zip(arguments.kwonlyargs,arguments.kw_defaults) if default is None)
            combined='\n'.join(ast.get_docstring(v,clean=False) for v in docs)
            candidates=[v.arg for v in [*positional,*arguments.kwonlyargs] if v.arg in path_keywords|directory_keywords
                and re.search(r'(?m)^\s*(?::param\s+)?'+re.escape(v.arg)+r'\s*(?:\([^\n]*\))?\s*:\s*[^\n]*\b(?:path|file|directory|folder)\b',combined,re.I)]
            binding=dict(profile=profile,module=module,symbol=node.name,args=[],kwargs={})
            if len(candidates)==1 and set(required)<=set(candidates):
                name=candidates[0]
                argument=next(v for v in [*positional,*arguments.kwonlyargs] if v.arg==name)
                value_type=_path_type(argument,tree,combined)
                if value_type is None:continue
                if positional and positional[0].arg==name:
                    # original default values are left to the callable; only the documented path is supplied.
                    if value_type!='STR':binding['path_argument']=dict(placement='POSITIONAL',keyword=None,value_type=value_type)
                elif name in path_keywords and name not in {v.arg for v in arguments.posonlyargs}:
                    binding['path_argument']=dict(placement='KEYWORD',keyword=name,value_type=value_type)
                else:continue
            elif not candidates and not required and re.search(r'\btemporary\s+(?:file|files|directory|directories|folder)\b',combined,re.I):
                binding['path_argument']=dict(placement='TEMPFILE_DEFAULT',keyword=None,value_type='STR')
            else:continue
            document=docs[0];literal=document.body[0].value
            rows.append(dict(binding=binding,document='source-docstring:'+member+':'+node.name,
                document_sha256=hashlib.sha256(text.encode()).hexdigest(),span=_span(text,literal),
                span_basis='ORIGINAL_AUTHOR_DOCSTRING_LITERAL_IN_SOURCE_MEMBER',source_member=member,
                documentation_spans=[_span(text,v.body[0].value) for v in docs],
                source_member_sha256=hashlib.sha256(text.encode()).hexdigest(),
                signature_sha256=hashlib.sha256(ast.dump(arguments,include_attributes=False).encode()).hexdigest(),
                recipe_origin='AUTHOR_DOCUMENTATION_AND_PUBLIC_SIGNATURE',
                original_path_literal_retained_in_private_document=False,
                implementation_behavior_used_as_specification=False,
                generated_python_example_presented_as_author_documentation=False,
                interpretation='FINITE_CLIENT_REQUIREMENT_COMPATIBILITY_ONLY'))
            if len(rows)>=12:return rows
    return rows
