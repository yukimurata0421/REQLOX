#!/usr/bin/env python3
"""Deploy one tested main commit to the existing dedicated REQLOX UI only."""
import argparse
import base64
import copy
import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def require(value, reason):
    if not value:
        raise ValueError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def load_configuration(path):
    value = json.loads(Path(path).read_bytes())
    fixed = dict(schema='reqlox.github-deployment.v1', repository='yukimurata0421/REQLOX',
                 project='reqlox', instance='reqlox-web', instance_id='3115344231848612081',
                 gateway='reqlox-web-gateway', zone='asia-northeast1-b', region='asia-northeast1',
                 origin='https://reqlox.yukimurata0421.dev', native_campaigns=15,
                 maximum_native_campaigns=15, charged_seconds=62, maximum_seconds=120)
    require(all(value.get(k) == v for k, v in fixed.items()), 'DEPLOYMENT_SCOPE_DRIFT')
    return value


def check_policy(policy):
    require(policy.get('mode') == 'OFFLINE_RECORDS_ONLY'
            and policy.get('cumulative_campaigns') == policy.get('maximum_campaigns') == 15
            and policy.get('charged_seconds') == 62 and policy.get('maximum_seconds') == 120
            and policy.get('remaining_campaigns') == 0
            and policy.get('native_execution_enabled') is False
            and policy.get('model_calls_enabled') is False
            and policy.get('source_fetch_enabled') is False, 'EXECUTION_POLICY_DRIFT')


def validate_host(vm, host, deployment, cfg):
    """Check the collector's declared paths before interpreting its documents."""
    unit = host['collector_unit']
    require(all(p in unit for p in ('/etc/codex-host-context/host.json',
        '/etc/codex-host-context/AGENTS.md', '/var/lib/reqlox-host-context/HOST_CONTEXT.generated.md')),
        'REMOTE_COLLECTOR_PATHS')
    require('BEGIN MANAGED: codex-host-contract-v1' in host['instructions'], 'REMOTE_MANAGED_BOUNDARY')
    contract = json.loads(host['contract'])
    context = json.loads(host['context'].split('```json\n')[1].split('\n```')[0])
    require(str(vm['id']) == host['physical_instance_id'] == cfg['instance_id']
            and vm['name'] == cfg['instance'] and vm['status'] == 'RUNNING'
            and context['boot_id'] == host['boot_id'], 'REMOTE_PHYSICAL_IDENTITY')
    require(contract['host_id'] == context['host_id'] == 'reqlox-web'
            and contract['project_id'] == context['project_id'] == 'reqlox'
            and contract['role'] == 'REQLOX bounded isolated demo', 'REMOTE_HOST_SCOPE')
    require(context['contract_sha256'] == digest(host['contract'].encode())
            and 0 <= (datetime.datetime.now(datetime.timezone.utc) -
                datetime.datetime.fromisoformat(context['generated_jst'])).total_seconds() < 600,
            'REMOTE_CONTEXT_STALE_OR_DRIFT')
    metadata = {row['key']: row['value'] for row in vm['metadata']['items']}
    runtime = json.loads(metadata['reqlox-runtime'])
    require(contract['release_sha256'] == context['release_sha256'] == runtime['release_sha256']
            == deployment['release_sha256'] == metadata['reqlox-release-sha256'], 'REMOTE_RELEASE_DRIFT')
    require(deployment['status'] == 'READY' and deployment['paid_model_calls_enabled'] is False
            and runtime['paid_model_calls_enabled'] is False and context['state_disk_mounted'] is True
            and all(v['ActiveState'] == 'active' for v in context['units'].values()), 'REMOTE_NOT_READY')
    require(runtime['artifact_bucket'] == cfg['releases_bucket']
            and runtime['web']['assets_bucket'] == cfg['assets_bucket']
            and runtime['web']['owner_secret_resource'] == cfg['owner_secret_version']
            and runtime['web']['public_origin'] == cfg['origin'], 'REMOTE_RUNTIME_SCOPE')
    return runtime


