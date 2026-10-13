from pathlib import Path
import base64, concurrent.futures, json, time, traceback
import modal
from swebench.harness.utils import make_test_spec
from swebench.harness.grading import get_eval_report

B=Path(__file__).resolve().parent
APP=modal.App.lookup('sgrep-swe-benchmark-20261012')
ROWS=json.loads((B/'selected-evaluator-only.json').read_text())

def put(sb,path,content):
    encoded=base64.b64encode(content.encode()).decode()
    for i in range(0,max(1,len(encoded)),32000):
        mode='wb' if i==0 else 'ab'
        p=sb.exec('python','-c','import base64,sys;open(sys.argv[1],sys.argv[3]).write(base64.b64decode(sys.argv[2]))',path,encoded[i:i+32000],mode)
        p.wait()
        if p.returncode:raise RuntimeError(p.stderr.read())

def command(sb,cmd,timeout=600):
    p=sb.exec('bash','-lc','{\n'+cmd+'\n} </dev/null 2>&1',timeout=timeout,text=False)
    out=p.stdout.read().decode('utf-8',errors='backslashreplace');err=p.stderr.read().decode('utf-8',errors='backslashreplace');p.wait()
    return {'stdout':out,'stderr':err,'exit_code':p.returncode}

def grade(row,patch,out):
    out.mkdir(parents=True,exist_ok=True)
    spec=make_test_spec(row); started=time.monotonic()
    sb=modal.Sandbox.create(app=APP,image=modal.Image.from_registry(row['image']),cpu=(2,2),memory=(8192,8192),timeout=900)
    receipt={'sandbox_id':sb.object_id,'image':row['image'],'started':time.time()}
    try:
        put(sb,'/tmp/candidate.patch',patch)
        put(sb,'/tmp/official-eval.sh',spec.eval_script)
        pre=command(sb,'cd /testbed && git rev-parse HEAD && git status --porcelain')
        receipt['source']=pre
        tree=command(sb,'cd /testbed && git diff --raw '+row['base_commit']+' HEAD')
        receipt['base_tree_check']=tree
        if tree['exit_code']:raise RuntimeError('Image base commit missing')
        changes=[line.split('\t')[-1] for line in tree['stdout'].splitlines() if line.split()[2]!=line.split()[3]]
        if any(x not in ['pyproject.toml','setup.py','setup.cfg','tox.ini'] for x in changes):raise RuntimeError('Unexpected image source changes: '+str(changes))
        if patch:
            applied=command(sb,'cd /testbed && git apply /tmp/candidate.patch')
            receipt['apply']=applied
            if applied['exit_code']:raise RuntimeError('Patch failed to apply')
        run=command(sb,'bash /tmp/official-eval.sh',timeout=700)
        (out/'test-output.txt').write_text(run['stdout']+'\n'+run['stderr'])
        prediction={'instance_id':row['instance_id'],'model_name_or_path':'preflight','model_patch':patch}
        report=get_eval_report(spec,prediction,str(out/'test-output.txt'),True)
        receipt.update(report=report,exit_code=run['exit_code'])
    except Exception as e:
        receipt['error']=str(e)
    finally:
        sb.terminate(wait=True);receipt['seconds']=time.monotonic()-started
        (out/'receipt.json').write_text(json.dumps(receipt,indent=2))
    return receipt

def check(row):
    out=B/'preflight-v3'/row['instance_id'];result={}
    for mode,patch in [('gold',row['patch']),('unfixed','')]:
        f=out/mode/'receipt.json'
        old=json.loads(f.read_text()) if f.exists() else None
        if old and old.get('error','').startswith('Unexpected image source changes'):
            f.rename(f.with_name('receipt-source-check-v3.json'));old=None
        result[mode]=old if old else grade(row,patch,f.parent)
    good=result['gold'].get('report',{}).get(row['instance_id'],{}).get('resolved') is True
    bad=result['unfixed'].get('report',{}).get(row['instance_id'],{}).get('resolved') is False
    result['eligible']=good and bad and not result['unfixed'].get('error')
    (out/'result.json').write_text(json.dumps(result,indent=2))
    print(json.dumps({'id':row['instance_id'],'eligible':result['eligible'],'gold':good,'unfixed_failed':bad}),flush=True)
    return row['instance_id'],result['eligible']

if __name__=='__main__':
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        result=dict(pool.map(check,ROWS))
    (B/'preflight-summary.json').write_text(json.dumps(result,indent=2))
