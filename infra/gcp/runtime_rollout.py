#!/usr/bin/env python3
"""Apply one reviewed release on the same dedicated demo VM at boot.

No disks, accounts, firewall, IAM or credential versions are changed. An
interrupted or failed attempt is retained and cannot become an implicit retry.
"""
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile


def require(condition, reason):
    if not condition: raise ValueError(reason)


def protected(path):
    p = Path(path); s = p.stat()
    require(not p.is_symlink() and s.st_uid == 0 and not s.st_mode & 0o022, 'Protected source differs')
    require(s.st_size <= 1048576, 'Protected source size')
    return p.read_bytes()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def atomic(path, raw, mode=0o644):
    p = Path(path); require(not p.is_symlink(), 'Managed file link')
    temporary = p.with_name(p.name + '.reviewed-new')
    with temporary.open('xb') as stream:
        os.fchmod(stream.fileno(), mode); stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, p)


def command(*args):
    subprocess.run(args, check=True, timeout=300)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def validate_change(old, new, old_contract, expected):
    require(old['host_id'] == new['host_id'] == old_contract['host_id'] == 'reqlox-web'
            and old['project_id'] == new['project_id'] == old_contract['project_id'] == 'reqlox', 'Scope differs')
    require(old_contract['role'] == 'REQLOX bounded isolated demo', 'Production hosts are outside this rollout')
    require(old['release_sha256'] == old_contract['release_sha256'] == expected['old_release_sha256']
            and new['release_sha256'] == expected['new_release_sha256'], 'Release differs')
    require({k:v for k,v in old.items() if k not in ('release_sha256', 'artifact_object')} ==
            {k:v for k,v in new.items() if k not in ('release_sha256', 'artifact_object')}, 'Runtime boundary changed')
    require(new['artifact_object'] == 'releases/' + new['release_sha256'] + '.tar.gz'
            and new['paid_model_calls_enabled'] is False and new['access'] == 'CLOUDFLARE_OWNER_LOGIN'
            and new['web']['authentication'] == 'OWNER_BASIC_AUTH', 'Runtime authority changed')
    return dict(old_contract, release_sha256=new['release_sha256'])


