"Build bounded cleanup repair candidates for private snapshots."
import ast
from collections import Counter
import hashlib
from pathlib import Path
import re

import reliability_path_context as context

c=context.c
EVENT='FINITE_TRANSIENT_TEMP_CLEANUP_REQUIREMENT_V1'
METHODS=(*context.METHODS,'reliability_source_study.py')


def methods():
    return {name:hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest() for name in METHODS}


def project(reference):
    "Project."
    c.check_seal(reference);text=reference['text']
    c.require(reference['kind']=='PUBLIC_FAILURE_REFERENCE_V1' and reference['url'].startswith('https://')
        and type(text) is str and 0<len(text.encode())<=4096
        and reference['text_sha256']==hashlib.sha256(text.encode()).hexdigest(), 'SOURCE_STUDY_REFERENCE')
    matches=list(re.finditer(r'[^\n]*(?:unlink|remove)[^\n]*\bEIO\b[^\n]*',text,re.I))
    return c.seal(dict(kind='REFERENCE_CLEANUP_CONDITION_PROJECTION_V1',
        source_sha256=reference['record_sha256'],conditions=[dict(operation='DELETE',errno='EIO',
        phase='CONTEXT_CLEANUP',occurrence=1,span=dict(start=m.start(),end=m.end(),
        sha256=hashlib.sha256(m.group().encode()).hexdigest())) for m in matches[:1]],
        transient_once_is_owner_policy=True,origin='INFERRED_FROM_REFERENCE',
        natural_incident_verified=False,source_semantic_support_certified=False,execution_authority=False))


def plan(base_plan, *, arm, reference=None, permanent_control=False):
    c.check_seal(base_plan)
    c.require(arm in ('SOURCE','NO_SOURCE') and type(permanent_control) is bool, 'SOURCE_STUDY_ARM')
    c.require(base_plan==context.plan(base_plan['sources'],base_plan['recipe'],base_plan['documents'],
        provenance=base_plan['provenance'],forecast_ref=base_plan['forecast_ref']), 'SOURCE_STUDY_CONTEXT_BINDING')
    c.require((arm=='SOURCE')==(reference is not None) and (arm=='SOURCE' or not permanent_control),
        'SOURCE_STUDY_ARM_DISCLOSURE')
    projection=project(reference) if reference else None
    c.require(projection is None or len(projection['conditions'])==1,'SOURCE_STUDY_SUPPORTED_REFERENCE_REQUIRED')
    return c.seal(dict(kind='FINITE_SOURCE_CONTEXT_STUDY_PLAN_V1',event=EVENT,base_plan=base_plan,
        arm=arm,source_reference=reference,source_projection=projection,permanent_control=permanent_control,
        method=methods(),maximum_discovery_conditions=3,
        owner_requirement='Release the acquired temporary resource and preserve other-owner contents and body '
            'exceptions when cleanup receives one injected EIO, after which the same operation can succeed. '
            'Permanent EIO is a separate bounded-retry control, outside this adoption envelope.',
        inference_is_not_a_natural_incident=True,target_bug_claim_eligible=False,execution_authority=False))


