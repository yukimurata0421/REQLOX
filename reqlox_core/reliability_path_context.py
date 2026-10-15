"Bind documented public contexts to an owned sandbox path."
import ast
import hashlib
import importlib
import importlib.machinery
import json
from pathlib import PurePosixPath, Path
import re
import sys
import sysconfig

import incident_reference as c

EVENT = 'FINITE_PATH_CONTEXT_RESOURCE_RELEASE_V1'
PROFILE = 'DOCUMENTED_SYNC_PATH_CONTEXT_V1'
FAULTS = ('NONE', 'BODY_EXCEPTION', 'BODY_BASE_EXCEPTION')
PATH_KEYWORDS = frozenset(('path', 'filename', 'filepath', 'file_name', 'file_path',
                          'lock_path', 'lockfile', 'lock_file', 'lockfile_path', 'target_path', 'output_path'))
DIRECTORY_KEYWORDS = frozenset(('lock_dir', 'directory', 'dir'))
TEMPFILE_OPTIONS = frozenset(('mode','buffering','encoding','errors','newline','suffix','prefix',
                             'delete','ignore_cleanup_errors','delete_on_close'))
LEGACY_METHODS = ('incident_reference.py', 'reliability_path_context.py',
                  'reliability_path_context_worker.py', 'run_reliability_path_context.py')
METHODS = (*LEGACY_METHODS, 'reliability_signature_context.py')


def methods():
    return {n: hashlib.sha256((Path(__file__).parent/n).read_bytes()).hexdigest() for n in METHODS}


def archived_method_names(base,all_names):
    "Archived method names."
    c.require(set(base['method']) in (set(LEGACY_METHODS),set(METHODS)), 'PATH_CONTEXT_ARCHIVED_BASE_METHOD_SET')
    return set(base['method']) | (set(all_names)-set(METHODS))


def native_import_capability():
    "Native import capability."
    proof = dict(kind='PINNED_NATIVE_IMPORT_CAPABILITY_V1', module='fcntl', available=False,
                 implementation=sys.implementation.name, platform=sys.platform,
                 backend=None, artifact_sha256=None, target_imported=False)
    if sys.implementation.name != 'cpython' or sys.platform != 'linux':return c.seal(proof)
    try:
        module = importlib.import_module('fcntl');spec = module.__spec__
        c.require(spec.name == 'fcntl' and module is sys.modules.get('fcntl'), 'PATH_CONTEXT_NATIVE_IMPORT_ORIGIN')
        if spec.origin == 'built-in':
            c.require(spec.loader is importlib.machinery.BuiltinImporter and 'fcntl' in sys.builtin_module_names,
                      'PATH_CONTEXT_NATIVE_IMPORT_ORIGIN')
            origin=Path(sys.executable).resolve();backend='BUILTIN'
        else:
            origin = Path(spec.origin).resolve();backend='EXTENSION'
            stdlib = Path(sysconfig.get_path('stdlib')).resolve()
            c.require(isinstance(spec.loader, importlib.machinery.ExtensionFileLoader)
                      and origin.is_relative_to(stdlib), 'PATH_CONTEXT_NATIVE_IMPORT_ORIGIN')
        c.require(origin.is_file() and origin.stat().st_size <= 16777216, 'PATH_CONTEXT_NATIVE_IMPORT_ARTIFACT_BOUND')
        proof.update(available=True, backend=backend, artifact_sha256=hashlib.sha256(origin.read_bytes()).hexdigest())
    except (ImportError, OSError, ValueError, AttributeError, TypeError):pass
    return c.seal(proof)