def main(config):
    require(os.getuid() == 0 and sys.version_info[:2] == (3, 11), 'Startup identity differs')
    require(sha(protected(__file__)) == config['rollout_method_sha256'], 'Reviewed rollout method differs')
    # Release code must be traversable by the service account. Private state and
    # backups below keep explicit 0700/0600 modes independently of this umask.
    os.umask(0o022)
    require(sha(protected('/usr/local/libexec/reqlox-base-bootstrap.py')) == config['base_bootstrap_sha256'],
            'Installed bootstrap source differs')
    base = load_module('reviewed_base', '/usr/local/libexec/reqlox-base-bootstrap.py')
    require(base.metadata('instance/id').decode().strip() == config['physical_instance_id']
            and base.metadata('instance/name').decode().strip() == 'reqlox-web'
            and base.metadata('project/project-id').decode().strip() == 'reqlox', 'Physical identity differs')
    unit = protected('/etc/systemd/system/codex-host-context-refresh.service')
    require(sha(unit) == config['collector_unit_sha256'], 'Collector differs')
    paths = ('/etc/codex-host-context/host.json', '/etc/codex-host-context/AGENTS.md',
             '/var/lib/reqlox-host-context/HOST_CONTEXT.generated.md')
    require(all(p.encode() in unit for p in paths), 'Collector paths differ')
    instructions = protected(paths[1]); require(sha(instructions) == config['instructions_sha256']
        and b'BEGIN MANAGED: codex-host-contract-v1' in instructions, 'Instructions differ')
    runtime_path = Path('/etc/reqlox/runtime.json'); contract_path = Path(paths[0])
    old_bytes = protected(runtime_path); old = json.loads(old_bytes)
    contract_bytes = protected(contract_path); contract = json.loads(contract_bytes)
    new = json.loads(base.metadata('instance/attributes/reqlox-runtime'))
    state = Path('/var/lib/reqlox-reviewed-rollouts') / config['new_release_sha256']
    if old['release_sha256'] == config['new_release_sha256']:
        # A later ordinary boot may reload credentials only after a completed rollout.
        require((state/'ready.json').is_file() and contract['release_sha256'] == old['release_sha256'],
                'Unconfirmed previous attempt; no automatic retry')
        load_module('reviewed_web', '/usr/local/libexec/reqlox-web-bootstrap.py').main()
        return
    require(sha(old_bytes) == config['old_runtime_sha256'] and sha(contract_bytes) == config['old_contract_sha256'],
            'Current protected binding differs')
    replacement = validate_change(old, new, contract, config)
    pointer = Path('/opt/reqlox/site'); old_site = pointer.resolve()
    require(pointer.is_symlink() and str(old_site) == '/opt/reqlox/releases/' + config['old_release_sha256'] + '/site',
            'Current site pointer differs')
    require(not state.exists(), 'Rollout already attempted; no automatic retry')
    state.mkdir(mode=0o700, parents=True)
    (state/'started.json').write_text(json.dumps(dict(status='OPEN', automatic_retry=False)))
    backup = state/'before'; backup.mkdir(mode=0o700)
    names = (str(runtime_path), str(contract_path), paths[1], '/etc/nginx/nginx.conf',
             '/usr/local/libexec/reqlox-web-bootstrap.py')
    for index, name in enumerate(names):
        data = protected(name); out = backup/str(index); out.write_bytes(data); out.chmod(0o600)
    (backup/'manifest.json').write_text(json.dumps(dict(sha256=[sha(protected(backup/str(i)))
        for i in range(len(names))])))
    (backup/'site-pointer').write_text(str(old_site))
    cutover = False
    try:
        token = json.loads(base.metadata('instance/service-accounts/default/token'))['access_token']
        raw = base.cloud_get('https://storage.googleapis.com/' + new['artifact_bucket'] + '/' + new['artifact_object'], token)
        require(sha(raw) == config['new_release_sha256'], 'New archive differs')
        root = Path('/opt/reqlox/releases') / config['new_release_sha256']
        require(not root.exists(), 'New release directory is not empty')
        root.mkdir(); archive = root/'release.tar.gz'; archive.write_bytes(raw)
        manifest = base.extract_release(archive, root)
        require(manifest.get('rollout_method_sha256') == config['rollout_method_sha256'],
                'Archive does not bind this reviewed deployment method')
        command('/usr/bin/python3', '-m', 'venv', str(root/'installer'))
        command(str(root/'installer/bin/python'), '-m', 'pip', 'install', '--no-index', '--no-compile',
                '--require-hashes', '--find-links', str(root/'wheelhouse'), '--target', str(root/'site'),
                '-r', str(root/'requirements.txt'))
        # Compare installed application bytes without importing new runtime code.
        wheels = list((root/'wheelhouse').glob('reqlox-*.whl'))
        require(len(wheels) == 1, 'Application wheel identity')
        with zipfile.ZipFile(wheels[0]) as wheel:
            for member in wheel.namelist():
                if member.endswith('/RECORD'): continue  # pip records installed entry points.
                require(not member.startswith('/') and '..' not in member.split('/')
                        and sha((root/'site'/member).read_bytes()) == sha(wheel.read(member)),
                        'Installed application bytes differ')
        command('systemctl', 'stop', 'reqlox.service'); cutover = True
        atomic(runtime_path, (json.dumps(new, sort_keys=True)+'\n').encode())
        atomic(contract_path, (json.dumps(replacement, sort_keys=True)+'\n').encode())
        temporary = pointer.with_name('site.reviewed-new'); temporary.symlink_to(root/'site'); os.replace(temporary, pointer)
        web_bytes = base64.b64decode(config['web_bootstrap_base64'], validate=True)
        require(sha(web_bytes) == config['web_bootstrap_sha256'], 'Reviewed web bootstrap differs')
        atomic('/usr/local/libexec/reqlox-web-bootstrap.py', web_bytes, 0o755)
        web = load_module('reviewed_web', '/usr/local/libexec/reqlox-web-bootstrap.py')
        web.main()
        require(json.loads(protected(contract_path)) == replacement and protected(paths[1]) == instructions,
                'Unreviewed contract fields or instructions changed')
        (state/'ready.json').write_text(json.dumps(dict(status='READY', release_sha256=new['release_sha256'],
              physical_instance_id=config['physical_instance_id'], paid_model_calls_enabled=False,
              private_state_preserved=True, automatic_retry=False)))
        print('REQLOX_REVIEWED_ROLLOUT_READY', flush=True)
    except BaseException as exc:
        (state/'failed.json').write_text(json.dumps(dict(status='FAILED', error_type=type(exc).__name__,
              cutover_started=cutover, automatic_retry=False)))
        if cutover:
            command('systemctl', 'stop', 'reqlox.service')
            for index, name in enumerate(names): atomic(name, (backup/str(index)).read_bytes(), 0o755 if name.endswith('.py') else 0o644)
            temporary = pointer.with_name('site.reviewed-old'); temporary.symlink_to(old_site); os.replace(temporary, pointer)
            command('systemctl', 'start', 'reqlox.service')
            command('nginx', '-t'); command('systemctl', 'reload', 'nginx.service')
            command('systemctl', 'start', 'codex-host-context-refresh.service')
        raise


if __name__ == '__main__':
    try:
        main(json.loads(Path(sys.argv[1]).read_bytes()))
    except BaseException:
        print('REQLOX_REVIEWED_ROLLOUT_STOPPED', flush=True)
        raise SystemExit(1)
