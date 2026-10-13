from pathlib import Path
import csv,json,collections,statistics,hashlib
import numpy as np
B=Path(__file__).resolve().parent
ARMS=['ripgrep','sgrep-pipe','sgrep','ck-semantic','ck-hybrid','jevgrep','colgrep','colgrep-agent']
def avg(x):return float(np.mean(x)) if x else None
def quant(x,q):return float(np.quantile(x,q)) if x else None
def writecsv(path,rows):
 if not rows:return
 with path.open('w') as f:
  w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
runs=[];queries=[];requests=[]
for p in sorted((B/'runs').glob('*/result.json')):
 d=json.loads(p.read_text());prep=d.get('preparation',{});ind=prep.get('index_build') or {};uses=d['usage']
 totals={k:sum(u.get(k,0) for u in uses) for k in ['input_tokens','output_tokens']}
 totals.update({k:sum(u.get('input_tokens_details',{}).get(k,0) for u in uses) for k in ['cached_tokens','cache_write_tokens']})
 totals['reasoning_tokens']=sum(u.get('output_tokens_details',{}).get('reasoning_tokens',0) for u in uses)
 api_uncached=(totals['input_tokens']*.1+totals['output_tokens']*.5)/1e6
 r={'id':d['id'],'task':d['task'],'repo':d['repo'],'arm':d['arm'],'repeat':d['repeat'],'status':d['status'],'resolved':int(d.get('resolved',False)),'agent_seconds':d.get('agent_seconds'),'preparation_seconds':prep.get('seconds'),'index_seconds':ind.get('seconds',0),'cold_task_seconds':(prep.get('seconds',0)+d.get('agent_seconds',0)) if prep else d['sandbox_lifetime_seconds'],'coding_cost_usd':d['api_cost_usd'],'retrieval_cost_usd':d['retrieval_cost_usd'],'api_cost_usd':d['api_cost_usd']+d['retrieval_cost_usd'],'unknown_api_cost_upper_usd':d.get('unknown_api_cost_upper_usd',0),'api_cost_upper_usd':d['api_cost_usd']+d['retrieval_cost_usd']+d.get('unknown_api_cost_upper_usd',0),'compute_estimate_usd':d['infra_allocation_estimate_usd'],'total_estimate_usd':d['total_estimate_usd'],'no_prompt_cache_api_usd':api_uncached+d['retrieval_cost_usd'],'accounting_complete':d.get('accounting_complete',False),'turns':len(uses),'searches':len(d['searches']),'error':d.get('error',''),'grading_error':d.get('grading',{}).get('error',''),**totals}
 runs.append(r)
 for t in sorted(p.parent.glob('tool-*.json')):
  x=json.loads(t.read_text());a=x.get('arguments',{})
  if 'query' in a:
   queries.append({'id':d['id'],'task':d['task'],'arm':d['arm'],'repeat':d['repeat'],'tool_file':str(t.relative_to(B)),'seconds':x.get('seconds'),'host_seconds':x.get('host_seconds'),'exit_code':x.get('exit_code'),'raw_tokens':x.get('raw_tokens'),'visible_tokens':x.get('visible_tokens'),'truncated':int(x.get('raw_tokens',0)>8000),'provider_requests':len(x.get('provider_requests',[]))})
 for i,(u,sec) in enumerate(zip(uses,d['api_seconds'])):
  requests.append({'id':d['id'],'arm':d['arm'],'turn':i,'seconds':sec,'input_tokens':u['input_tokens'],'output_tokens':u['output_tokens'],'cached_tokens':u.get('input_tokens_details',{}).get('cached_tokens',0),'cache_write_tokens':u.get('input_tokens_details',{}).get('cache_write_tokens',0)})
