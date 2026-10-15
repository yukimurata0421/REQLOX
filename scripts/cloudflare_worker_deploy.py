#!/usr/bin/env python3
"""Bind a new Worker to exactly one unoccupied domain without changing others."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import urllib.error
import urllib.parse
import urllib.request
import uuid

from cloudflare_deploy import credentials, Edge, validate


def multipart(metadata, source):
    boundary="reqlox-"+uuid.uuid4().hex
    chunks=[]
    for name,filename,kind,raw in [('metadata','metadata.json','application/json',json.dumps(metadata).encode()),
                                   ('worker.mjs','worker.mjs','application/javascript+module',source)]:
        chunks.append((f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{filename}"\r\nContent-Type: {kind}\r\n\r\n').encode()+raw+b'\r\n')
    return boundary,b''.join(chunks)+f'--{boundary}--\r\n'.encode()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',type=Path,required=True)
    parser.add_argument('--state-dir',type=Path,required=True)
    parser.add_argument('--credential-ssh-host',required=True)
    parser.add_argument('--credential-path',required=True)
    parser.add_argument('--origin',required=True)
    parser.add_argument('--worker',type=Path,required=True)
    args=parser.parse_args();os.umask(0o077)
    config=validate(json.loads(args.config.read_bytes()))
    origin=urllib.parse.urlsplit(args.origin)
    if origin.scheme!='https' or not origin.hostname.endswith('.run.app') or origin.username or origin.path not in ('','/'):
        raise ValueError('Use the verified Google Cloud Run HTTPS origin')
    state=args.state_dir/'worker-state.json'
    if state.exists():raise ValueError('Preserve the previous attempt; no automatic redeployment')
    values=credentials(args.credential_ssh_host,args.credential_path);edge=Edge(values,args.state_dir)
    account,zone=values['CLOUDFLARE_ACCOUNT_ID'],values['CLOUDFLARE_ZONE_ID']
    z=edge.request('GET','/zones/'+zone)
    if z['name']!=config['root_domain'] or z['account']['id']!=account:raise ValueError('Zone identity drift')
    dns=edge.request('GET','/zones/'+zone+'/dns_records?'+urllib.parse.urlencode({'name':config['domain']}))
    scripts=edge.request('GET','/accounts/'+account+'/workers/scripts')
    if dns or any(s.get('id')==config['name'] for s in scripts):raise ValueError('Existing resource must not be overwritten')
    source=args.worker.read_bytes()
    metadata={'main_module':'worker.mjs','compatibility_date':'2026-10-11','bindings':[
        {'type':'plain_text','name':'ORIGIN','text':args.origin},{'type':'plain_text','name':'PUBLIC_HOST','text':config['domain']}]}
    boundary,raw=multipart(metadata,source);path='/accounts/'+account+'/workers/scripts/'+config['name']
    request=urllib.request.Request('https://api.cloudflare.com/client/v4'+path,data=raw,method='PUT',
        headers={'Authorization':'Bearer '+values['CLOUDFLARE_API_TOKEN'],'Content-Type':'multipart/form-data; boundary='+boundary})
    try:
        with urllib.request.urlopen(request,timeout=60) as response:result=json.load(response)
    except urllib.error.HTTPError as exc:
        edge.audit('PUT',path,raw,'HTTP_'+str(exc.code));raise ValueError('Worker upload failed: HTTP '+str(exc.code)) from None
    edge.audit('PUT',path,raw,'SUCCESS' if result.get('success') else 'REJECTED')
    if not result.get('success'):raise ValueError('Worker upload rejected')
    record={'worker':config['name'],'domain':config['domain'],'source_sha256':hashlib.sha256(source).hexdigest(),'custom_domain_id':None}
    state.write_text(json.dumps(record,indent=2)+'\n')
    domain=edge.request('PUT','/accounts/'+account+'/workers/domains',{'hostname':config['domain'],'service':config['name'],'zone_id':zone,'environment':'production'})
    record['custom_domain_id']=domain['id'];state.write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record))


if __name__=='__main__':main()
