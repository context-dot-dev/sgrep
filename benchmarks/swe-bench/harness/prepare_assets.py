from pathlib import Path
import json,time
import modal
B=Path(__file__).resolve().parent
app=modal.App.lookup('sgrep-swe-benchmark-20261012')
v=modal.Volume.from_name('sgrep-benchmark-tools-20261012')
im=modal.Image.from_registry('ubuntu:24.04',add_python='3.12').apt_install('libgomp1','libstdc++6','libssl3','libcurl4','git','ripgrep')
script=r'''
set -euxo pipefail
mkdir -p /bench-tools/lib /bench-tools/home/.cache /tmp/warmup
cp -a /lib/x86_64-linux-gnu/. /bench-tools/lib/
export HOME=/bench-tools/home
export PATH=/bench-tools/bin:$PATH
rm -f /bench-tools/bin/ck /bench-tools/bin/colgrep
printf '#!/bin/sh\nexec /bench-tools/lib/ld-linux-x86-64.so.2 --library-path /bench-tools/lib /bench-tools/npm/node_modules/@beaconbay/ck-search/dist/bin/ck "$@"\n' > /bench-tools/bin/ck
printf '#!/bin/sh\nexec /bench-tools/lib/ld-linux-x86-64.so.2 --library-path /bench-tools/lib /bench-tools/colgrep/colgrep-x86_64-unknown-linux-gnu/colgrep "$@"\n' > /bench-tools/bin/colgrep
chmod +x /bench-tools/bin/ck /bench-tools/bin/colgrep
printf 'def retry_request(client):\n    return client.get("https://example.com")\n' > /tmp/warmup/example.py
python -c "from pathlib import Path; p=Path('/tmp/warmup'); [(p/('large.'+ext)).write_text(('// comment\\n' if ext!='py' else '# comment\\n')*400) for ext in ['py','js','ts','tsx','rs','go','c','cpp','java']]"
cd /tmp/warmup
sgrep --version
ck --version
jg --version
colgrep --version
sgrep 'retry request' . --no-cache
ck --index .
colgrep --force-cpu init
colgrep --force-cpu --install-agent
colgrep --help > /bench-tools/colgrep-help.txt
colgrep settings > /bench-tools/colgrep-settings.txt
find /bench-tools/home/.cache -maxdepth 4 -type d > /bench-tools/cache-directories.txt
find /bench-tools/home/.config -maxdepth 3 -type f > /bench-tools/config-files.txt || true
printf 'DONE\n' > /bench-tools/READY
'''
with modal.enable_output():
 sb=modal.Sandbox.create(app=app,image=im,volumes={'/bench-tools':v},cpu=4,memory=8192,timeout=1800)
 (B/'asset-builder.json').write_text(json.dumps({'sandbox_id':sb.object_id,'started':time.time()}))
 try:
  t=time.monotonic();p=sb.exec('bash','-lc','{ '+script+'\n} 2>&1',timeout=1700)
  with (B/'asset-setup.log').open('w') as f:
   for line in p.stdout:f.write(line);f.flush()
  p.wait();(B/'asset-result.json').write_text(json.dumps({'exit_code':p.returncode,'seconds':time.monotonic()-t}))
 finally:sb.terminate()