def standard_import_capabilities():
    "Standard import capabilities."
    result={}
    for name in ('tomllib',):
        proof=dict(kind='PINNED_STANDARD_PYTHON_IMPORT_V1',module=name,available=False,
                   files_sha256={},target_imported=False)
        try:
            module=importlib.import_module(name);spec=module.__spec__
            origin=Path(spec.origin).resolve()
            c.require(isinstance(spec.loader,importlib.machinery.SourceFileLoader)
                and origin.is_relative_to(Path('/usr/lib').resolve()),'PATH_CONTEXT_STANDARD_IMPORT_ORIGIN')
            files=sorted(origin.parent.glob('*.py'))
            c.require(1<=len(files)<=8 and all(not p.is_symlink() and p.stat().st_size<=262144 for p in files),
                      'PATH_CONTEXT_STANDARD_IMPORT_BYTES')
            proof.update(available=True,files_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in files})
        except (ImportError,ValueError,AttributeError,TypeError,OSError):pass
        result[name]=c.seal(proof)
    return result


def guarded_analysis(text, *, capability=None):
    "Guarded analysis."
    tree = ast.parse(text);omitted = []
    if capability is None:return tree, omitted
    c.check_seal(capability)
    c.require(capability == native_import_capability(), 'PATH_CONTEXT_NATIVE_IMPORT_DRIFT')
    pinned={name for name,value in standard_import_capabilities().items() if value['available']}
    if capability['available']:pinned.add('fcntl')
    if not pinned:return tree, omitted
    
    reserved = {'ImportError', '__builtins__', '__import__'}
    machinery = {'sys', 'modules', 'meta_path', 'path_hooks', 'path_importer_cache',
                 '__dict__', '__getattribute__', '__setattr__'}
    for node in ast.walk(tree):
        if (isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)) and node.id in reserved
            or isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and node.name in reserved
            or isinstance(node, ast.arg) and node.arg in reserved
            or isinstance(node, ast.ExceptHandler) and node.name in reserved
            or isinstance(node, ast.alias) and (node.asname or node.name.split('.')[0]) in reserved
            or isinstance(node,ast.ImportFrom) and node.module=='sys'
                and any(a.name not in ('platform','version','version_info','maxsize','getfilesystemencoding',
                                       'getdefaultencoding') for a in node.names)
            or isinstance(node, ast.Attribute) and node.attr in machinery
            or isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == 'getattr'):
            return tree, omitted
    class Reachable(ast.NodeTransformer):
        def visit_Try(self, node):
            
            if (len(node.body) == len(node.handlers) == 1 and isinstance(node.body[0], ast.Import)
                and len(node.body[0].names) == 1 and node.body[0].names[0].name in pinned
                and isinstance(node.handlers[0].type, ast.Name) and node.handlers[0].type.id == 'ImportError'):
                module_name=node.body[0].names[0].name
                omitted.append(dict(try_line=node.lineno, handler_line=node.handlers[0].lineno,
                    reason='PINNED_FCNTL_IMPORT_FALLBACK_NOT_SELECTED' if module_name=='fcntl'
                        else 'PINNED_STANDARD_IMPORT_FALLBACK_NOT_SELECTED',
                    **({} if module_name=='fcntl' else {'imported_standard_module':module_name})))
                replacement = ast.If(test=ast.Constant(value=True),
                                     body=node.body + node.orelse + node.finalbody, orelse=[])
                return self.generic_visit(ast.copy_location(replacement, node))
            return self.generic_visit(node)
    return Reachable().visit(tree), omitted