def rollout_config(vm, host, old, new, cfg):
    source = (ROOT / 'infra/gcp/runtime_rollout.py').read_bytes()
    web = (ROOT / 'infra/gcp/public_web/web_bootstrap.py').read_bytes()
    return dict(physical_instance_id=cfg['instance_id'], old_release_sha256=old['release_sha256'],
        new_release_sha256=new['release_sha256'],
        old_runtime_sha256=digest((json.dumps(old, sort_keys=True) + '\n').encode()),
        old_contract_sha256=digest(host['contract'].encode()),
        instructions_sha256=digest(host['instructions'].encode()),
        collector_unit_sha256=digest(host['collector_unit'].encode()),
        base_bootstrap_sha256=cfg['base_bootstrap_sha256'], rollout_method_sha256=digest(source),
        web_bootstrap_sha256=digest(web), web_bootstrap_base64=base64.b64encode(web).decode())


def startup_script(config):
    source = (ROOT / 'infra/gcp/runtime_rollout.py').read_bytes()
    require(digest(source) == config['rollout_method_sha256'], 'ROLLOUT_METHOD_DRIFT')
    rows = ['#!/bin/bash', 'set -euo pipefail', 'umask 077']
    for raw, path, mode in [(source, '/usr/local/libexec/reqlox-reviewed-rollout.py', '0755'),
            (json.dumps(config, sort_keys=True).encode(), '/etc/reqlox/reviewed-rollout.json', '0600')]:
        rows += ["printf '%s' " + base64.b64encode(raw).decode() + ' | base64 -d > ' + path,
                 'chmod ' + mode + ' ' + path]
    rows += ['timeout 600 python3 -B /usr/local/libexec/reqlox-reviewed-rollout.py /etc/reqlox/reviewed-rollout.json']
    return '\n'.join(rows) + '\n'


def rollback_config(host, old, failed, cfg, commit):
    source = ROOT/'infra/gcp/runtime_rollback.py'
    spec = importlib.util.spec_from_file_location('rollback_web_config', ROOT/'infra/gcp/public_web/web_bootstrap.py')
    web = importlib.util.module_from_spec(spec); spec.loader.exec_module(web)
    nginx = web.nginx_config(urllib.parse.urlsplit(cfg['origin']).hostname, cfg['assets_bucket'], True)
    return dict(request_id='git-'+commit+'-return', physical_instance_id=cfg['instance_id'],
        old_release_sha256=old['release_sha256'], failed_release_sha256=failed,
        rollback_method_sha256=digest(source.read_bytes()), base_bootstrap_sha256=cfg['base_bootstrap_sha256'],
        collector_unit_sha256=digest(host['collector_unit'].encode()),
        instructions_sha256=digest(host['instructions'].encode()),
        old_contract_sha256=digest(host['contract'].encode()),
        old_runtime_sha256=digest((json.dumps(old, sort_keys=True)+'\n').encode()),
        new_nginx_sha256=digest(nginx.encode()),
        new_web_bootstrap_sha256=digest((ROOT/'infra/gcp/public_web/web_bootstrap.py').read_bytes()))


