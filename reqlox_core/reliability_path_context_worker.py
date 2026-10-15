"Execute original context implementations inside a bounded namespace."

if __name__ == '__main__' and not __package__:
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))
    __package__ = 'reqlox_core'

import datetime
import gc
import hashlib
import importlib
import importlib.abc
import importlib.machinery
import inspect
import json
import os
from pathlib import Path
import resource
import sys
import tempfile

from . import incident_reference as c
from . import reliability_path_context as protocol


class BodyException(Exception):
    pass


class BodyBaseException(BaseException):
    pass


def run(plan_path, digest, *, lifecycle_observer=None):
    value=json.loads(Path(plan_path).read_text());c.check_seal(value)
    c.require(c.digest(value)==digest and value['method']==protocol.methods(), 'PATH_CONTEXT_PLAN_OR_METHOD_DRIFT')
    limit=value['limits']
    resource.setrlimit(resource.RLIMIT_CPU,(limit['cpu_seconds'],limit['cpu_seconds']))
    resource.setrlimit(resource.RLIMIT_AS,(limit['memory_bytes'],limit['memory_bytes']))
    resource.setrlimit(resource.RLIMIT_FSIZE,(limit['output_bytes'],limit['output_bytes']))
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_NOFILE,(limit['open_files'],limit['open_files']))
    resource.setrlimit(resource.RLIMIT_NPROC,(limit['processes'],limit['processes']))
    os.nice(10)
    process_status=dict(line.split(':',1) for line in Path('/proc/self/status').read_text().splitlines() if ':' in line)
    boundary=dict(uid=os.getuid(), effective_capabilities=int(process_status['CapEff'].strip(),16),
        home_visible=Path('/home').exists() or Path('/root').exists(),
        cpu_seconds=list(resource.getrlimit(resource.RLIMIT_CPU)),
        memory_bytes=list(resource.getrlimit(resource.RLIMIT_AS)),
        file_bytes=list(resource.getrlimit(resource.RLIMIT_FSIZE)),
        core_bytes=list(resource.getrlimit(resource.RLIMIT_CORE)))
    protocol.check_execution_boundary(boundary)
    attempts=[]
    # Source pathを追加する前に標準extensionをpinする。Targetの同名moduleを使わない。
    capability=protocol.native_import_capability()
    standard_capabilities=protocol.standard_import_capabilities()
    c.require(capability==value['native_import_capability'], 'PATH_CONTEXT_NATIVE_IMPORT_DRIFT')
    c.require(standard_capabilities==value['pinned_standard_import_capabilities'],
              'PATH_CONTEXT_STANDARD_IMPORT_DRIFT')
    def audit(event,args):
        if event.startswith('socket.') or event in ('subprocess.Popen','os.system','os.exec','os.fork','os.posix_spawn'):
            attempts.append(event);raise RuntimeError('PATH_CONTEXT_EXTERNAL_ACTION_DENIED')
    sys.addaudithook(audit)
    root=Path('/tmp/path-context');root.mkdir()
    sys.path[:0]=['/target/src','/target']
    result=dict(kind='FINITE_PATH_CONTEXT_OBSERVATION_V1',plan_sha256=digest,
        source_snapshot_sha256=c.digest(value['sources']),method=value['method'],
        namespaces={k:os.readlink('/proc/self/ns/'+k) for k in ('user','mnt','pid','net')},rows=[],
        external_action_attempts=attempts,label=None,label_authority='UNKNOWN',error=None,
        public_module=value['recipe']['binding']['module'],public_symbol=value['recipe']['binding']['symbol'],
        original_implementation_mutated=False,raw_source_bundle_verified=False)
    result['execution_boundary']=boundary
    result['native_import_capability']=capability
    result['pinned_standard_import_capabilities']=standard_capabilities
    def phase(name,case):
        if lifecycle_observer is not None:lifecycle_observer(name,case)
    try:
        for name,text in value['sources'].items():
            c.require((Path('/target')/name).read_text()==text, 'PATH_CONTEXT_SOURCE_DRIFT')
        result['raw_source_bundle_verified']=True
        class CheckedTargetFinder(importlib.abc.MetaPathFinder):
            def find_spec(self,fullname,path=None,target=None):
                spec=importlib.machinery.PathFinder.find_spec(fullname,path)
                if spec and spec.origin and Path(spec.origin).is_relative_to('/target'):
                    protocol.source_guard(Path(spec.origin).read_text(), capability=capability)
                return None
        sys.meta_path.insert(0,CheckedTargetFinder())
        recipe=value['recipe']['binding'];module=importlib.import_module(recipe['module'])
        constructor=getattr(module,recipe['symbol'])
        c.require(inspect.isclass(constructor) or inspect.isfunction(constructor), 'PATH_CONTEXT_CONSTRUCTOR_REQUIRED')
        original=inspect.unwrap(constructor);origin=inspect.getsourcefile(original)
        c.require(origin is not None and Path(origin).is_relative_to('/target'), 'PATH_CONTEXT_ORIGINAL_CLASS_REQUIRED')
        result.update(callable_kind='CLASS' if inspect.isclass(constructor) else 'FACTORY_FUNCTION',
            callable_module=original.__module__,callable_symbol=original.__name__,
            callable_source_member=str(Path(origin).relative_to('/target')))
        if inspect.isclass(constructor):
            result.update(class_module=constructor.__module__,class_symbol=constructor.__name__,
                class_source_member=str(Path(origin).relative_to('/target')))
        def context_origin(instance):
            owner=type(instance).__module__
            c.require(owner in protocol.module_names(value['sources']) or owner.split('.')[0] in sys.stdlib_module_names,
                'PATH_CONTEXT_RETURNED_CONTEXT_ORIGIN_UNKNOWN')
            c.require(hasattr(type(instance),'__enter__') and hasattr(type(instance),'__exit__'),
                'PATH_CONTEXT_RETURNED_CONTEXT_PROTOCOL_UNKNOWN')
            return owner
        def make_context(args, kwargs):
            instance = constructor(*args, **kwargs)
            descriptor = recipe.get('context_method')
            if descriptor is None:return instance
            c.require(type(descriptor) is dict and set(descriptor)=={'name','args','kwargs'}
                and descriptor['name'].isidentifier() and not descriptor['name'].startswith('_'),
                'PATH_CONTEXT_PUBLIC_METHOD_REQUIRED')
            method = getattr(instance, descriptor['name'])
            original_method = inspect.unwrap(method)
            method_origin = inspect.getsourcefile(original_method)
            c.require(inspect.ismethod(method) and method.__self__ is instance and method_origin is not None
                and Path(method_origin).is_relative_to('/target'), 'PATH_CONTEXT_ORIGINAL_METHOD_REQUIRED')
            return method(*descriptor['args'], **descriptor['kwargs'])
        for index,prior in enumerate(value['initial_other_file_contents']):
            for fault in value['faults']:
                directory=root/f'case-{index}-{fault}';directory.mkdir();path=directory/'resource'
                directory_argument=recipe.get('path_argument',{}).get('role')=='DIRECTORY'
                if directory_argument:path.mkdir()
                other=directory/'other-owner';other.write_text(prior)
                baseline_paths={str(q) for q in directory.rglob('*')}
                def owned_fds():
                    found=[]
                    for fd in Path('/proc/self/fd').iterdir():
                        try:target=os.readlink(fd)
                        except OSError:continue
                        if target.startswith(str(directory)):found.append((fd.name,target))
                    return found
                baseline=owned_fds();raised=False;expected=BodyException if fault=='BODY_EXCEPTION' else BodyBaseException
                if recipe.get('path_argument',{}).get('placement') == 'TEMPFILE_DEFAULT':
                    tempfile.tempdir = str(directory)
                acquired=False;witness=False;during=[];owned_paths=[]
                call_args,call_kwargs=protocol.owned_constructor_arguments(recipe,path)
                phase('CONSTRUCT',directory.name)
                instance=make_context(call_args,call_kwargs)
                instance_module=context_origin(instance)
                with_entry_error=None
                try:
                    phase('ENTRY',directory.name)
                    with instance:
                        acquired=True;during=owned_fds()
                        owned_paths=[str(q) for q in directory.rglob('*') if q!=other
                                     and (not directory_argument or str(q) not in baseline_paths)]
                        witness=bool(during) or bool(owned_paths)
                        phase('CLEANUP',directory.name)
                        if fault!='NONE':raise expected('owned body failure')
                except expected:
                    raised=True
                except BaseException as exc:
                    with_entry_error=type(exc).__name__
                phase('IDLE',directory.name)
                after=owned_fds()
                paths_released=bool(during) or all(not Path(q).exists() for q in owned_paths)
                passed=(acquired and witness and baseline==after and paths_released and other.read_text()==prior
                        and with_entry_error is None and (fault=='NONE' or raised))
                row=dict(fault=fault,other_file_case=index,entry_acquired=acquired,resource_witness=witness,
                    context_instance_module=instance_module,
                    prior_owned_fds=baseline,remaining_owned_fds=after,other_file_preserved=other.read_text()==prior,
                    owned_path_resource_released=paths_released,
                    body_failure_propagated=raised if fault!='NONE' else None,unexpected_error=with_entry_error,
                    contract_pass=passed)
                result['rows'].append(row)
                if not acquired or not witness:
                    raise ValueError('PATH_CONTEXT_BASELINE_OR_CAPABILITY_UNKNOWN')
                if not passed:
                    result.update(label='FAIL',label_authority='NATIVE_FINITE_REQUIREMENT_ORACLE')
                    break
                del instance;gc.collect()
                try:
                    call_args,call_kwargs=protocol.owned_constructor_arguments(recipe,path)
                    phase('CONSTRUCT_REPEAT',directory.name)
                    again=make_context(call_args,call_kwargs)
                    c.require(context_origin(again)==instance_module,'PATH_CONTEXT_REPEAT_CONTEXT_ORIGIN_DRIFT')
                    phase('ENTRY_REPEAT',directory.name)
                    with again:
                        repeat_fds=owned_fds()
                        repeat_paths=[str(q) for q in directory.rglob('*') if q!=other
                                      and (not directory_argument or str(q) not in baseline_paths)]
                        c.require(bool(repeat_fds) or bool(repeat_paths), 'PATH_CONTEXT_REPEAT_UNKNOWN')
                        phase('CLEANUP_REPEAT',directory.name)
                except (ImportError,MemoryError):raise
                except BaseException as exc:
                    if isinstance(exc,ValueError) and str(exc).startswith('PATH_CONTEXT_'):raise
                    row.update(repeat_error=type(exc).__name__,repeat_pass=False,contract_pass=False)
                    result.update(label='FAIL',label_authority='NATIVE_FINITE_REQUIREMENT_ORACLE')
                    break
                phase('IDLE',directory.name)
                row['repeat_remaining_owned_fds']=owned_fds()
                row['repeat_other_file_preserved']=other.read_text()==prior
                row['repeat_owned_path_resource_released']=bool(repeat_fds) or all(not Path(q).exists() for q in repeat_paths)
                row['repeat_pass']=(row['repeat_remaining_owned_fds']==baseline
                    and row['repeat_other_file_preserved'] and row['repeat_owned_path_resource_released'])
                if not row['repeat_pass']:
                    row['contract_pass']=False
                    result.update(label='FAIL',label_authority='NATIVE_FINITE_REQUIREMENT_ORACLE')
                    break
            if result['label']=='FAIL':break
        if result['label'] is None:result.update(label='PASS',label_authority='NATIVE_FINITE_REQUIREMENT_ORACLE')
    except BaseException as exc:
        result.update(error=type(exc).__name__+':'+str(exc)[:160],label=None,label_authority='UNKNOWN')
    print(json.dumps(c.seal(result),sort_keys=True),flush=True)


if __name__=='__main__':
    run(sys.argv[1],sys.argv[2])