def source_guard(text, *, capability=None):
    "Source guard."
    tree,_=guarded_analysis(text, capability=capability);aliases={};builtin_modules=set()
    parents={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    for node in ast.walk(tree):
        if isinstance(node,ast.Name) and isinstance(node.ctx,(ast.Store,ast.Del)):
            c.require(node.id not in ('__builtins__','__import__'), 'PATH_CONTEXT_REFLECTION_HELD')
        if isinstance(node,ast.Import):
            aliases.update({a.asname or a.name.split('.')[0]:a.name for a in node.names})
            builtin_modules.update(a.asname or a.name for a in node.names if a.name=='builtins')
        elif isinstance(node,ast.ImportFrom) and not node.level:
            c.require(node.module is not None and not node.module.startswith(('incident_reference','reliability_',
                'run_reliability_','ctypes','cffi','marshal')), 'PATH_CONTEXT_ORACLE_IMPORT_HELD')
            if node.module=='sys':
                c.require(all(a.name in ('platform','version','version_info','maxsize','getfilesystemencoding',
                    'getdefaultencoding') for a in node.names),'PATH_CONTEXT_INTERPRETER_ACCESS_HELD')
            if node.module=='builtins':
                c.require(all(a.name=='open' for a in node.names),'PATH_CONTEXT_BUILTIN_ACCESS_HELD')
    c.require(not any(v.startswith(('incident_reference','reliability_','run_reliability_',
                                   'ctypes','cffi','marshal')) for v in aliases.values()),
              'PATH_CONTEXT_ORACLE_IMPORT_HELD')
    for node in ast.walk(tree):
        if isinstance(node,ast.Name) and node.id in ('__builtins__','__import__'):
            raise ValueError('PATH_CONTEXT_REFLECTION_HELD')
        if isinstance(node,ast.Name) and node.id in builtin_modules:
            parent=parents.get(node)
            c.require(isinstance(parent,ast.Attribute) and parent.value is node
                and parent.attr=='open' and isinstance(parent.ctx,ast.Load)
                and isinstance(node.ctx,ast.Load),'PATH_CONTEXT_BUILTIN_ACCESS_HELD')
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name):
            c.require(node.func.id not in ('exec','eval','compile','globals','locals','vars','__import__',
                                           'setattr','delattr'), 'PATH_CONTEXT_REFLECTION_HELD')
        if isinstance(node,ast.Attribute):
            c.require(node.attr not in ('__globals__','__builtins__','__subclasses__','__code__','__closure__'),
                      'PATH_CONTEXT_REFLECTION_HELD')
            root=node
            while isinstance(root,ast.Attribute):root=root.value
            if isinstance(root,ast.Name) and aliases.get(root.id)=='sys':
                c.require(isinstance(node.value,ast.Name) and node.attr in ('platform','version','version_info',
                    'maxsize','getfilesystemencoding','getdefaultencoding') and isinstance(node.ctx,ast.Load),
                    'PATH_CONTEXT_INTERPRETER_ACCESS_HELD')
    return tree


def module_names(sources):
    names = set()
    for member in sources:
        path = PurePosixPath(member)
        parts = list(path.parts)
        if parts[0] == 'src':
            parts = parts[1:]
        parts[-1] = parts[-1][:-3]
        if parts[-1] == '__init__':
            parts = parts[:-1]
        if parts and all(p.isidentifier() for p in parts) and parts[0] not in sys.stdlib_module_names:
            names.add('.'.join(parts))
    return names


def example_blocks(text):
    "Example blocks."
    blocks=[(m.start(2),m.end(2),m.group(2)) for m in
        re.finditer(r'^```([^\n]*)\n(.*?)^```[ \t]*(?:\n|$)',text,re.S|re.M)
        if m.group(1).strip() in ('','python','py')]
    lines=text.splitlines(keepends=True);offsets=[];offset=0
    for line in lines:offsets.append(offset);offset+=len(line)
    # Markdown's indented code and RST literal examples. Parsing later requires
    # an original package import and a literal public path constructor.
    index=0
    while index<len(lines):
        if not lines[index].startswith('    ') or not lines[index].strip():index+=1;continue
        first=index
        while index<len(lines) and (lines[index].startswith('    ') or not lines[index].strip()):index+=1
        code=''.join(q[4:] if q.startswith('    ') else q for q in lines[first:index])
        blocks.append((offsets[first],offsets[index] if index<len(lines) else len(text),code))
    for index,line in enumerate(lines):
        if not re.match(r'^\s*\.\. (?:code-block|code):: python\s*$',line):continue
        first=index+1
        while first<len(lines) and (not lines[first].strip() or lines[first].lstrip().startswith(':')):first+=1
        if first==len(lines) or not lines[first][:1].isspace():continue
        indent=len(lines[first])-len(lines[first].lstrip());last=first
        while last<len(lines) and (not lines[last].strip() or len(lines[last])-len(lines[last].lstrip())>=indent):last+=1
        code=''.join(q[indent:] if q.strip() else q for q in lines[first:last])
        blocks.append((offsets[first],offsets[last] if last<len(lines) else len(text),code))
    index=0
    while index<len(lines):
        if not re.match(r'^\s*>>> ',lines[index]):index+=1;continue
        first=index;code=[]
        while index<len(lines):
            m=re.match(r'^\s*(?:>>>|\.\.\.) ?(.*?)(\n?)$',lines[index])
            if not m:break
            code.append(m.group(1)+m.group(2));index+=1
        blocks.append((offsets[first],offsets[index] if index<len(lines) else len(text),''.join(code)))
    return sorted(set(blocks))[:64]


