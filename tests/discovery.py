"""CLI failure contract, fixed before implementation.

Discovery must recover zero-word-overlap passages; pure stdin reranking must not
scan or add unrelated corpus chunks; malformed, stale and out-of-scope input must
fail; duplicate/context lines must survive exactly once; empty stdin must finish
without model work. Cache reuse must preserve ranking, invalidate changed/deleted
source and changed models, tolerate corruption, and never write to the corpus.
All receipts use the real model and executable, not mocked internals.
"""
import hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path
cli=shutil.which('sgrep'); assert cli
checks=[]
with tempfile.TemporaryDirectory(prefix='sgrep-discovery-') as tmp:
 root=Path(tmp)/'repo';root.mkdir();cache=Path(tmp)/'cache'
 subprocess.run(['git','init','-q',root],check=True)
 (root/'.gitignore').write_text('ignored.txt\n')
 (root/'ignored.txt').write_text('automobile automobile automobile\n')
 (root/'transport.txt').write_text('Vehicles have engines, wheels, a steering wheel, and brakes. Drivers travel along roads.\n')
 (root/'fruit.txt').write_text('Fresh apples and oranges grow on trees. Bananas and strawberries are delicious fruits.\n')
 (root/'empty').mkdir()
 env=os.environ|{'HF_HUB_OFFLINE':'1','SGREP_CACHE_DIR':str(cache)}
 def call(name,args,stdin=None,code=0):
  p=subprocess.run([cli,*args],cwd=root,env=env,input=stdin,text=True,capture_output=True,timeout=120)
  checks.append(dict(name=name,code=p.returncode,stdout=p.stdout,stderr=p.stderr))
  assert p.returncode==code,(name,p.stderr,p.returncode)
  return json.loads(p.stdout) if code in (0,1) else p.stderr
 def rg(*args):
  p=subprocess.run(['rg','--json',*args],cwd=root,text=True,capture_output=True);assert p.returncode in (0,1);return p.stdout
 before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
 rows=call('zero lexical overlap',['automobile','--json','--explain','-n','1'])
 assert rows[0]['path']=='transport.txt',rows
 assert rows[0]['scores']['bm25']==0,rows
 assert list(cache.rglob('*.bin'))
 hashes={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.rglob('*.bin')}
 assert call('warm repeat',['automobile','--json','--explain','-n','1'])==rows
 assert hashes=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.rglob('*.bin')}
 assert call('uncached equivalence',['automobile','--json','--explain','-n','1','--no-cache'])==rows
 raw=rg('-C','3','engines','transport.txt')
 streamed=call('stdin only ranks supplied passages',['automobile','--json','--stdin'],raw)
 assert len(streamed)==1 and streamed[0]['path']=='transport.txt',streamed
 assert streamed[0]['content']==(root/'transport.txt').read_text()
 assert call('duplicate input',['automobile','--json','--stdin'],raw+raw)==streamed
 assert call('empty stdin',['automobile','--json','--stdin'],'',code=1)==[]
 call('malformed stdin',['automobile','--json','--stdin'],'{bad',code=2)
 call('conflicting inputs',['automobile','--json','--stdin','--rg-json','-'],raw,code=2)
 call('scope validation',['automobile','fruit.txt','--json','--stdin'],raw,code=2)
 assert call('empty corpus',['automobile','empty','--json'],code=1)==[]
 after={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
 assert before==after,'search wrote inside repository'
 for p in cache.rglob('*.bin'):p.write_bytes(b'corrupt')
 assert call('corrupt cache recovers',['automobile','--json','--explain','-n','1'])==rows
 call('explicit code model has separate cache',['automobile','--model','code','--json'])
 assert len(list(cache.rglob('*.bin')))==2
 assert call('text model cache remains valid',['automobile','--model','text','--json','--explain','-n','1'])==rows
 unavailable=Path(tmp)/'not-a-directory';unavailable.write_text('occupied')
 env['SGREP_CACHE_DIR']=str(unavailable)
 assert call('unwritable cache is optional',['automobile','--json','--explain','-n','1'])==rows
 env['SGREP_CACHE_DIR']=str(cache)
 (root/'transport.txt').write_text('Lemons are sour citrus fruit.\n')
 call('stale input',['automobile','--json','--stdin'],raw,code=2)
 changed=call('cache invalidates edits',['citrus','--json'])
 assert any('Lemons' in r['content'] for r in changed)
 assert not any('engines' in r['content'] for r in changed)
 (root/'transport.txt').unlink()
 assert all(r['path']!='transport.txt' for r in call('cache invalidates deletion',['citrus','--json']))
 print(json.dumps({'ok':True,'checks':checks},indent=2))
