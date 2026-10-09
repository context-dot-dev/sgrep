"""Real CLI index contract, written before implementation.

Failure modes: changed content with restored mtime, replacement, deleted/added
files, ignore changes, truncated/bit-flipped cache, model switches, read-only
cache, and ranking/score drift. Compare complete JSON to the frozen executable.
"""
import json, os, subprocess, tempfile
from pathlib import Path

baseline = os.environ['SGREP_BASELINE']
candidate = os.environ['SGREP_CANDIDATE']
checks = []
with tempfile.TemporaryDirectory(prefix='sgrep-index-') as tmp:
    root = Path(tmp)/'repo'; root.mkdir()
    cache = Path(tmp)/'cache'
    subprocess.run(['git','init','-q',root],check=True)
    (root/'foo').mkdir()
    (root/'foo'/'bar').write_text('Failed requests consume credits.\n')
    (root/'foo.bar').write_text('Failed requests consume credits.\n')
    file = root/'billing.py'
    file.write_text('def should_bill(failed):\n    return not failed\n')
    (root/'fruit.txt').write_text('Apples grow on trees.\n')
    env = os.environ | {'SGREP_CACHE_DIR':str(cache),'HF_HUB_OFFLINE':'1'}
    def check(name, extra=()):
        args = ['when failed requests consume credits',str(root),'--json','--explain',*extra]
        old = subprocess.run([baseline,*args,'--no-cache'],env=env,capture_output=True,check=True)
        new = subprocess.run([candidate,*args],env=env,capture_output=True,check=True)
        assert json.loads(old.stdout)==json.loads(new.stdout), (name,old.stdout,new.stdout)
        checks.append(name)
    from concurrent.futures import ThreadPoolExecutor
    def concurrent_search(_):
        return subprocess.run([candidate, 'failed credits', str(root), '--json', '--explain'], env=env, capture_output=True, check=True).stdout
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(concurrent_search, range(4)))
    assert all(result == results[0] for result in results)
    checks.append('concurrent cache creation')
    if os.name == 'posix':
        assert all(f.stat().st_mode & 0o077 == 0 for f in cache.glob('*.bin'))
        checks.append('private cache permissions')
    check('after concurrent build'); check('warm'); check('warm new query', ['--model','code'])
    stat = file.stat()
    file.write_text(file.read_text().replace('not failed', '    failed'))
    assert file.stat().st_size == stat.st_size
    os.utime(file,ns=(stat.st_atime_ns,stat.st_mtime_ns))
    check('restored modification time')
    replacement = root/'replacement'; replacement.write_text('def free_credits():\n    return True\n')
    replacement.replace(file); check('atomic replacement')
    (root/'new.py').write_text('def consume_credits():\n    return 10\n'); check('added file')
    (root/'.gitignore').write_text('new.py\n'); check('ignore change')
    file.unlink(); check('deleted file')
    check('text model',['--model','text']); check('code model',['--model','code'])
    for f in cache.glob('*.bin'): f.write_bytes(b'broken')
    check('truncated cache')
    for f in cache.glob('*.bin'):
        b=bytearray(f.read_bytes()); b[-1]^=1; f.write_bytes(b)
    check('bit flipped cache')
print(json.dumps({'ok':True,'checks':checks},indent=2))