def documented_assignments(tree):
    "Documented assignments."
    writes = {}; invalid = set(); assignments = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            writes[node.id] = writes.get(node.id, 0) + 1
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            invalid.add(node.name)
        elif isinstance(node, ast.arg):invalid.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:invalid.add(node.name)
        elif isinstance(node, ast.alias):invalid.add(node.asname or node.name.split('.')[0])
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            root = node
            while isinstance(root, ast.Attribute):root = root.value
            if isinstance(root, ast.Name):invalid.add(root.id)
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign) and node.value is not None:
            target = node.target
        else:continue
        if isinstance(target, ast.Name) and writes.get(target.id) == 1 and target.id not in invalid:
            assignments[target.id] = (node.lineno, node.value)
    return assignments


def documented_path(expression, *, before, assignments, imports, ambiguous, shadowed, seen=()):
    "Documented path."
    if isinstance(expression, ast.Constant) and type(expression.value) is str:return 'STR'
    if isinstance(expression, ast.Name):
        c.require(expression.id not in seen and len(seen) < 8, 'PATH_CONTEXT_PATH_ARGUMENT_UNKNOWN')
        assignment = assignments.get(expression.id)
        c.require(assignment is not None and assignment[0] < before, 'PATH_CONTEXT_PATH_ARGUMENT_UNKNOWN')
        return documented_path(assignment[1], before=assignment[0], assignments=assignments,
            imports=imports, ambiguous=ambiguous, shadowed=shadowed, seen=(*seen, expression.id))
    c.require(isinstance(expression, ast.Call) and len(expression.args) == 1 and not expression.keywords
              and isinstance(expression.args[0], ast.Constant) and type(expression.args[0].value) is str,
              'PATH_CONTEXT_PATH_ARGUMENT_UNKNOWN')
    reference = ast.unparse(expression.func).split('.')
    c.require(reference[0] not in shadowed and reference[0] not in ambiguous,
              'PATH_CONTEXT_PATH_ARGUMENT_UNKNOWN')
    resolved = imports.get(reference[0])
    c.require(resolved is not None and '.'.join([resolved, *reference[1:]]) == 'pathlib.Path',
              'PATH_CONTEXT_PATH_ARGUMENT_UNKNOWN')
    return 'PATHLIB_PATH'


def documented_context_constructor(call, assignments):
    "Documented context constructor."
    if not isinstance(call, ast.Call):return call, None
    receiver = call.func.value if isinstance(call.func, ast.Attribute) else None
    if isinstance(receiver, ast.Name):
        assignment = assignments.get(receiver.id)
        receiver = assignment[1] if assignment and assignment[0] < call.lineno else None
    if not isinstance(receiver, ast.Call):return call, None
    name = call.func.attr
    c.require(name.isidentifier() and not name.startswith('_'), 'PATH_CONTEXT_PUBLIC_METHOD_REQUIRED')
    
    args = [ast.literal_eval(n) for n in call.args]
    kwargs = {n.arg:ast.literal_eval(n.value) for n in call.keywords}
    c.require(None not in kwargs and len(kwargs)==len(call.keywords) and len(args)<=2 and len(kwargs)<=4
        and all(type(v) in (str,int,float,bool,type(None)) for v in [*args,*kwargs.values()])
        and all(type(v) is not str or len(v)<=100 and '/' not in v and '\\' not in v
                and '\0' not in v for v in [*args,*kwargs.values()])
        and all(type(v) is not float or abs(v)<=60 for v in [*args,*kwargs.values()]),
        'PATH_CONTEXT_METHOD_ARGUMENTS_HELD')
    return receiver, dict(name=name,args=args,kwargs=kwargs)