def candidate(sources, *, retry_errnos=('EIO',), ignore_absent=False):
    "Candidate."
    c.require(tuple(retry_errnos) in (('EIO',),('EIO','EINTR')), 'SOURCE_STUDY_REPAIR_ERRNO_POLICY')
    c.require(type(ignore_absent) is bool, 'SOURCE_STUDY_REPAIR_ABSENCE_POLICY')
    errno_test='_reqlox_cleanup_error.errno != _reqlox_cleanup_errno.EIO' if len(retry_errnos)==1 else \
        '_reqlox_cleanup_error.errno not in (_reqlox_cleanup_errno.EIO, _reqlox_cleanup_errno.EINTR)'
    result=dict(sources);changed=[]
    for member,text in sorted(sources.items()):
        tree=ast.parse(text);aliases=set();path_names=set()
        for node in tree.body:
            if isinstance(node,ast.Import):
                aliases.update(a.asname or 'os' for a in node.names if a.name=='os')
            if isinstance(node,ast.ImportFrom) and node.module=='pathlib':
                path_names.update(a.asname or a.name for a in node.names if a.name=='Path')
        if not aliases and not path_names:continue
        reserved={'_reqlox_cleanup_error','_reqlox_cleanup_errno','_reqlox_cleanup_path',
                  '_reqlox_cleanup_delete','_reqlox_cleanup_retries_left'}
        if ignore_absent:reserved.add('_reqlox_cleanup_os')
        identifiers={n.id for n in ast.walk(tree) if isinstance(n,ast.Name)}
        identifiers.update(n.arg for n in ast.walk(tree) if isinstance(n,ast.arg))
        identifiers.update(n.asname or n.name for n in ast.walk(tree) if isinstance(n,ast.alias))
        identifiers.update(n.name for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef)))
        identifiers.update(n.name for n in ast.walk(tree) if isinstance(n,ast.ExceptHandler) and n.name)
        identifiers.update(name for n in ast.walk(tree) if isinstance(n,(ast.Global,ast.Nonlocal)) for name in n.names)
        c.require(not identifiers & reserved,
                  'SOURCE_STUDY_REPAIR_NAME_COLLISION')
        # Aliases and OSError must retain their standard meaning throughout the module.
        if any(isinstance(n,ast.Name) and isinstance(n.ctx,(ast.Store,ast.Del))
               and n.id in aliases|path_names|{'OSError'} for n in ast.walk(tree)):
            continue
        if any(isinstance(n,ast.arg) and n.arg in aliases|path_names|{'OSError'} for n in ast.walk(tree)):
            continue
        if any(isinstance(n,(ast.FunctionDef,ast.ClassDef,ast.AsyncFunctionDef))
               and n.name in aliases|path_names|{'OSError'} for n in ast.walk(tree)):
            continue
        import_bindings=Counter(a.asname or a.name.split('.')[0] for n in ast.walk(tree)
            if isinstance(n,(ast.Import,ast.ImportFrom)) for a in n.names)
        if import_bindings['OSError'] or any(import_bindings[name]!=1 for name in aliases|path_names):continue
        def path_expression(expr):
            if not isinstance(expr,ast.Call):return False
            if isinstance(expr.func,ast.Name) and expr.func.id in path_names:return True
            return (isinstance(expr.func,ast.Attribute) and expr.func.attr in ('joinpath','with_name','with_suffix')
                    and path_expression(expr.func.value))
        factories=set()
        for function in tree.body:
            if isinstance(function,ast.FunctionDef) and not function.decorator_list:
                returns=[n.value for n in ast.walk(function) if isinstance(n,ast.Return)]
                if returns and all(path_expression(v) for v in returns):factories.add(function.name)
        factories-={n.id for n in ast.walk(tree) if isinstance(n,ast.Name) and isinstance(n.ctx,(ast.Store,ast.Del))}
        factories-={n.arg for n in ast.walk(tree) if isinstance(n,ast.arg)}
        for name in list(factories):
            if sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)) and n.name==name
                   for n in ast.walk(tree))!=1:factories.remove(name)
        def owned_attributes(owner):
            writes={}
            if owner.bases or owner.decorator_list:return set()
            if any(isinstance(n,ast.FunctionDef) and n.name in ('__setattr__','__getattribute__')
                   or isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                   and n.func.id in ('setattr','delattr','exec','eval') for n in ast.walk(owner)):return set()
            for assignment in ast.walk(owner):
                if isinstance(assignment,ast.Assign):
                    for target in assignment.targets:
                        if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=='self':
                            writes.setdefault(target.attr,[]).append(assignment.value)
                elif isinstance(assignment,(ast.AnnAssign,ast.AugAssign)):
                    target=assignment.target
                    if isinstance(target,ast.Attribute) and isinstance(target.value,ast.Name) and target.value.id=='self':
                        writes.setdefault(target.attr,[]).append(None)
            result=set()
            for name,values in writes.items():
                if len(values)==1 and (path_expression(values[0]) or isinstance(values[0],ast.Call)
                                      and isinstance(values[0].func,ast.Name) and values[0].func.id in factories):
                    result.add(name)
            return result
        if any(isinstance(n,ast.Attribute) and isinstance(n.value,ast.Name)
               and n.value.id in aliases and isinstance(n.ctx,(ast.Store,ast.Del)) for n in ast.walk(tree)):
            continue
        class Rewrite(ast.NodeTransformer):
            cleanup=False;count=0;function=False;function_changed=False;path_attributes=set()
            def visit_ClassDef(self,node):
                prior=self.path_attributes;self.path_attributes=owned_attributes(node)
                node=self.generic_visit(node);self.path_attributes=prior;return node
            def visit_FunctionDef(self,node):
                prior=self.cleanup;prior_function=self.function;prior_changed=self.function_changed
                self.cleanup=node.name=='__exit__';self.function=True;self.function_changed=False
                node=self.generic_visit(node)
                if self.function_changed:
                    at=1 if (node.body and isinstance(node.body[0],ast.Expr)
                        and isinstance(node.body[0].value,ast.Constant)
                        and isinstance(node.body[0].value.value,str)) else 0
                    node.body[at:at]=ast.parse('_reqlox_cleanup_retries_left = 1').body
                self.cleanup=prior;self.function=prior_function;self.function_changed=prior_changed;return node
            def visit_AsyncFunctionDef(self,node):
                prior=self.cleanup;prior_function=self.function;self.cleanup=False;self.function=False
                node=self.generic_visit(node);self.cleanup=prior;self.function=prior_function;return node
            def visit_Try(self,node):
                prior=self.cleanup
                def block(nodes):
                    rows=[]
                    for n in nodes:
                        value=self.visit(n)
                        rows.extend(value if isinstance(value,list) else [value])
                    return rows
                node.body=block(node.body);node.handlers=block(node.handlers);node.orelse=block(node.orelse)
                self.cleanup=self.function;node.finalbody=block(node.finalbody)
                self.cleanup=prior;return node
            def visit_Expr(self,node):
                call=node.value
                if not (self.cleanup and isinstance(call,ast.Call) and isinstance(call.func,ast.Attribute)
                        and not call.keywords):return node
                os_delete=(isinstance(call.func.value,ast.Name) and call.func.value.id in aliases
                           and call.func.attr in ('remove','unlink') and len(call.args)==1)
                value=call.func.value
                path_delete=(call.func.attr=='unlink' and not call.args and isinstance(value,ast.Attribute)
                    and isinstance(value.value,ast.Name) and value.value.id=='self' and value.attr in self.path_attributes)
                if not os_delete and not path_delete:return node
                # Avoid repeated side effects in the deletion argument.
                if os_delete and any(isinstance(n,(ast.Call,ast.Await,ast.Yield,ast.NamedExpr)) for n in ast.walk(call.args[0])):
                    return node
                self.count+=1;self.function_changed=True
                if os_delete:
                    assignment='_reqlox_cleanup_path = '+ast.unparse(call.args[0])
                    call.args=[ast.Name(id='_reqlox_cleanup_path',ctx=ast.Load())]
                else:
                    assignment=('_reqlox_cleanup_path = '+ast.unparse(value)+'\n'
                        '_reqlox_cleanup_delete = _reqlox_cleanup_path.unlink') if ignore_absent else \
                        '_reqlox_cleanup_delete = '+ast.unparse(call.func)
                    call.func=ast.Name(id='_reqlox_cleanup_delete',ctx=ast.Load())
                retry='if '+errno_test+' or _reqlox_cleanup_retries_left == 0:\n    raise\n' \
                    '_reqlox_cleanup_retries_left -= 1\n'+ast.unparse(call)+'\n'
                if ignore_absent:
                    retry='if (_reqlox_cleanup_error.errno == _reqlox_cleanup_errno.ENOENT and '\
                        'not _reqlox_cleanup_os.path.lexists(_reqlox_cleanup_path)):\n    pass\nelse:\n'+ \
                        ''.join('    '+line+'\n' for line in retry.splitlines())
                return ast.parse(assignment+'\ntry:\n    '+ast.unparse(call)+'\nexcept OSError as _reqlox_cleanup_error:\n'+
                    ''.join('    '+line+'\n' for line in retry.splitlines())).body
        rewrite=Rewrite();tree=rewrite.visit(tree)
        if rewrite.count:
            c.require(rewrite.count<=4,'SOURCE_STUDY_REPAIR_BOUND')
            at=0
            if tree.body and isinstance(tree.body[0],ast.Expr) and isinstance(tree.body[0].value,ast.Constant) and isinstance(tree.body[0].value.value,str):at=1
            while at<len(tree.body) and isinstance(tree.body[at],ast.ImportFrom) and tree.body[at].module=='__future__':at+=1
            tree.body.insert(at,ast.Import(names=[ast.alias(name='errno',asname='_reqlox_cleanup_errno')]))
            if ignore_absent:
                tree.body.insert(at,ast.Import(names=[ast.alias(name='os',asname='_reqlox_cleanup_os')]))
            ast.fix_missing_locations(tree);result[member]=ast.unparse(tree)+'\n';changed.append(member)
    metadata=dict(kind='BOUNDED_TEMP_CLEANUP_REPAIR_CANDIDATE_V1',sources=result,
        changed_members=changed,original_sources_sha256=c.digest(sources),candidate_sources_sha256=c.digest(result),
        retry_errno='EIO' if len(retry_errnos)==1 else list(retry_errnos),maximum_additional_attempts_per_cleanup=1,
        retry_budget_scope='ONE_SYNC_FUNCTION_INVOCATION',nested_function_invocations_share_retry_budget=False,
        whole_context_retry_bound_certified=False,production_adoption=False,execution_authority=False)
    if ignore_absent:metadata.update(ignore_enoent_only_when_same_path_absent=True,
        absence_is_not_a_concurrent_identity_proof=True)
    return c.seal(metadata)
