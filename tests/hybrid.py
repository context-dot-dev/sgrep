"""Real CLI acceptance for live BM25 + rg candidates and relative score fusion.

Failure contract (written before implementation): corpus filtering loses split
identifiers; rg-only candidates disappear; corpus statistics include duplicate
supplemental blocks; strong lexical gaps erased; equal scores divide by zero;
partial overlaps discarded; stale/malformed/out-of-scope JSON accepted; paths
or text treated as shell commands; source truncated, padded, or modified.
"""
import base64
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

cli = shutil.which('sgrep')
assert cli
checks = []
with tempfile.TemporaryDirectory(prefix='sgrep-hybrid-') as temp:
    root = Path(temp)
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    (root / '.gitignore').write_text('ignored.txt\n')
    (root / 'ignored.txt').write_text('excludedneedle\n')
    (root / 'binary.txt').write_bytes(b'\x00excludedneedle\n')
    (root / 'camel.py').write_text('def retryRequest():\n    return 1\n')
    (root / 'refund_handler.py').write_text('def process():\n    return False\n')
    (root / 'context.txt').write_text('cached lease renewal record\n' + 'ordinary data\n' * 10 + 'shared lease renewal record\n' + 'ordinary data\n' * 10 + 'renewal completion\n')
    (root / 'odd\nname.txt').write_text('singleflight joins concurrent work\n')
    (root / 'ranking').mkdir()
    (root / 'ranking' / 'needle.txt').write_text('ZXQ7319 ' * 6 + 'oranges pottery calendar ' * 40 + '\n')
    for i in range(12):
        (root / 'ranking' / f'lease{i:02}.txt').write_text('Lease renewals reconcile existing leases and extend the duration of active agreements.\n')

    def call(name, args, stdin=None, code=0):
        p = subprocess.run([cli, *args], cwd=root, input=stdin, capture_output=True, text=True, env=os.environ | {'HF_HUB_OFFLINE':'1'}, timeout=60)
        checks.append(dict(name=name,code=p.returncode,stdout=p.stdout,stderr=p.stderr))
        assert p.returncode == code, (name,p.returncode,p.stderr)
        return json.loads(p.stdout) if code in (0,1) else p.stderr

    def rg(*args):
        p = subprocess.run(['rg','--json',*args],cwd=root,capture_output=True,text=True)
        assert p.returncode in (0,1),p.stderr
        return p.stdout

    # A filename match must survive even without the term in the file contents.
    rows = call('repo wide filename evidence', ['refund','--json','--explain'])
    assert any(x['path']=='refund_handler.py' for x in rows)
    assert call('semantic candidates without literal matches', ['absentzzqq','--json'])
    assert all(r['path'] not in ('binary.txt','ignored.txt') for r in call('binary and ignored', ['excludedneedle','--json']))
    call('explain requires json', ['lease','--explain'],code=2)

    raw = rg('-C','0','singleflight','odd\nname.txt')
    rows = call('rg candidate independent of query words', ['parallel tasks','--json','--rg-json','-'],raw)
    assert rows and rows[0]['path']=='odd\nname.txt'
    saved=root/'hits.jsonl'; saved.write_text(raw)
    from_file=call('saved rg input', ['parallel tasks','odd\nname.txt','--json','--rg-json',str(saved)])
    assert any(row in rows for row in from_file if row['path']=='odd\nname.txt')
    saved.unlink()
    assert call('empty rg still searches corpus', ['request','--json','--rg-json','-'],'')
    encoded=[]
    for line in raw.splitlines():
        event=json.loads(line)
        if event['type'] in ('match','context'):
            for field in ('path','lines'):
                value=event['data'][field]['text'].encode()
                event['data'][field]={'bytes':base64.b64encode(value).decode()}
        encoded.append(json.dumps(event))
    assert call('base64 rg fields', ['parallel tasks','--json','--rg-json','-'],'\n'.join(encoded))==rows
    explicit=rg('excludedneedle','ignored.txt')
    assert any(r['path']=='ignored.txt' for r in call('explicit ignored match', ['unrelatedzz','--json','-n','100','--rg-json','-'],explicit))
    binary=rg('--text','excludedneedle','binary.txt')
    call('explicit binary rejected', ['unrelatedzz','--json','--rg-json','-'],binary,code=2)
    (root/'multiline.txt').write_bytes(b'alpha\r\nbeta\r\ngamma\r\n')
    multiline=rg('-U', 'alpha\r?\nbeta', 'multiline.txt')
    multi=call('multiline CRLF match', ['unrelatedzz','--json','-n','100','--rg-json','-'],multiline)
    assert any(r['path']=='multiline.txt' and 'alpha\nbeta\n' in r['content'] for r in multi)
    call('malformed rg', ['lease','--json','--rg-json','-'],'{broken',code=2)
    call('wrong rg fields', ['lease','--json','--rg-json','-'],json.dumps({'type':'match','data':{}}),code=2)
    (root/'odd\nname.txt').write_text('changed source\n')
    call('stale rg', ['parallel tasks','--json','--rg-json','-'],raw,code=2)
    (root/'odd\nname.txt').write_text('singleflight joins concurrent work\n')
    call('rg outside file scope', ['lease','camel.py','--json','--rg-json','-'],raw,code=2)

    raw=rg('-C','1','cached','context.txt')+rg('-C','12','shared','context.txt')
    rows=call('duplicates and overlap', ['lease renewal','--json','-n','100','--rg-json','-'],raw+raw)
    assert len({(r['path'],r['start'],r['end']) for r in rows})==len(rows)
    for r in rows:
        source=(root/r['path']).read_text().splitlines(keepends=True)
        assert r['content']==''.join(source[r['start']-1:r['end']])
    assert any('renewal completion' in r['content'] for r in rows)

    partial = rg('-C','8','cached','context.txt') + rg('-C','6','shared','context.txt')
    kept = call('partial overlaps keep unique source', ['unrelatedzz','context.txt','--json','-n','100','--rg-json','-'],partial)
    assert set(range(1,19)) <= {line for r in kept for line in range(r['start'],r['end']+1)}, kept

    args=['reconcile lease renewal ZXQ7319','ranking','--json','--explain','-n','100']
    rows=call('relative scores and lexical outlier',args)
    scores=[r['scores'] for r in rows]
    for score in scores:
        assert all(math.isfinite(v) for v in score.values())
        assert abs(score['fused']-(.25*score['bm25_relative']+.75*score['semantic_relative']))<1e-6
    lexical=next(r for r in rows if r['path']=='needle.txt')
    assert lexical['scores']['bm25_relative']==1.0
    assert any(r['scores']['semantic']>lexical['scores']['semantic'] for r in rows), rows
    assert rows.index(lexical)<5, rows
    assert call('stable across requested counts',args[:-1]+['5'])==rows[:5]
    # Two long rg passages share the same filename and prefix; only their tails differ.
    prefix = 'ordinary words ' * 900
    (root/'long.txt').write_text(prefix + 'car vehicle engine road\n\n' + prefix + 'apple orange banana fruit\n')
    raw = rg('-e', 'engine', '-e', 'banana', 'long.txt')
    long_rows = call('embedding includes complete tails', ['automobile','long.txt','--json','--explain','--rg-json','-'],raw)
    assert len(long_rows)>=2
    by_line = {r['start']:r['scores']['semantic'] for r in long_rows}
    assert abs(by_line[1]-by_line[3])>1e-7, by_line
    # Duplicate supplied passages must not alter corpus statistics or rankings.
    once = call('single supplemental input', ['automobile','long.txt','--json','--explain','--rg-json','-'],raw)
    twice = call('duplicate supplemental input', ['automobile','long.txt','--json','--explain','--rg-json','-'],raw+raw)
    assert once==twice
    (root/'only.txt').write_text('solitary token\n')
    single=call('flat scores', ['solitary','only.txt','--json','--explain'])
    assert len(single)==1 and all(math.isfinite(v) for v in single[0]['scores'].values())
    (root/'only.txt').write_text('freshreplacement token\n')
    assert call('live edits',['freshreplacement','only.txt','--json'])
    assert all('solitary' not in r['content'] for r in call('removed term',['solitary','only.txt','--json']))
print(json.dumps({'ok':True,'checks':checks},indent=2))