def owned_constructor_arguments(binding, path):
    "Owned constructor arguments."
    descriptor = binding.get('path_argument')
    args = list(binding['args']);kwargs = dict(binding['kwargs'])
    if descriptor is None:return [str(path), *args], kwargs
    fields = {'placement', 'keyword', 'value_type'}
    directory = type(descriptor) is dict and descriptor.get('role') == 'DIRECTORY'
    c.require(type(descriptor) is dict and set(descriptor) == fields | ({'role'} if directory else set())
              and descriptor['value_type'] in ('STR', 'PATHLIB_PATH')
              and (not directory or descriptor['placement'] == 'KEYWORD'), 'PATH_CONTEXT_PATH_BINDING_UNKNOWN')
    value = Path(path) if descriptor['value_type'] == 'PATHLIB_PATH' else str(path)
    if descriptor['placement'] == 'TEMPFILE_DEFAULT':
        c.require(not directory and descriptor['keyword'] is None
                  and (not args or len(args)==1 and type(args[0]) is int and 1<=args[0]<=8)
                  and descriptor['value_type'] == 'STR', 'PATH_CONTEXT_PATH_BINDING_UNKNOWN')
        c.require(set(kwargs)<=TEMPFILE_OPTIONS and all(type(kwargs[k]) is str
            and '/' not in kwargs[k] and '\\' not in kwargs[k] and '\0' not in kwargs[k]
            for k in ('prefix','suffix') if k in kwargs),'PATH_BINDING_UNKNOWN')
        return args, kwargs
    elif descriptor['placement'] == 'POSITIONAL':
        c.require(descriptor['keyword'] is None, 'PATH_CONTEXT_PATH_BINDING_UNKNOWN')
        args.insert(0, value)
    else:
        c.require(descriptor['placement'] == 'KEYWORD'
                  and descriptor['keyword'] in (DIRECTORY_KEYWORDS if directory else PATH_KEYWORDS)
                  and descriptor['keyword'] not in kwargs and (directory or not args),
                  'PATH_CONTEXT_PATH_BINDING_UNKNOWN')
        if directory:
            c.require(len(args) <= 1 and all(type(v) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', v)
                      and v not in ('.', '..') for v in args), 'PATH_CONTEXT_PATH_BINDING_UNKNOWN')
        kwargs[descriptor['keyword']] = value
    return args, kwargs


