"""Bounded owner gateway: GCS browser assets and private VPC API proxy."""
import base64
import hmac
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import threading
import urllib.error
import urllib.parse
import urllib.request

STATIC = {"/":"index.html","/study":"study.html","/knowledge":"knowledge.html",
          "/targets":"targets.html","/targets.js":"targets.js","/targets.css":"targets.css",
          "/records":"records.html","/records.js":"records.js","/workspace.js":"workspace.js","/workspace.css":"workspace.css",
          "/app.js":"app.js","/study.js":"study.js","/knowledge.js":"knowledge.js","/style.css":"style.css"}
PUBLIC = {'/demo/':'public-demo.html', '/demo/public-demo.html':'public-demo.html',
          '/demo/public-demo.js':'public-demo.js', '/demo/public-demo.css':'public-demo.css',
          '/demo/public-demo.json':'public-demo.json'}
MAXIMUM_BYTES=8*1024*1024
CSP="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'"


class Handler(BaseHTTPRequestHandler):
    server_version="REQLOX-owner"
    sys_version=""

    def log_message(self,*args):pass

    def send(self,status,raw=b'',kind='application/json; charset=utf-8',challenge=False):
        self.send_response(status)
        for key,value in [('Content-Type',kind),('Content-Length',str(len(raw))),('Cache-Control','no-store, no-transform'),
                          ('X-Content-Type-Options','nosniff'),('Referrer-Policy','no-referrer'),('Content-Security-Policy',CSP),
                          ('Strict-Transport-Security','max-age=86400')]:
            self.send_header(key,value)
        if challenge:self.send_header('WWW-Authenticate','Basic realm="REQLOX owner", charset="UTF-8"')
        self.end_headers()
        if self.command!='HEAD':self.wfile.write(raw)

    def proxy(self):
        self.connection.settimeout(90)
        if self.path=='/__ready' and self.command=='GET':
            try:
                request=urllib.request.Request(self.server.backend+'/api/deployment',headers={
                    'Authorization':self.server.authorization.decode(),'Host':self.server.public_host,'X-Forwarded-Proto':'https'})
                with urllib.request.urlopen(request,timeout=3) as response:value=json.loads(response.read(65536))
                ready=value.get('status')=='READY' and value.get('release_sha256')==self.server.release and value.get('paid_model_calls_enabled') is False
                return self.send(200 if ready else 503,b'{"status":"READY"}' if ready else b'{"status":"WAITING"}')
            except (OSError,ValueError):return self.send(503,b'{"status":"WAITING"}')
        origin=self.headers.get('Origin')
        if origin is not None and origin!='https://'+self.server.public_host:
            return self.send(403,b'{"error":"Use the configured HTTPS origin."}')
        path=urllib.parse.urlsplit(self.path).path
        public_asset = path in PUBLIC
        if path == '/demo' and self.command in ('GET','HEAD'):
            self.send_response(308)
            self.send_header('Location','/demo/')
            self.send_header('Content-Length','0')
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            return
        if path.startswith('/demo/') or path == '/demo':
            if not public_asset:return self.send(404,b'{"error":"Not found."}')
            if self.command not in ('GET','HEAD'):return self.send(405)
        if not public_asset and not hmac.compare_digest(self.headers.get('Authorization','').encode(),self.server.authorization):
            return self.send(401,b'{"error":"Owner sign-in required."}',challenge=True)
        if self.command not in ('GET','HEAD','POST'):return self.send(405)
        body=None
        if self.command=='POST':
            try:
                length=int(self.headers.get('Content-Length','0'))
                if not 1<=length<=MAXIMUM_BYTES or self.headers.get('Transfer-Encoding'):raise ValueError()
                body=self.rfile.read(length)
                if len(body)!=length:raise ValueError()
            except ValueError:return self.send(400,b'{"error":"Check the input size."}')
        if self.command in ('GET','HEAD') and (public_asset or path in STATIC):
            filename = PUBLIC[path] if public_asset else STATIC[path]
            url='https://storage.googleapis.com/'+self.server.bucket+'/'+getattr(self.server,'asset_prefix','')+filename
            headers={}
        elif path.startswith('/api/'):
            url=self.server.backend+self.path
            headers={'Authorization':self.server.authorization.decode(),'Host':self.server.public_host,
                     'X-Forwarded-Proto':'https'}
            for key in ('Content-Type','X-REQLOX-Token','Origin'):
                if self.headers.get(key) is not None:headers[key]=self.headers[key]
        else:return self.send(404,b'{"error":"Not found."}')
        if not self.server.bound.acquire(blocking=False):return self.send(429,b'{"error":"Try again shortly."}')
        try:
            request=urllib.request.Request(url,data=body,headers=headers,method=self.command)
            try:
                response=urllib.request.urlopen(request,timeout=90)
            except urllib.error.HTTPError as exc:response=exc
            with response:
                bound = 1024*1024 if public_asset else MAXIMUM_BYTES
                raw=response.read(bound+1)
                if len(raw)>bound:raise ValueError('Response size bound')
                return self.send(response.status,raw,response.headers.get('Content-Type','application/json'))
        except (OSError,ValueError):return self.send(503,b'{"error":"The bounded VM is unavailable. Saved data is retained."}')
        finally:self.server.bound.release()

    do_GET=proxy
    do_POST=proxy
    do_HEAD=proxy
    do_PUT=do_PATCH=do_DELETE=do_OPTIONS=proxy


def main():
    password=Path('/var/run/secrets/owner/password').read_bytes()
    if not 24<=len(password)<=128:raise ValueError('Owner secret unavailable')
    server=ThreadingHTTPServer(('0.0.0.0',int(os.environ.get('PORT','8080'))),Handler)
    server.daemon_threads=True
    server.public_host=os.environ['PUBLIC_HOST']
    server.bucket=os.environ['GCS_BUCKET']
    server.asset_prefix=os.environ.get('ASSET_PREFIX','')
    if server.asset_prefix:
        import re
        if not re.fullmatch(r'releases/[a-f0-9]{40}/',server.asset_prefix):
            raise ValueError('Asset release identity differs')
    server.backend=os.environ['BACKEND_URL']
    server.release=os.environ['RELEASE_SHA256']
    server.authorization=b'Basic '+base64.b64encode(b'reqlox:'+password)
    server.bound=threading.BoundedSemaphore(8)
    server.serve_forever()


if __name__=='__main__':main()