def rollback_startup_script(config):
    source = (ROOT/'infra/gcp/runtime_rollback.py').read_bytes()
    require(digest(source) == config['rollback_method_sha256'], 'ROLLBACK_METHOD_DRIFT')
    rows = ['#!/bin/bash', 'set -euo pipefail', 'umask 077']
    for raw, path, mode in [(source, '/usr/local/libexec/reqlox-reviewed-return.py', '0755'),
            (json.dumps(config, sort_keys=True).encode(), '/etc/reqlox/reviewed-return.json', '0600')]:
        rows += ["printf '%s' " + base64.b64encode(raw).decode() + ' | base64 -d > ' + path, 'chmod '+mode+' '+path]
    rows += ['timeout 300 python3 -B /usr/local/libexec/reqlox-reviewed-return.py /etc/reqlox/reviewed-return.json']
    return '\n'.join(rows)+'\n'


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Cloud:
    """No automatic mutation retry; authentication material stays in memory."""
    def __init__(self, cfg):
        self.cfg = cfg
        self.opener = urllib.request.build_opener(NoRedirect)

    def command(self, arguments, *, seconds=600):
        result = subprocess.run(['gcloud', *arguments, '--project='+self.cfg['project'],
            '--format=json', '--quiet'], capture_output=True, timeout=seconds)
        require(result.returncode == 0, 'GCLOUD_OPERATION_REJECTED')
        return json.loads(result.stdout or b'{}')

    def api(self, url, method='GET', value=None, raw=None, kind='application/json'):
        token = subprocess.check_output(['gcloud', 'auth', 'print-access-token'], timeout=30).strip().decode()
        body = raw if raw is not None else None if value is None else json.dumps(value).encode()
        request = urllib.request.Request(url, data=body, method=method,
            headers={'Authorization': 'Bearer '+token, 'Content-Type': kind})
        try:
            with self.opener.open(request, timeout=60) as response:
                data = response.read(4*1024*1024+1)
                require(len(data) <= 4*1024*1024, 'CLOUD_RESPONSE_BOUND')
                return json.loads(data)
        except urllib.error.HTTPError as exc:
            raise ValueError('CLOUD_HTTP_'+str(exc.code)) from None

    def upload(self, bucket, name, raw, kind):
        query = urllib.parse.urlencode(dict(uploadType='media', name=name, ifGenerationMatch=0))
        result = self.api('https://storage.googleapis.com/upload/storage/v1/b/'+bucket+'/o?'+query,
                          'POST', raw=raw, kind=kind)
        require(result['name'] == name and int(result['size']) == len(raw), 'UPLOAD_RECEIPT_DRIFT')
        return dict(name=name, generation=result['generation'], sha256=digest(raw))

    def poll(self, operation, seconds=180):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            value = self.api(operation['selfLink'])
            if value.get('status') == 'DONE':
                require('error' not in value, 'COMPUTE_OPERATION_FAILED')
                return
            time.sleep(3)
        raise TimeoutError('COMPUTE_OBSERVATION_DEADLINE')