def recipes(sources, documents):
    "Recipes."
    c.require(type(sources) is dict and 0<len(sources)<=1024, 'PATH_CONTEXT_SOURCE_COUNT')
    total=0
    for name,text in sources.items():
        c.require(type(name) is str and type(text) is str, 'PATH_CONTEXT_SOURCE_TYPE')
        path=PurePosixPath(name)
        c.require(not path.is_absolute() and '..' not in path.parts and str(path)==name
                  and '\\' not in name and name.endswith('.py'), 'PATH_CONTEXT_SOURCE_PATH')
        size=len(text.encode());total+=size
        c.require(size<=262144, 'PATH_CONTEXT_SOURCE_BYTES')
    c.require(total<=16777216, 'PATH_CONTEXT_TOTAL_BYTES')
    c.require(type(documents) is dict and 0 <= len(documents) <= 20
              and all(type(k) is str and type(v) is str and len(v.encode()) <= 262144
                      for k,v in documents.items()), 'PATH_CONTEXT_DOCUMENTS')
    modules = module_names(sources); rows = []; held = []
    for document, text in sorted(documents.items()):
        blocks=example_blocks(text)
        parsed=[];global_imports={};ambiguous=set();shadowed=set()
        for start,end,code in blocks:
            if len(code.encode()) > 16384:
                continue
            try:
                tree = ast.parse(code)
            except SyntaxError:
                continue
            imports = {}
            for node in ast.walk(tree):
                if isinstance(node,ast.Name) and isinstance(node.ctx,(ast.Store,ast.Del)):shadowed.add(node.id)
                elif isinstance(node,ast.Attribute) and isinstance(node.ctx,(ast.Store,ast.Del)):
                    root=node
                    while isinstance(root,ast.Attribute):root=root.value
                    if isinstance(root,ast.Name):shadowed.add(root.id)
                elif isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):shadowed.add(node.name)
                elif isinstance(node,ast.arg):shadowed.add(node.arg)
                elif isinstance(node,ast.ExceptHandler) and node.name:shadowed.add(node.name)
            for node in tree.body:
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        imports[alias.asname or alias.name.split('.')[0]] = alias.name if alias.asname else alias.name.split('.')[0]
                elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                    for alias in node.names:
                        if alias.name != '*':
                            imports[alias.asname or alias.name] = node.module+'.'+alias.name
            for alias,module in imports.items():
                if alias in global_imports and global_imports[alias]!=module:ambiguous.add(alias)
                global_imports[alias]=module
            parsed.append((start,end,code,tree,imports))
        for start,end,code,tree,imports in parsed:
            imports={**{k:v for k,v in global_imports.items() if k not in ambiguous},**imports}
            assignments=documented_assignments(tree)
            for node in ast.walk(tree):
                if not isinstance(node, ast.With) or len(node.items) != 1:
                    continue
                call = node.items[0].context_expr
                if isinstance(call,ast.Name):
                    assignment=assignments.get(call.id)
                    call=assignment[1] if assignment and assignment[0]<node.lineno else None
                if not isinstance(call, ast.Call):
                    continue
                try:
                    call, context_method = documented_context_constructor(call, assignments)
                except (ValueError, TypeError):
                    held.append(dict(document=document, reason='PATH_CONTEXT_METHOD_ARGUMENTS_HELD'))
                    continue
                reference = ast.unparse(call.func).split('.')
                if reference[0] in shadowed:continue
                resolved = imports.get(reference[0])
                if resolved is None:
                    
                    
                    if (len(reference)<2 or '.'.join(reference[:-1]) not in modules
                        or reference[0] in ambiguous):continue
                    resolved='.'.join(reference)
                else:
                    resolved = '.'.join([resolved, *reference[1:]])
                module, _, symbol = resolved.rpartition('.')
                if module not in modules or not symbol.isidentifier() or symbol.startswith('_'):
                    continue
                try:
                    path_keywords = [n for n in call.keywords if n.arg in PATH_KEYWORDS]
                    directory_keywords = [n for n in call.keywords if n.arg in DIRECTORY_KEYWORDS]
                    directory = bool(directory_keywords)
                    count_argument = (len(call.args)==1 and isinstance(call.args[0],ast.Constant)
                        and type(call.args[0].value) is int and 1<=call.args[0].value<=8)
                    temporary_default = (not call.args or count_argument) and not path_keywords and not directory_keywords
                    c.require((len(directory_keywords) == 1 and not path_keywords and len(call.args) <= 1)
                              if directory else ((bool(call.args) and not path_keywords)
                                                 or (not call.args and len(path_keywords) == 1)
                                                 or temporary_default),
                              'PATH_CONTEXT_PATH_ARGUMENT_UNKNOWN')
                    keyword = None if temporary_default else (directory_keywords[0].arg if directory else (None if call.args else path_keywords[0].arg))
                    expression = None if temporary_default else (directory_keywords[0].value if directory else (call.args[0] if call.args else path_keywords[0].value))
                    value_type = 'STR' if temporary_default else documented_path(expression, before=call.lineno,
                        assignments=assignments, imports=imports, ambiguous=ambiguous, shadowed=shadowed)
                except (ValueError, TypeError):
                    held.append(dict(document=document, reason='PATH_CONTEXT_PATH_ARGUMENT_UNKNOWN'))
                    continue
                try:
                    args = [ast.literal_eval(n) for n in (call.args if directory or temporary_default else call.args[1:])]
                    if directory:
                        c.require(all(type(v) is str and re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', v)
                                  and v not in ('.', '..') for v in args), 'PATH_CONTEXT_LITERAL_ARGUMENTS')
                    extra_keywords = [n for n in call.keywords if keyword is None or n.arg != keyword]
                    kwargs = {n.arg:ast.literal_eval(n.value) for n in extra_keywords}
                    if temporary_default:
                        c.require(set(kwargs)<=TEMPFILE_OPTIONS and all(type(kwargs[k]) is str
                            and '/' not in kwargs[k] and '\\' not in kwargs[k] and '\0' not in kwargs[k]
                            for k in ('prefix','suffix') if k in kwargs),'PATH_CONTEXT_TEMPFILE_OPTIONS_HELD')
                    c.require(None not in kwargs and len(kwargs)==len(extra_keywords)
                              and len(args)<=2 and len(kwargs)<=4
                              and all(type(v) in (str,int,float,bool,type(None)) for v in [*args,*kwargs.values()]),
                              'PATH_CONTEXT_LITERAL_ARGUMENTS')
                    c.require(all(not isinstance(v,float) or abs(v)<=60 for v in [*args,*kwargs.values()])
                              and all(type(v) is not str or len(v)<=100 for v in [*args,*kwargs.values()]),
                              'PATH_CONTEXT_ARGUMENT_BOUND')
                except (ValueError, TypeError):
                    held.append(dict(document=document, reason='PATH_CONTEXT_CONSTRUCTOR_ARGUMENTS_UNKNOWN'))
                    continue
                binding = dict(profile=PROFILE,module=module,symbol=symbol,args=args,kwargs=kwargs)
                if context_method is not None:binding['context_method'] = context_method
                
                if keyword is not None or value_type != 'STR' or temporary_default:
                    binding['path_argument'] = dict(placement='TEMPFILE_DEFAULT' if temporary_default else ('KEYWORD' if keyword else 'POSITIONAL'),
                                                    keyword=keyword, value_type=value_type)
                    if directory:binding['path_argument']['role'] = 'DIRECTORY'
                if any(r['binding']==binding for r in rows):
                    continue
                rows.append(dict(binding=binding,document=document,
                    document_sha256=hashlib.sha256(text.encode()).hexdigest(),span=dict(start=start,end=end,
                    sha256=hashlib.sha256(text[start:end].encode()).hexdigest()),example_sha256=hashlib.sha256(code.encode()).hexdigest(),
                    original_path_literal_retained_in_private_document=True))
                if directory and call.args and isinstance(call.args[0], ast.Constant) and type(call.args[0].value) is str:
                    
                    
                    try:
                        old_kwargs = {n.arg:ast.literal_eval(n.value) for n in call.keywords}
                        c.require(None not in old_kwargs and len(old_kwargs)==len(call.keywords)
                            and len(old_kwargs)<=4 and all(type(v) in (str,int,float,bool,type(None))
                            and (type(v) is not str or len(v)<=100)
                            and (type(v) is not float or abs(v)<=60) for v in old_kwargs.values()),
                            'PATH_CONTEXT_LITERAL_ARGUMENTS')
                        legacy=dict(profile=PROFILE,module=module,symbol=symbol,args=[],kwargs=old_kwargs)
                        if not any(r['binding']==legacy for r in rows):
                            rows.append({**rows[-1], 'binding':legacy})
                    except (ValueError, TypeError):pass
    if not rows:
        import reliability_signature_context as signatures
        rows=signatures.discover(sources,profile=PROFILE,path_keywords=PATH_KEYWORDS,
                                directory_keywords=DIRECTORY_KEYWORDS,allowed_modules=modules)
    c.require(len(rows)<=12, 'PATH_CONTEXT_RECIPE_CAP')
    
    rows.sort(key=lambda row: row['binding'].get('path_argument', {}).get('role') != 'DIRECTORY')
    return c.seal(dict(kind='DOCUMENTED_PATH_CONTEXT_RECIPES_V1',
        sources_sha256=c.digest(sources),rows=rows,held=held,target_imports=0,native_campaigns=0,
        semantics_certified=False,execution_authority=False))


