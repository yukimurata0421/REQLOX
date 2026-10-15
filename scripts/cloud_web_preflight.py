#!/usr/bin/env python3
"""Reject unbound replacement, broad ingress, or private-data publication."""
import argparse
import hashlib
import json
from pathlib import Path


def validate(plan, project, domain, replace_instance_id=None):
    variables = {k: v["value"] for k,v in plan["variables"].items()}
    if variables.get("project_id") != project or variables.get("name") != "reqlox-web" or variables.get("domain") != domain:
        raise ValueError("Web plan identity differs")
    prefix="reqlox-web"
    assets=project+"-"+prefix+"-assets"
    runtime="serviceAccount:"+prefix+"-runtime@"+project+".iam.gserviceaccount.com"
    allowed={"google_service_account","google_compute_network","google_compute_subnetwork","google_compute_firewall",
             "google_storage_bucket","google_storage_bucket_object","google_storage_bucket_iam_member",
             "google_secret_manager_secret","google_secret_manager_secret_iam_member","google_compute_disk",
             "google_compute_instance","google_iap_tunnel_instance_iam_member","google_project_service",
             "google_artifact_registry_repository","google_artifact_registry_repository_iam_member",
             "google_project_iam_member","google_cloud_run_v2_service","google_cloud_run_v2_service_iam_member"}
    digest=hashlib.sha256(Path(variables['release_archive']).read_bytes()).hexdigest()
    files={"index.html","study.html","knowledge.html","app.js","study.js","knowledge.js","style.css","targets.html","targets.js","targets.css"}
    changes=[]
    replacements=[]
    for resource in plan.get('resource_changes',[]):
        change=resource['change'];after=change.get('after') or {};kind=resource['type']
        if change['actions'] in (['no-op'],['read']):continue
        replacement = change['actions'] == ['delete','create']
        before = change.get('before') or {}
        if replacement:
            if not replace_instance_id or not str(replace_instance_id).isdigit():raise ValueError('Replacement requires an observed physical instance identity')
            if kind=='google_compute_instance':
                if resource['address']!='google_compute_instance.web[0]' or str(before.get('instance_id'))!=str(replace_instance_id) or before.get('name')!=prefix or before.get('zone')!=variables['zone']:
                    raise ValueError('Replacement does not match the observed failed Web VM')
            elif kind=='google_iap_tunnel_instance_iam_member':
                instance = before.get('instance','')
                expected = 'projects/'+project+'/iap_tunnel/zones/'+variables['zone']+'/instances/'+prefix
                conditions = lambda value: [{k: (v or '') for k, v in item.items()} for item in value.get('condition', [])]
                if instance not in (prefix, expected) or before.get('member')!=after.get('member') or before.get('role')!=after.get('role') or conditions(before)!=conditions(after):
                    raise ValueError('IAP replacement changes authorization')
            else:raise ValueError('Only the observed VM and its existing IAP grant may be replaced')
            replacements.append(resource['address'])
        if resource.get('mode')!='managed' or kind not in allowed or (change['actions']!=['create'] and not replacement):
            raise ValueError('The Web deployment may only create new scoped resources')
        if after.get('project') not in (None,project):raise ValueError('Cross-project change')
        if kind in {'google_compute_instance','google_compute_disk','google_compute_firewall','google_compute_network','google_compute_subnetwork','google_service_account'}:
            name=after.get('name') or after.get('account_id')
            if not name or not name.startswith(prefix):raise ValueError('Unowned resource')
        if kind=='google_storage_bucket' and after.get('name') not in (assets,project+'-reqlox-web-buildsource'):raise ValueError('Only the dedicated Web buckets are allowed')
        if kind=='google_storage_bucket' and after.get('name')!=assets and after.get('public_access_prevention')!='enforced':raise ValueError('Build sources must remain private')
        if kind=='google_storage_bucket_object':
            if after.get('bucket')==assets:
                if after.get('name') not in files:raise ValueError('Non-UI object would be published')
            elif after.get('bucket')==variables['release_bucket']:
                if after.get('name')!='releases/'+digest+'.tar.gz':raise ValueError('Unbound private release object')
            else:raise ValueError('Unexpected object destination')
        if kind=='google_storage_bucket_iam_member':
            public=after.get('bucket')==assets and after.get('member')=='allUsers'
            private=after.get('bucket')==variables['release_bucket'] and after.get('member')==runtime
            build=after.get('bucket')==project+'-reqlox-web-buildsource' and after.get('member')=='serviceAccount:reqlox-web-build@'+project+'.iam.gserviceaccount.com'
            if after.get('role')!='roles/storage.objectViewer' or not (public or private or build):raise ValueError('Unscoped storage IAM')
        if kind=='google_secret_manager_secret' and after.get('secret_id') not in {'reqlox-web-owner-login','reqlox-web-tunnel-token'}:
            raise ValueError('Unscoped secret')
        if kind=='google_secret_manager_secret_iam_member':
            backend=after.get('member')==runtime and after.get('secret_id') in {'reqlox-web-owner-login','reqlox-web-tunnel-token','reqlox-jev-api-key'}
            gateway=after.get('member')=='serviceAccount:reqlox-web-gateway@'+project+'.iam.gserviceaccount.com' and after.get('secret_id')=='reqlox-web-owner-login'
            if after.get('role')!='roles/secretmanager.secretAccessor' or not (backend or gateway):
                raise ValueError('Unscoped secret access')
        if kind=='google_compute_firewall':
            iap=after.get('source_ranges')==['35.235.240.0/20'] and after.get('allow')==[{'ports':['8080'],'protocol':'tcp'}]
            gateway=after.get('name')=='reqlox-web-gateway' and after.get('source_ranges')==['10.83.1.0/26'] and after.get('target_service_accounts')==['reqlox-web-runtime@'+project+'.iam.gserviceaccount.com'] and after.get('allow')==[{'ports':['8081'],'protocol':'tcp'}]
            if not (iap or gateway):raise ValueError('Public VM ingress is forbidden')
        if kind=='google_project_service' and after.get('service') not in {'run.googleapis.com','artifactregistry.googleapis.com','cloudbuild.googleapis.com'}:raise ValueError('Unexpected service enablement')
        if kind=='google_project_iam_member' and (after.get('role')!='roles/logging.logWriter' or after.get('member')!='serviceAccount:reqlox-web-build@'+project+'.iam.gserviceaccount.com'):raise ValueError('Unscoped project IAM')
        if kind=='google_artifact_registry_repository' and after.get('repository_id')!='reqlox-web':raise ValueError('Unscoped image repository')
        if kind=='google_artifact_registry_repository_iam_member' and (after.get('role')!='roles/artifactregistry.writer' or after.get('member')!='serviceAccount:reqlox-web-build@'+project+'.iam.gserviceaccount.com'):raise ValueError('Unscoped build writer')
        if kind=='google_cloud_run_v2_service':
            template=after['template'][0]
            if after.get('name')!='reqlox-web-gateway' or template['scaling'][0]['max_instance_count']!=1 or template['scaling'][0]['min_instance_count']!=0 or template['service_account']!='reqlox-web-gateway@'+project+'.iam.gserviceaccount.com':raise ValueError('Unbounded gateway service')
            if template['containers'][0]['image']!=variables['gateway_image']:raise ValueError('Gateway image differs from the pinned digest')
        if kind=='google_cloud_run_v2_service_iam_member' and (after.get('name')!='reqlox-web-gateway' or after.get('role')!='roles/run.invoker' or after.get('member')!='allUsers'):raise ValueError('Unscoped public gateway invocation')
        if kind=='google_compute_instance':
            scheduling=after['scheduling'][0]
            if (after['machine_type']!='e2-medium' or scheduling['instance_termination_action']!='STOP'
                    or scheduling['max_run_duration'][0]['seconds']>86400 or scheduling['automatic_restart'] is not False):
                raise ValueError('Missing finite VM allocation')
            runtime_config=json.loads(after['metadata']['reqlox-runtime'])
            if runtime_config['paid_model_calls_enabled'] is not False or runtime_config['access']!='CLOUDFLARE_OWNER_LOGIN' or runtime_config['web']['public_origin']!='https://'+domain or runtime_config['web']['authentication']!='OWNER_BASIC_AUTH':
                raise ValueError('Owner access or model boundary differs')
        if kind=='google_iap_tunnel_instance_iam_member':
            if after.get('instance')!=prefix or after.get('role')!='roles/iap.tunnelResourceAccessor' or after.get('member') not in variables['iap_members']:
                raise ValueError('Unscoped IAP access')
        changes.append(resource['address'])
    if not 1<=len(changes)<=30:raise ValueError('Unexpected Web plan size')
    if replacements and ('google_compute_instance.web[0]' not in replacements or len(replacements)>2):raise ValueError('Unbound replacement set')
    return {'status':'PASS','creates':len(changes),'updates':0,'deletes':len(replacements),'replacements':replacements,'changes':changes,
            'private_bucket_publication':False,'secret_values_in_state':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan-json',type=Path,required=True)
    parser.add_argument('--project',required=True)
    parser.add_argument('--domain',required=True)
    parser.add_argument('--replace-instance-id')
    args=parser.parse_args()
    print(json.dumps(validate(json.loads(args.plan_json.read_bytes()),args.project,args.domain,args.replace_instance_id)))
