from pathlib import Path
import json,modal,time,shlex,concurrent.futures
from run_benchmark import APP,VOLUME,prepare,put,command,ARMS
B=Path(__file__).resolve().parent

def check(row):
 start=time.monotonic();s=modal.Sandbox.create(app=APP,image=modal.Image.from_registry(row['image']),volumes={'/bench-tools':VOLUME},cpu=(4,4),memory=(8192,8192),timeout=900,outbound_domain_allowlist=['api.typesafe.ai'])
 d={'task':row['instance_id'],'sandbox_id':s.object_id,'searches':{},'passed':False}
 try:
  d['preparation']=prepare(s,row,'jevgrep')
  command(s,'mkdir -p /testbed/benchmark_adapter_fixture')
  put(s,'/testbed/benchmark_adapter_fixture/colors.py','def benchmark_find_color():\n    """Return the blue color."""\n    return "blue"\n')
  prefix='export HOME=/root/search-home XDG_CACHE_HOME=/root/search-home/.cache XDG_CONFIG_HOME=/root/search-home/.config PATH=/bench-tools/bin:$PATH OMP_NUM_THREADS=4 RAYON_NUM_THREADS=4; '
  for cmd in ['ck --index /testbed/benchmark_adapter_fixture','colgrep settings --agent-threads 8 --parallel 4 --agent-llama-server /bench-tools/home/.cache/colgrep/llama.cpp/llama-b11476-bin-ubuntu-vulkan-x64/llama-b11476/llama-server','colgrep --force-cpu -y init /testbed/benchmark_adapter_fixture']:
   r=command(s,prefix+cmd,timeout=300);assert r['exit_code']==0,r
  args=json.dumps({'query':'function that returns the color blue','pattern':'benchmark_find_color','path':'benchmark_adapter_fixture'})
  for arm in ARMS:
   r=command(s,'python /root/remote_search.py '+arm+' '+shlex.quote(args),timeout=315);assert r['exit_code']==0,r
   x=json.loads(r['stdout']);d['searches'][arm]=x;assert x['exit_code']==0,x
  d['passed']=True
 except Exception as e:d['error']=str(e)[:2000]
 finally:
  s.terminate();d['seconds']=time.monotonic()-start;(B/('native-matrix-'+row['instance_id']+'.json')).write_text(json.dumps(d,indent=2))
 print(json.dumps({'task':d['task'],'passed':d['passed'],'arms':list(d['searches']),'error':d.get('error')}),flush=True)
 return d
if __name__=='__main__':
 rows=[r for r in json.loads((B/'tasks.json').read_text()) if r['instance_id'] in ['astropy__astropy-7671','psf__requests-6028']]
 with concurrent.futures.ThreadPoolExecutor(max_workers=2) as p:result=list(p.map(check,rows))
 assert all(r['passed'] for r in result)
