"""E2E controls for image/runtime compatibility before paid scored attempts."""
from pathlib import Path
import json,modal,time,concurrent.futures,shlex
from run_benchmark import APP,VOLUME,prepare,command,put
from swebench.harness.utils import make_test_spec
from swebench.harness.grading import get_eval_report
B=Path(__file__).resolve().parent

def verify(row):
 out=B/'prepared-agent-controls'/row['instance_id'];out.mkdir(parents=True,exist_ok=True)
 prior=out/'receipt.json'
 if prior.exists() and json.loads(prior.read_text()).get('prepared_environment_control'):return json.loads(prior.read_text())
 start=time.monotonic();s=modal.Sandbox.create(app=APP,image=modal.Image.from_registry(row['image']),volumes={'/bench-tools':VOLUME},cpu=(4,4),memory=(8192,8192),timeout=1000)
 d={'task':row['instance_id'],'sandbox_id':s.object_id,'started':time.time(),'passed':False}
 try:
  d['preparation']=prepare(s,row,'ripgrep')
  d['runtime']=command(s,'python --version; cat /etc/os-release')
  patch=command(s,'python /root/collect_patch.py');assert patch['exit_code']==0 and patch['stdout']=='',patch
  command(s,'mkdir -p /testbed/benchmark_adapter_fixture')
  put(s,'/testbed/benchmark_adapter_fixture/colors.py','def benchmark_find_color():\n    """Return the blue color."""\n    return "blue"\n')
  args=json.dumps({'query':'function that returns the color blue','pattern':'benchmark_find_color','path':'benchmark_adapter_fixture'})
  d['searches']={}
  for arm in ['ripgrep','sgrep-pipe']:
   r=command(s,'python /root/remote_search.py '+arm+' '+shlex.quote(args),timeout=315)
   assert r['exit_code']==0,r
   t=json.loads(r['stdout']);d['searches'][arm]=t
   assert t['exit_code']==0 and 'benchmark_find_color' in t['stdout'],t
  command(s,'rm -rf /testbed/benchmark_adapter_fixture')
  put(s,'/tmp/control.patch',row['patch']);d['apply']=command(s,'cd /testbed && git apply /tmp/control.patch');assert d['apply']['exit_code']==0,d['apply']
  patch=command(s,'python /root/collect_patch.py');assert patch['exit_code']==0 and patch['stdout'].startswith('diff --git'),patch
  (out/'collected-gold.diff').write_text(patch['stdout'])
  spec=make_test_spec(row)
  # Exercise the already-installed agent environment, without the grader's reinstall step.
  marker='git checkout '+row['base_commit']
  control=spec.eval_script[spec.eval_script.index(marker):]
  control=control.replace(marker,'git checkout HEAD')
  control='#!/bin/bash\nset -uxo pipefail\nsource /opt/miniconda3/bin/activate\nconda activate testbed\ncd /testbed\n'+control
  put(s,'/tmp/control-eval.sh',control)
  r=command(s,'bash /tmp/control-eval.sh',timeout=700);(out/'test-output.txt').write_text(r['stdout'])
  d['report']=get_eval_report(spec,{'instance_id':row['instance_id'],'model_name_or_path':'prepared-source-control','model_patch':row['patch']},str(out/'test-output.txt'),True)
  assert d['report'][row['instance_id']]['resolved'] is True,d['report']
  d['passed']=True;d['prepared_environment_control']=True
 except Exception as e:d['error']=str(e)[:1500]
 finally:
  s.terminate();d['seconds']=time.monotonic()-start;prior.write_text(json.dumps(d,indent=2))
 print(json.dumps({'task':d['task'],'passed':d['passed'],'error':d.get('error'),'seconds':d['seconds']}),flush=True)
 return d
if __name__=='__main__':
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(verify,json.loads((B/'selected-evaluator-only.json').read_text())))
 result={'passed':all(r['passed'] for r in rows),'tasks':len(rows),'failures':[r['task'] for r in rows if not r['passed']]};(B/'prepared-agent-controls.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
