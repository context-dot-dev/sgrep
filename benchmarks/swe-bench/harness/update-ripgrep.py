import json,time
from run_benchmark import *
v=modal.Volume.from_name('sgrep-benchmark-tools-20261012')
sb=modal.Sandbox.create(app=APP,image=modal.Image.from_registry('ubuntu:24.04',add_python='3.12').apt_install('ca-certificates'),volumes={'/bench-tools':v},cpu=1,memory=1024,timeout=180)
script='''import urllib.request,hashlib,tarfile,io,os,json
name='ripgrep-15.2.0-x86_64-unknown-linux-musl.tar.gz'
base='https://github.com/BurntSushi/ripgrep/releases/download/15.2.0/'
data=urllib.request.urlopen(base+name).read()
expected=urllib.request.urlopen(base+name+'.sha256').read().decode().split()[0]
assert hashlib.sha256(data).hexdigest()==expected
with tarfile.open(fileobj=io.BytesIO(data),mode='r:gz') as tar:
 content=tar.extractfile('ripgrep-15.2.0-x86_64-unknown-linux-musl/rg').read()
open('/bench-tools/bin/rg','wb').write(content);os.chmod('/bench-tools/bin/rg',0o755)
print(json.dumps({'archive_sha256':expected,'binary_sha256':hashlib.sha256(content).hexdigest()}))
'''
try:
 put(sb,'/tmp/install.py',script);r=command(sb,'python /tmp/install.py && /bench-tools/bin/rg --version');save(B/'ripgrep-release.json',r);print(r)
finally:sb.terminate()
