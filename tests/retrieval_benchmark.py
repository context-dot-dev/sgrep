"""Frozen paired CLI comparison. No discarded failures, real source validation."""
import argparse,hashlib,json,os,platform,statistics,subprocess,time
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('before',type=Path)
parser.add_argument('after',type=Path)
parser.add_argument('queries',type=Path)
parser.add_argument('output',type=Path)
args=parser.parse_args()
BEFORE=args.before.resolve(); AFTER=args.after.resolve()
queries=json.loads(args.queries.read_text())
if not queries:
    parser.error("query file must contain at least one query")
OUT=args.output.resolve();OUT.mkdir(parents=True,exist_ok=True)
CACHE=OUT/'cache'
ENV=os.environ|{'HF_HUB_OFFLINE':'1','IS_LOCAL':'true','SGREP_CACHE_DIR':str(CACHE)}
rows=[]
def run(binary,q):
 command=[str(binary),q['query'],q['root'],'--json','-n','50']
 start=time.perf_counter();p=subprocess.run(command,env=ENV,text=True,capture_output=True,timeout=180); elapsed=(time.perf_counter()-start)*1000
 result={'command':command,'ms':elapsed,'exit_code':p.returncode,'stderr':p.stderr,'bytes':len(p.stdout.encode())}
 if p.returncode not in (0,1):return result
 hits=json.loads(p.stdout);result['results']=hits
 for h in hits:
  lines=(Path(q['root'])/h['path']).read_text().splitlines(keepends=True)
  assert h['content']==''.join(lines[h['start']-1:h['end']]),(q['id'],h)
 target=q['target']; ranks=[i+1 for i,h in enumerate(hits) if h['path']==target['path']]
 result['rank']=min(ranks) if ranks else None
 gold=set(range(target['start'],target['end']+1));covered=set();remaining=8000
 for h in hits:
  header=f"{h['path']}:{h['start']}-{h['end']}\n";remaining-=len(header)
  if remaining<=0:break
  for line,text in enumerate(h['content'].splitlines(keepends=True),h['start']):
   if len(text)>remaining:remaining=0;break
   remaining-=len(text)
   if h['path']==target['path']:covered.add(line)
  if remaining<=0:break
 result['coverage_8k_chars']=len(gold&covered)/len(gold)
 return result
seen=set()
for i,q in enumerate(queries):
 row={'id':q['id'],'language':q['language'],'target':q['target'],'first_corpus_query':q['root'] not in seen,'arms':{}}
 for name,binary in ([('before',BEFORE),('after',AFTER)] if i%2==0 else [('after',AFTER),('before',BEFORE)]):
  result=run(binary,q);(OUT/f'{q["id"]}.{name}.json').write_text(json.dumps(result,indent=2))
  row['arms'][name]={k:v for k,v in result.items() if k not in ('results','command')}
 seen.add(q['root']);rows.append(row)
 (OUT/'rows.json').write_text(json.dumps(rows,indent=2))
 if (i+1)%10==0:print(i+1,'/',len(queries),flush=True)
summary={}
for name in ['before','after']:
 r=[x['arms'][name] for x in rows]; valid=[x for x in r if x['exit_code'] in (0,1)]
 summary[name]={'n':len(r),'failures':len(r)-len(valid),'file_at_1':sum(x.get('rank')==1 for x in r)/len(r),'file_at_5':sum(x.get('rank') is not None and x['rank']<=5 for x in r)/len(r),'file_at_10':sum(x.get('rank') is not None and x['rank']<=10 for x in r)/len(r),'half_function_8k_chars':sum(x.get('coverage_8k_chars',0)>=.5 for x in r)/len(r),'full_function_8k_chars':sum(x.get('coverage_8k_chars',0)==1 for x in r)/len(r),'median_ms':statistics.median(x['ms'] for x in r),'median_first_corpus_ms':statistics.median(x['arms'][name]['ms'] for x in rows if x['first_corpus_query']),'median_reuse_ms':statistics.median([x['arms'][name]['ms'] for x in rows if not x['first_corpus_query']]) if any(not x['first_corpus_query'] for x in rows) else None}
summary['conditions']={'queries':len(queries),'platform':platform.platform(),'source':str(args.queries.resolve()),'models':'cached offline','budget':'8000 Unicode source/header characters, whole lines only; not tokens','before_sha256':hashlib.sha256(BEFORE.read_bytes()).hexdigest(),'after_sha256':hashlib.sha256(AFTER.read_bytes()).hexdigest(),'cache_bytes':sum(p.stat().st_size for p in CACHE.rglob('*.bin'))}
(OUT/'summary.json').write_text(json.dumps(summary,indent=2));print(json.dumps(summary,indent=2))