writecsv(B/'attempts.csv',runs);writecsv(B/'searches.csv',queries);writecsv(B/'model-requests.csv',requests)
summary=[]
for arm in ARMS:
 rs=[r for r in runs if r['arm']==arm];qs=[q for q in queries if q['arm']==arm];req=[x for x in requests if x['arm']==arm]
 if not rs:continue
 solved=sum(r['resolved'] for r in rs)
 summary.append({'arm':arm,'attempts':len(rs),'resolved':solved,'solve_rate':solved/len(rs),'mean_api_usd':avg([r['api_cost_usd'] for r in rs]),'mean_total_estimate_usd':avg([r['total_estimate_usd'] for r in rs]),'mean_api_upper_usd':avg([r['api_cost_upper_usd'] for r in rs]),'api_usd_per_resolved':sum(r['api_cost_usd'] for r in rs)/solved if solved else None,'median_agent_seconds':quant([r['agent_seconds'] for r in rs if r['agent_seconds'] is not None],.5),'p95_agent_seconds':quant([r['agent_seconds'] for r in rs if r['agent_seconds'] is not None],.95),'median_cold_seconds':quant([r['cold_task_seconds'] for r in rs],.5),'p95_cold_seconds':quant([r['cold_task_seconds'] for r in rs],.95),'median_index_seconds':quant([r['index_seconds'] for r in rs],.5),'median_search_seconds':quant([q['seconds'] for q in qs if q['seconds'] is not None],.5),'p95_search_seconds':quant([q['seconds'] for q in qs if q['seconds'] is not None],.95),'median_model_seconds':quant([q['seconds'] for q in req],.5),'p95_model_seconds':quant([q['seconds'] for q in req],.95),'search_timeouts':sum(q['exit_code']==124 for q in qs),'searches':len(qs),'mean_search_visible_tokens':avg([q['visible_tokens'] for q in qs if q['visible_tokens'] is not None]),'truncated_searches':sum(q['truncated'] for q in qs),'cache_read_fraction':sum(r['cached_tokens'] for r in rs)/max(1,sum(r['input_tokens'] for r in rs)),'incomplete_accounting':sum(not r['accounting_complete'] for r in rs),'attempt_errors':sum(r['status']=='error' for r in rs),'grading_errors':sum(bool(r['grading_error']) for r in rs)})
paired=[];rng=np.random.default_rng(20261013)
by=collections.defaultdict(list)
for r in runs:by[(r['task'],r['arm'])].append(r)
for arm in ARMS[1:]:
 tasks=sorted(t for t,a in by if a==arm and len(by[t,arm])==2 and len(by.get((t,'ripgrep'),[]))==2)
 if not tasks:continue
 n=len(tasks);idx=rng.integers(0,n,(10000,n));res={'arm':arm,'paired_tasks':n}
 for metric in ['resolved','api_cost_usd','api_cost_upper_usd','total_estimate_usd','agent_seconds','cold_task_seconds']:
  if any(r[metric] is None for t in tasks for a in [arm,'ripgrep'] for r in by[t,a]):continue
  x=np.array([avg([r[metric] for r in by[t,arm]]) for t in tasks]);base=np.array([avg([r[metric] for r in by[t,'ripgrep']]) for t in tasks]);d=x-base;boot=d[idx].mean(axis=1)
  res[metric]={'candidate_mean':float(x.mean()),'baseline_mean':float(base.mean()),'difference':float(d.mean()),'ci95':[float(z) for z in np.quantile(boot,[.025,.975])]}
  if metric!='resolved':res[metric]['relative_change']=float(x.mean()/base.mean()-1) if base.mean() else None
 if 'resolved' in res:res['accuracy_within_5pp_supported']=res['resolved']['ci95'][0]>-.05
 paired.append(res)
writecsv(B/'summary.csv',summary)
result={'completed_attempts':len(runs),'expected_attempts':800,'complete':len(runs)==800,'coding_api_usd':sum(r['coding_cost_usd'] for r in runs),'unknown_api_cost_upper_usd':sum(r['unknown_api_cost_upper_usd'] for r in runs),'retrieval_api_usd':sum(r['retrieval_cost_usd'] for r in runs),'compute_allocation_estimate_usd':sum(r['compute_estimate_usd'] for r in runs),'total_scored_estimate_usd':sum(r['total_estimate_usd'] for r in runs),'summary':summary,'paired':paired,'status_counts':dict(collections.Counter(r['status'] for r in runs))}
(B/'analysis.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k not in ('summary','paired')},indent=2))
