import json,os,signal,subprocess,sys,time
from pathlib import Path

arm,raw=sys.argv[1:3]
a=json.loads(raw);root=Path('/testbed');scope=(root/a.get('path','.')).resolve()
try:scope.relative_to(root)
except ValueError:
    print(json.dumps({'stdout':'','stderr':'Search path outside repository','exit_code':2,'seconds':0,'provider_requests':[]}));sys.exit(0)
env=os.environ.copy();env.update(HOME='/root/search-home',XDG_CACHE_HOME='/root/search-home/.cache',XDG_CONFIG_HOME='/root/search-home/.config',PATH='/bench-tools/bin:'+os.environ['PATH'],NO_COLOR='1',OMP_NUM_THREADS='4',RAYON_NUM_THREADS='4',SGREP_CACHE_DIR='/root/search-home/.cache/sgrep')
q=a['query'];pattern=a['pattern'];path=str(scope)

def run(cmd,stdin=None,timeout=300):
    t=time.monotonic()
    p=subprocess.Popen(cmd,cwd='/testbed',env=env,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,start_new_session=True)
    try:
        out,err=p.communicate(stdin,timeout=timeout);status=p.returncode
    except subprocess.TimeoutExpired:
        os.killpg(p.pid,signal.SIGKILL);out,err=p.communicate();status=124
    return {'stdout':out.decode(errors='replace'),'stderr':err.decode(errors='replace'),'exit_code':status,'seconds':time.monotonic()-t}

started=time.monotonic();usage=Path('/root/jev-usage.jsonl');before=len(usage.read_text().splitlines()) if usage.exists() else 0
if arm=='ripgrep':
    r=run(['/bench-tools/bin/rg','--no-config','-n','-C','3','--color','never','--',pattern,path])
elif arm=='sgrep-pipe':
    candidates=run(['/bench-tools/bin/rg','--no-config','--json','-C','3','--',pattern,path])
    if candidates['exit_code'] not in (0,1):r=candidates
    else:
        r=run(['/bench-tools/bin/sgrep',q,'/testbed','--stdin','-n','20'],candidates['stdout'].encode())
        r['candidate_seconds']=candidates['seconds'];r['candidate_bytes']=len(candidates['stdout'].encode())
elif arm=='sgrep':r=run(['/bench-tools/bin/sgrep',q,path,'-n','20'])
elif arm in ('ck-semantic','ck-hybrid'):
    r=run(['/bench-tools/bin/ck','--sem' if arm=='ck-semantic' else '--hybrid','--full-section','--topk','20','--threshold','0',q,path])
elif arm=='jevgrep':
    env['NODE_OPTIONS']='--import=/root/jev-meter.mjs'
    r=run(['/bench-tools/bin/jg',q,path,'--max-output-bytes','0','--max-requests','1000'])
elif arm in ('colgrep','colgrep-agent'):
    r=run(['/bench-tools/bin/colgrep','--force-cpu','--color','never']+(['--agent'] if arm=='colgrep-agent' else ['-c','-k','20'])+[q,path])
else:raise ValueError('Unknown search backend')
r['seconds']=time.monotonic()-started
r['provider_requests']=[json.loads(x) for x in usage.read_text().splitlines()[before:]] if usage.exists() else []
print(json.dumps(r))