def candidate_recipe(original, sources, documents):
    """Rebind unchanged author evidence and caller arguments to a repair copy."""
    found = recipes(sources, documents)
    if original['recipe_origin'] != 'AUTHOR_DOCUMENTATION_AND_PUBLIC_SIGNATURE':
        c.require(original in found['rows'], 'PATH_CONTEXT_CANDIDATE_DOCUMENT_DRIFT')
        return original
    fixed = ('binding', 'document', 'span_basis', 'source_member', 'signature_sha256',
             'recipe_origin', 'original_path_literal_retained_in_private_document',
             'implementation_behavior_used_as_specification',
             'generated_python_example_presented_as_author_documentation', 'interpretation')
    matches = [row for row in found['rows']
               if all(row.get(key) == original.get(key) for key in fixed)
               and [s['sha256'] for s in row['documentation_spans']]
               == [s['sha256'] for s in original['documentation_spans']]]
    c.require(len(matches) == 1, 'PATH_CONTEXT_CANDIDATE_CALLER_OR_EVIDENCE_DRIFT')
    return matches[0]


def plan(sources, recipe, documents, *, provenance, forecast_ref=None):
    found = recipes(sources, documents)
    c.require(recipe in found['rows'], 'PATH_CONTEXT_RECIPE_DRIFT')
    c.require(type(provenance) is dict and provenance.get('role') in ('KNOWN_DEVELOPMENT', 'FROZEN_UNUSED_COHORT'),
              'PATH_CONTEXT_PROVENANCE')
    return c.seal(dict(kind='FINITE_PATH_CONTEXT_EXECUTION_PLAN_V1',sources=sources,recipe=recipe,
        documents=documents,provenance=provenance,forecast_ref=forecast_ref,event=EVENT,method=methods(),
        faults=list(FAULTS),initial_other_file_contents=['', 'prior-owned-by-another-invocation'],
        semantics='Instantiate the documented public context with an owned sandbox path and documented literal '
                  'arguments. NORMAL must acquire an observable path resource and release it. Body Exception and '
                  'BaseException must propagate and release the resource. Repeat with a new instance. Preserve the '
                  'other invocation file. Runtime baseline/dependency/unsupported failures have UNKNOWN labels.',
        limits=dict(cpu_seconds=2,wall_seconds=5,memory_bytes=134217728,output_bytes=131072,
                    file_bytes=1048576,open_files=64,processes=16),
        native_import_capability=native_import_capability(),
        pinned_standard_import_capabilities=standard_import_capabilities(),
        natural_incident_truth_certified=False,target_bug_claim_eligible=False,
        original_implementation_mutated=False,execution_authority=False))


def check_execution_boundary(value):
    """Verify the child boundary recorded before importing Target code."""
    c.require(type(value) is dict and type(value.get('uid')) is int and value['uid'] > 0
              and value.get('effective_capabilities') == 0 and value.get('home_visible') is False
              and value.get('cpu_seconds') == [2, 2]
              and value.get('memory_bytes') == [134217728, 134217728]
              and value.get('file_bytes') == [131072, 131072]
              and value.get('core_bytes') == [0, 0], 'PATH_CONTEXT_EXECUTION_BOUNDARY')