class Deployment:
    def __init__(self, cfg, commit, bundle, output, cloud=None):
        self.cfg, self.commit, self.bundle, self.output = cfg, commit, Path(bundle), Path(output)
        self.cloud = cloud or Cloud(cfg)
        self.vm_url = ('https://compute.googleapis.com/compute/v1/projects/'+cfg['project']+
            '/zones/'+cfg['zone']+'/instances/'+cfg['instance'])
        self.authorization = None
        self.vm_changed = False
        self.gateway_changed = False
        self.result = dict(schema='reqlox.ci-deployment-result.v1', commit=commit, status='OPEN',
            new_native_campaigns=0, new_model_calls=0, cumulative_campaigns=15, charged_seconds=62,
            automatic_retry=False, state_disk_preserved=True)

    def save(self):
        self.output.mkdir(mode=0o700, parents=True, exist_ok=True)
        (self.output/'result.json').write_text(json.dumps(self.result, indent=2)+'\n')

    def public(self, path, *, base=None, headers=None, value=None, authenticate=True):
        origin = base or self.cfg['origin']
        require(origin == self.cfg['origin'] or (origin.startswith('https://') and
            urllib.parse.urlsplit(origin).hostname.endswith('.run.app')), 'UNTRUSTED_VERIFICATION_ORIGIN')
        actual = {'User-Agent': 'Mozilla/5.0', **(headers or {})}
        if authenticate:
            actual['Authorization'] = self.authorization
        data = None if value is None else json.dumps(value).encode()
        if data is not None:
            actual['Content-Type'] = 'application/json'
        request = urllib.request.Request(origin+path, data=data, headers=actual)
        try:
            with self.cloud.opener.open(request, timeout=30) as response:
                self.last_public_response_headers = {k.lower(): v for k, v in response.headers.items()
                    if k.lower() in ('cache-control', 'content-type', 'server', 'cf-ray', 'cf-cache-status')}
                raw = response.read(1024*1024+1)
                require(len(raw) <= 1024*1024, 'PUBLIC_RESPONSE_BOUND')
                return response.status, raw
        except urllib.error.HTTPError as exc:
            self.last_public_response_headers = {k.lower(): v for k, v in exc.headers.items()
                if k.lower() in ('cache-control', 'content-type', 'server', 'cf-ray', 'cf-cache-status')}
            return exc.code, exc.read(1024*1024)

    def public_json(self, path, **kwargs):
        status, raw = self.public(path, **kwargs)
        require(status == 200, 'PUBLIC_HTTP_'+str(status))
        return json.loads(raw)

    def observe(self, base=None):
        config = self.public_json('/api/config', base=base)
        host = self.public_json('/api/host-context', base=base, headers={'X-REQLOX-Token': config['token']})
        deployment = self.public_json('/api/deployment', base=base)
        workspace = self.public_json('/api/workspace/config', base=base)
        check_policy(workspace['execution_policy'])
        return host, deployment, workspace

    def gateway(self):
        return self.cloud.command(['run', 'services', 'describe', self.cfg['gateway'],
                                   '--region='+self.cfg['region']], seconds=30)

    def build_gateway(self):
        image = self.cfg['region']+'-docker.pkg.dev/'+self.cfg['project']+'/reqlox-web/gateway:git-'+self.commit
        build = dict(steps=[dict(name='gcr.io/cloud-builders/docker', args=['build',
            '--build-arg', 'PYTHON_IMAGE='+self.cfg['gateway_base_image'], '-t', image, '.'])],
            images=[image], timeout='600s', options=dict(logging='CLOUD_LOGGING_ONLY'),
            serviceAccount='projects/'+self.cfg['project']+'/serviceAccounts/'+self.cfg['build_service_account'])
        file = self.output/'build.json'
        file.write_text(json.dumps(build))
        value = self.cloud.command(['builds', 'submit', str(ROOT/'infra/gcp/public_web/gateway'),
            '--config='+str(file), '--region='+self.cfg['region'],
            '--gcs-source-staging-dir=gs://'+self.cfg['build_bucket']+'/cicd/'+self.commit,
            '--async'], seconds=90)
        build_url = ('https://cloudbuild.googleapis.com/v1/projects/'+self.cfg['project']+
            '/locations/'+self.cfg['region']+'/builds/'+value['id'])
        deadline = time.monotonic()+660
        while value.get('status') in ('QUEUED','PENDING','WORKING') and time.monotonic() < deadline:
            time.sleep(5)
            value = self.cloud.api(build_url)
        require(value.get('status') == 'SUCCESS', 'GATEWAY_BUILD_FAILED')
        images = value['results']['images']
        require(len(images) == 1 and images[0]['name'] == image, 'GATEWAY_IMAGE_BINDING')
        self.result['build_id'] = value['id']
        return image.split(':git-')[0]+'@'+images[0]['digest']

    def verify(self, base, expected, host_before, history_before):
        host, deployment, workspace = self.observe(base)
        vm = self.cloud.api(self.vm_url)
        validate_host(vm, host, deployment, self.cfg)
        require(deployment['release_sha256'] == expected, 'DEPLOYED_RELEASE_DRIFT')
        require(host['instructions'] == host_before['instructions']
            and host['collector_unit'] == host_before['collector_unit']
            and json.loads(host['contract']) == dict(json.loads(host_before['contract']), release_sha256=expected),
            'UNREVIEWED_REMOTE_CONTRACT_CHANGE')
        require(workspace['history'] == history_before, 'PRIVATE_HISTORY_DRIFT')
        config = self.public_json('/api/config', base=base)
        checked = []
        for path in ('/api/run', '/api/targets/run', '/api/study/compare-run'):
            status, raw = self.public(path, base=base, value={}, headers={
                'X-REQLOX-Token': config['token'], 'Origin': self.cfg['origin']})
            require(status == 403 and json.loads(raw)['error'] == 'UI_EXECUTION_DISABLED', 'EXECUTION_STOP_DRIFT')
            checked.append(path)
        require(self.public('/api/config', base=base, authenticate=False)[0] == 401, 'ANONYMOUS_ACCESS_DRIFT')
        require(self.public('/api/config', base=base, headers={'Origin':'https://wrong.example'})[0] == 403,
                'ORIGIN_ACCESS_DRIFT')
        self.result.update(execution_stop_checked=checked, private_history_records=len(history_before),
                           private_history_preserved=True, anonymous_status=401, wrong_origin_status=403)

    def wait_ready(self, base, expected, seconds=240):
        """Poll read-only readiness; never repeat a deployment mutation."""
        deadline = time.monotonic()+seconds
        while time.monotonic() < deadline:
            try:
                status, raw = self.public('/api/deployment', base=base)
                if status == 200:
                    value = json.loads(raw)
                    if value.get('status') == 'READY' and value.get('release_sha256') == expected:
                        return
                else:
                    require(status in (502,503,504), 'READINESS_HTTP_'+str(status))
            except (TimeoutError, urllib.error.URLError):
                pass
            time.sleep(4)
        raise TimeoutError('UI_READINESS_DEADLINE')

    def verify_public_demo(self, base, assets):
        from cloud_web_assets import PUBLIC_ROUTES as ROUTES
        rows = {r['name']: r for r in assets['files']}
        for route, name in ROUTES.items():
            status, raw = self.public(route, base=base, authenticate=False)
            self.result.setdefault('public_asset_checks', []).append(dict(
                phase='staged' if base else 'origin', route=route, status=status,
                bytes=len(raw), observed_sha256=digest(raw), expected_sha256=rows[name]['sha256'],
                headers=dict(getattr(self, 'last_public_response_headers', {})),
                analytics_markup_seen=b'static.cloudflareinsights.com/beacon.min.js' in raw))
            require(status == 200 and digest(raw) == rows[name]['sha256'], 'READONLY_DEMO_ASSET_DRIFT')
        require(self.public('/api/workspace/config', base=base, authenticate=False)[0] == 401,
                'READONLY_DEMO_PRIVATE_API_EXPOSED')
        require(self.public('/demo/api/workspace/config', base=base, authenticate=False)[0] == 404,
                'READONLY_DEMO_ROUTE_ESCAPE')
        require(self.public('/demo/public-demo.json', base=base, authenticate=False, value={})[0] == 405,
                'READONLY_DEMO_WRITE_EXPOSED')
        self.result['anonymous_demo_verified'] = True

    def restore(self, before_vm, old_revision, host_before, history_before):
        """One explicit rollback; preserve the failed release and all state."""
        self.result['rollback'] = 'STARTED'
        self.save()
        current = self.cloud.api(self.vm_url)
        require(current['id'] == before_vm['id'] and current['serviceAccounts'] == before_vm['serviceAccounts']
            and current['scheduling'] == before_vm['scheduling']
            and [d['source'] for d in current['disks']] == [d['source'] for d in before_vm['disks']],
            'ROLLBACK_IDENTITY_DRIFT')
        items = {r['key']:r['value'] for r in before_vm['metadata']['items']}
        old = json.loads(items['reqlox-runtime'])
        current_items = {r['key']:r['value'] for r in current['metadata']['items']}
        failed = json.loads(current_items['reqlox-runtime'])['release_sha256']
        config = rollback_config(host_before, old, failed, self.cfg, self.commit)
        self.cloud.upload(self.cfg['releases_bucket'], 'returns/'+self.commit+'.json',
                          json.dumps(config, sort_keys=True).encode(), 'application/json')
        items['startup-script'] = rollback_startup_script(config)
        self.result['rollback_method_sha256'] = config['rollback_method_sha256']
        self.cloud.poll(self.cloud.api(self.vm_url+'/setMetadata', 'POST', dict(
            fingerprint=current['metadata']['fingerprint'], items=[dict(key=k,value=v) for k,v in items.items()])))
        if current['status'] != 'TERMINATED':
            self.cloud.poll(self.cloud.api(self.vm_url+'/stop', 'POST', {}))
        self.cloud.poll(self.cloud.api(self.vm_url+'/start', 'POST', {}))
        if self.gateway_changed:
            self.cloud.command(['run', 'services', 'update-traffic', self.cfg['gateway'],
                '--region='+self.cfg['region'], '--to-revisions='+old_revision+'=100', '--clear-tags'])
        old_release = json.loads(next(r['value'] for r in before_vm['metadata']['items']
            if r['key'] == 'reqlox-runtime'))['release_sha256']
        self.wait_ready(None, old_release)
        self.verify(None, old_release, host_before, history_before)
        self.result['rollback'] = 'RESTORED_AND_HTTP_VERIFIED'

    def run(self):
        require(re.fullmatch('[a-f0-9]{40}', self.commit), 'COMMIT_IDENTITY')
        require(os.environ.get('GITHUB_REPOSITORY') == self.cfg['repository']
            and os.environ.get('GITHUB_REF') == 'refs/heads/main'
            and os.environ.get('GITHUB_EVENT_NAME') == 'push'
            and os.environ.get('GITHUB_SHA') == self.commit
            and os.environ.get('GITHUB_RUN_ATTEMPT') == '1', 'UNAUTHORIZED_WORKFLOW_CONTEXT')
        self.save()
        archive = self.bundle/'release/cloud-release.tar.gz'
        release = digest(archive.read_bytes())
        require(archive.stat().st_size <= 128*1024*1024, 'RELEASE_SIZE_BOUND')
        self.result['release_sha256'] = release
        password = base64.b64decode(self.cloud.api('https://secretmanager.googleapis.com/v1/'+
            self.cfg['owner_secret_version']+':access')['payload']['data'])
        self.authorization = 'Basic '+base64.b64encode(b'reqlox:'+password).decode()
        password = None
        before_vm = self.cloud.api(self.vm_url)
        host, deployment, workspace = self.observe()
        old = validate_host(before_vm, host, deployment, self.cfg)
        require(old['release_sha256'] != release, 'RELEASE_ALREADY_INSTALLED')
        before_gateway = self.gateway()
        traffic = [r for r in before_gateway['status']['traffic'] if r.get('percent')]
        require(len(traffic) == 1 and traffic[0]['percent'] == 100, 'GATEWAY_TRAFFIC_DRIFT')
        old_revision = traffic[0]['revisionName']
        # Immutable admission rejects a second deployment of the same commit.
        self.cloud.upload(self.cfg['releases_bucket'], 'deployments/'+self.commit+'.json',
            json.dumps(dict(commit=self.commit, release_sha256=release, old_release=old['release_sha256'],
                instance_id=self.cfg['instance_id'], new_native_campaigns=0, new_model_calls=0)).encode(),
            'application/json')
        image = self.build_gateway()
        self.cloud.upload(self.cfg['releases_bucket'], 'releases/'+release+'.tar.gz', archive.read_bytes(), 'application/gzip')
        assets = json.loads((self.bundle/'assets.json').read_bytes())
        from cloud_web_assets import FILES
        require({r['name'] for r in assets['files']} == set(FILES), 'ASSET_ALLOWLIST_DRIFT')
        for row in assets['files']:
            raw = (self.bundle/'assets'/row['name']).read_bytes()
            require(len(raw) == row['bytes'] and digest(raw) == row['sha256'], 'ASSET_HASH_DRIFT')
            import mimetypes
            self.cloud.upload(self.cfg['assets_bucket'], 'releases/'+self.commit+'/'+row['name'], raw,
                              mimetypes.guess_type(row['name'])[0] or 'application/octet-stream')
        new = dict(old, release_sha256=release, artifact_object='releases/'+release+'.tar.gz')
        startup = startup_script(rollout_config(before_vm, host, old, new, self.cfg))
        current = self.cloud.api(self.vm_url)
        require(current['metadata'] == before_vm['metadata'] and current['scheduling'] == before_vm['scheduling']
            and current['id'] == before_vm['id'], 'VM_CHANGED_BEFORE_CUTOVER')
        items = {r['key']:r['value'] for r in current['metadata']['items']}
        items.update({'reqlox-runtime':json.dumps(new, sort_keys=True), 'reqlox-release-sha256':release,
                      'startup-script':startup, 'reqlox-source-commit':self.commit})
        try:
            self.vm_changed = True
            self.cloud.poll(self.cloud.api(self.vm_url+'/setMetadata', 'POST', dict(
                fingerprint=current['metadata']['fingerprint'], items=[dict(key=k,value=v) for k,v in items.items()])))
            self.cloud.poll(self.cloud.api(self.vm_url+'/stop', 'POST', {}))
            self.cloud.poll(self.cloud.api(self.vm_url+'/start', 'POST', {}))
            tag = 'git-'+self.commit[:12]
            self.gateway_changed = True
            self.cloud.command(['run', 'deploy', self.cfg['gateway'], '--region='+self.cfg['region'],
                '--image='+image, '--no-traffic', '--tag='+tag,
                '--update-env-vars=RELEASE_SHA256='+release+',ASSET_PREFIX=releases/'+self.commit+'/'], seconds=600)
            candidate = self.gateway()
            staged = [r for r in candidate['status']['traffic'] if r.get('tag') == tag]
            require(len(staged) == 1 and staged[0].get('percent',0) == 0, 'CANDIDATE_TRAFFIC_BINDING')
            self.wait_ready(staged[0]['url'], release)
            self.verify(staged[0]['url'], release, host, workspace['history'])
            self.verify_public_demo(staged[0]['url'], assets)
            current = self.cloud.api(self.vm_url)
            require(current['serviceAccounts'] == before_vm['serviceAccounts']
                and current['scheduling'] == before_vm['scheduling']
                and [d['source'] for d in current['disks']] == [d['source'] for d in before_vm['disks']],
                'VM_BOUNDARY_DRIFT')
            revision = staged[0]['revisionName']
            self.cloud.command(['run','services','update-traffic',self.cfg['gateway'],
                '--region='+self.cfg['region'], '--to-revisions='+revision+'=100', '--clear-tags'])
            self.verify(None, release, host, workspace['history'])
            self.verify_public_demo(None, assets)
            for row in assets['files']:
                route = {'index.html':'/','study.html':'/study','knowledge.html':'/knowledge',
                         'targets.html':'/targets','records.html':'/records',
                         'public-demo.html':'/demo/','public-demo.js':'/demo/public-demo.js',
                         'public-demo.css':'/demo/public-demo.css','public-demo.json':'/demo/public-demo.json'}.get(row['name'],'/'+row['name'])
                status, raw = self.public(route)
                require(status == 200, 'PUBLIC_ASSET_UNAVAILABLE')
                if not row['name'].endswith('.html'):
                    require(digest(raw) == row['sha256'], 'PUBLIC_ASSET_HASH_DRIFT')
            self.result.update(status='DEPLOYED_AND_HTTP_VERIFIED', gateway_revision=revision,
                gateway_image=image, browser_assets=len(assets['files']), state_disk_preserved=True)
        except BaseException:
            self.result['status'] = 'FAILED'
            self.save()
            if self.vm_changed:
                try:
                    self.restore(before_vm, old_revision, host, workspace['history'])
                except BaseException as rollback_error:
                    self.result['rollback'] = 'OUTCOME_UNKNOWN_STOP_NO_RETRY'
                    self.result['rollback_error_type'] = type(rollback_error).__name__
                    self.result['rollback_reason'] = str(rollback_error)[:500]
            raise
        finally:
            self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--commit', required=True)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    job = Deployment(load_configuration(ROOT/'infra/gcp/cicd.json'), args.commit, args.bundle, args.output)
    try:
        job.run()
    except Exception as exc:
        job.result.update(status='FAILED', error_type=type(exc).__name__)
        if isinstance(exc, ValueError) and re.fullmatch('[A-Z0-9_]+', str(exc)):
            job.result['reason'] = str(exc)
        job.save()
        raise SystemExit('Deployment stopped; retained result.json describes the bounded outcome.') from None
    print(json.dumps(job.result))


if __name__ == '__main__':
    main()
