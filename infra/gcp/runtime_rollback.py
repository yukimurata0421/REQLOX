#!/usr/bin/env python3
"""Restore a verified previous UI release once, retaining failed rollout state."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys

FILES = ('/etc/reqlox/runtime.json', '/etc/codex-host-context/host.json',
         '/etc/codex-host-context/AGENTS.md', '/etc/nginx/nginx.conf',
         '/usr/local/libexec/reqlox-web-bootstrap.py')


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def protected(path):
    p = Path(path); s = p.stat()
    require(not p.is_symlink() and s.st_uid == 0 and not s.st_mode & 0o022
            and s.st_size <= 1048576, 'ROLLBACK_PROTECTED_FILE')
    return p.read_bytes()


def validate(config, backup, current, pointer):
    old = json.loads(backup[0]); actual = json.loads(current[0])
    old_contract = json.loads(backup[1]); contract = json.loads(current[1])
    require(old['release_sha256'] == config['old_release_sha256']
            and actual['release_sha256'] in (config['old_release_sha256'], config['failed_release_sha256']),
            'ROLLBACK_RELEASE_IDENTITY')
    require(old['host_id'] == actual['host_id'] == old_contract['host_id'] == 'reqlox-web'
            and old['project_id'] == actual['project_id'] == old_contract['project_id'] == 'reqlox'
            and old_contract['role'] == 'REQLOX bounded isolated demo', 'ROLLBACK_HOST_SCOPE')
    expected = dict(old, release_sha256=actual['release_sha256'],
                    artifact_object='releases/'+actual['release_sha256']+'.tar.gz')
    require(actual == expected and actual['paid_model_calls_enabled'] is False,
            'ROLLBACK_RUNTIME_BOUNDARY')
    require(contract == dict(old_contract, release_sha256=actual['release_sha256']),
            'ROLLBACK_CONTRACT_BOUNDARY')
    require(current[2] == backup[2] and digest(backup[2]) == config['instructions_sha256'],
            'ROLLBACK_INSTRUCTIONS_CHANGED')
    require(pointer == '/opt/reqlox/releases/'+actual['release_sha256']+'/site',
            'ROLLBACK_SITE_POINTER')
    for index, key in ((3, 'new_nginx_sha256'), (4, 'new_web_bootstrap_sha256')):
        require(digest(current[index]) in (digest(backup[index]), config[key]), 'ROLLBACK_SOURCE_CHANGED')
    require(digest(backup[0]) == config['old_runtime_sha256']
            and digest(backup[1]) == config['old_contract_sha256'], 'ROLLBACK_BACKUP_BINDING')
    return old


def atomic(path, raw, mode=0o644):
    p = Path(path); require(not p.is_symlink(), 'ROLLBACK_DESTINATION_LINK')
    temp = p.with_name(p.name+'.rollback-new')
    with temp.open('xb') as stream:
        os.fchmod(stream.fileno(), mode); stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(temp, p)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def command(*args):
    subprocess.run(args, check=True, timeout=90)


def main(config):
    require(os.getuid() == 0 and sys.version_info[:2] == (3, 11), 'ROLLBACK_STARTUP_IDENTITY')
    for key in ('old_release_sha256', 'failed_release_sha256', 'rollback_method_sha256'):
        require(re.fullmatch('[a-f0-9]{64}', config[key]), 'ROLLBACK_HASH_FORMAT')
    require(re.fullmatch('[a-z0-9-]{1,100}', config['request_id']), 'ROLLBACK_REQUEST_ID')
    require(digest(protected(__file__)) == config['rollback_method_sha256'], 'ROLLBACK_METHOD_CHANGED')
    require(digest(protected('/usr/local/libexec/reqlox-base-bootstrap.py')) == config['base_bootstrap_sha256'],
            'ROLLBACK_BASE_CHANGED')
    base = module('rollback_base', '/usr/local/libexec/reqlox-base-bootstrap.py')
    require(base.metadata('instance/id').decode().strip() == config['physical_instance_id']
            and config['physical_instance_id'] == '3115344231848612081'
            and base.metadata('instance/name').decode().strip() == 'reqlox-web'
            and base.metadata('project/project-id').decode().strip() == 'reqlox', 'ROLLBACK_PHYSICAL_IDENTITY')
    unit = protected('/etc/systemd/system/codex-host-context-refresh.service')
    require(digest(unit) == config['collector_unit_sha256'] and all(p.encode() in unit for p in
        (FILES[1], FILES[2], '/var/lib/reqlox-host-context/HOST_CONTEXT.generated.md')), 'ROLLBACK_COLLECTOR_CHANGED')
    root = Path('/var/lib/reqlox-reviewed-rollouts') / config['failed_release_sha256'] / 'before'
    backup = [protected(root/str(i)) for i in range(len(FILES))]
    hashes = config.get('legacy_backup_sha256')
    if hashes is None:
        hashes = json.loads(protected(root/'manifest.json'))['sha256']
    require(hashes == [digest(raw) for raw in backup], 'ROLLBACK_BACKUP_CHANGED')
    current = [protected(p) for p in FILES]
    pointer = Path('/opt/reqlox/site')
    require(pointer.is_symlink(), 'ROLLBACK_SITE_NOT_LINK')
    old = validate(config, backup, current, str(pointer.resolve()))
    require(json.loads(base.metadata('instance/attributes/reqlox-runtime')) == old,
            'ROLLBACK_METADATA_NOT_OLD_RUNTIME')
    state = Path('/var/lib/reqlox-reviewed-returns') / config['request_id']
    if state.exists():
        require((state/'ready.json').is_file() and current == backup,
                'ROLLBACK_ALREADY_RESERVED_NO_RETRY')
        ready = json.loads(protected(state/'ready.json'))
        require(ready.get('status') == 'RESTORED' and ready.get('release_sha256') == old['release_sha256']
                and json.loads(protected(state/'reserved.json'))['config'] == config,
                'ROLLBACK_COMPLETION_BINDING')
        module('rollback_web', FILES[4]).main()
        return
    state.mkdir(mode=0o700, parents=True)
    (state/'reserved.json').write_text(json.dumps(dict(status='RESERVED', config=config, automatic_retry=False)))
    for i, raw in enumerate(current):
        (state/('failed-'+str(i))).write_bytes(raw)
    (state/'failed-site-pointer').write_text(str(pointer.resolve()))
    try:
        command('systemctl', 'stop', 'reqlox.service', 'nginx.service')
        for i, path in enumerate(FILES):
            atomic(path, backup[i], 0o755 if path.endswith('.py') else 0o644)
        temp = pointer.with_name('site.rollback-new')
        temp.symlink_to('/opt/reqlox/releases/'+old['release_sha256']+'/site'); os.replace(temp, pointer)
        # Reload only the existing secret versions and the restored source.
        module('rollback_web', FILES[4]).main()
        require([protected(p) for p in FILES] == backup, 'ROLLBACK_RESTORED_BYTES_CHANGED')
        (state/'ready.json').write_text(json.dumps(dict(status='RESTORED', release_sha256=old['release_sha256'],
                                                     private_state_preserved=True, automatic_retry=False)))
    except BaseException as exc:
        (state/'failed.json').write_text(json.dumps(dict(status='FAILED', error_type=type(exc).__name__, automatic_retry=False)))
        raise


if __name__ == '__main__':
    try:
        main(json.loads(Path(sys.argv[1]).read_bytes()))
    except BaseException:
        print('REQLOX_REVIEWED_RETURN_STOPPED', flush=True)
        raise SystemExit(1)
