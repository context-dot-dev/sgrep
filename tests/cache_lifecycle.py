"""Real-CLI cache lifecycle failures, specified before implementation.

Cached/uncached rankings must agree after same-size preserved-mtime edits,
additions, deletion, rename, ignore changes, model changes and query changes.
Refresh must replace the corpus cache while offline; no-cache must not touch it.
Corrupt/truncated/oversized entries must be recomputed without unbounded reads.
Repeated scopes and abandoned entries must respect byte/count/age limits;
cleanup must preserve unrelated files and symlink targets. Concurrent readers,
writers and eviction must not change results. Every run leaves a JSON receipt.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import traceback

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('binary', type=Path)
parser.add_argument('receipt', type=Path)
args = parser.parse_args()
cli = str(args.binary.resolve())
checks = []


def record(name, action):
    try:
        action()
        checks.append(dict(name=name, ok=True))
    except Exception:
        checks.append(dict(name=name, ok=False, error=traceback.format_exc()))


with tempfile.TemporaryDirectory(prefix='sgrep-index-e2e-') as temp:
    root = Path(temp)
    source = root/'source'
    source.mkdir()
    cache = root/'cache'
    subprocess.run(['git', 'init', '-q', source], check=True)
    document = source/'guide.txt'
    document.write_text('shipping oldneedle\n')
    env = os.environ | {'HF_HUB_OFFLINE': '1', 'SGREP_CACHE_DIR': str(cache)}

    def call(*flags, query='shipping', overrides=None):
        result = subprocess.run([cli, query, str(source), '--json', '--explain', *flags],
                                env=env | (overrides or {}), capture_output=True, text=True, timeout=120)
        assert result.returncode in (0, 1), result.stderr
        return json.loads(result.stdout)

    def entries():
        return list(cache.glob('*.bin'))

    def identical():
        assert call() == call('--no-cache')

    def freshness():
        identical()
        entry = entries()[0].read_bytes()
        header = json.loads(entry[16:16+int.from_bytes(entry[8:16], 'little')])
        assert next(stamp['digest'] for stamp in header['manifest'] if Path(stamp['path']) == Path('guide.txt')) == list(hashlib.sha256(document.read_bytes()).digest())
        for operation in ('edit', 'add', 'rename', 'ignore', 'delete'):
            if operation == 'edit':
                stat = document.stat()
                document.write_text('shipping newneedle\n')
                os.utime(document, ns=(stat.st_atime_ns, stat.st_mtime_ns))
            elif operation == 'add':
                (source/'extra.txt').write_text('shipping delivery\n')
            elif operation == 'rename':
                (source/'extra.txt').rename(source/'renamed.txt')
            elif operation == 'ignore':
                (source/'.gitignore').write_text('renamed.txt\n')
            elif operation == 'delete':
                document.unlink()
            identical()
        document.write_text('shipping oldneedle\n')
        identical()
        assert len(entries()) == 1, 'source generations accumulated'
    record('freshness across source and ignore changes', freshness)

    def reuse():
        before = {p.name: p.read_bytes() for p in entries()}
        call(query='delivery')
        assert before == {p.name: p.read_bytes() for p in entries()}
        for p in entries():
            os.utime(p, (time.time()-60, time.time()-60))
        call()
        assert all(time.time()-p.stat().st_mtime < 5 for p in entries()), 'hits did not update recency'
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in entries()}
        call('--no-cache')
        assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in entries()}
        assert call('--model', 'code') == call('--model', 'code', '--no-cache')
        assert len(entries()) == 2
    record('query reuse, access recency, no-cache isolation, model separation', reuse)

    def refresh():
        call('--model', 'text')
        for p in entries():
            os.utime(p, (time.time()-60, time.time()-60))
        before = {p.name: p.stat().st_ino for p in entries()}
        assert call('--refresh-cache') == call('--no-cache')
        assert any(p.stat().st_ino != before[p.name] for p in entries()), 'refresh reused the valid index'
        assert call() == call('--no-cache')
    record('offline refresh bypasses and replaces existing search index', refresh)

    def corrupt():
        for payload in (b'bad', b'\0'*1088, None):
            for p in entries():
                if payload is None:
                    with p.open('wb') as stream:
                        stream.truncate(1024**3)
                else:
                    p.write_bytes(payload)
            identical()
        assert sum(p.stat().st_size for p in entries()) <= 256*1024**2
    record('corrupt and sparse 1 GiB entries recover within budget', corrupt)

    def bounded():
        keep = cache/'do-not-delete.txt'
        keep.write_text('unrelated')
        external = root/'outside.bin'
        external.write_bytes(b'outside')
        symlink = cache/('f'*64+'.bin')
        symlink.symlink_to(external)
        for i in range(140):
            entry = cache/(f'{i:064x}'+'.bin')
            entry.write_bytes(b'x'*2048)
            os.utime(entry, (time.time()-120, time.time()-120))
        old = cache/('e'*64+'.bin')
        old.write_bytes(b'old')
        os.utime(old, (time.time()-31*86400, time.time()-31*86400))
        abandoned = cache/'sgrep-index-abandoned.tmp'
        abandoned.write_bytes(b'partial')
        call(overrides={'SGREP_CACHE_MAX_BYTES': '8192'})
        regular = [p for p in entries() if not p.is_symlink()]
        assert sum(p.stat().st_size for p in regular) <= 8192
        assert len(regular) <= 128
        assert not old.exists() and not abandoned.exists()
        assert keep.read_text() == 'unrelated' and external.read_bytes() == b'outside'
        assert symlink.is_symlink(), 'cleanup traversed or removed an unowned symlink'
        for i in range(140):
            (cache/(f'{i:064x}'+'.bin')).write_bytes(b'x')
        call()
        assert len([p for p in entries() if not p.is_symlink()]) <= 128
    record('byte, entry and age caps; temp cleanup; unrelated files preserved', bounded)

    def oversized():
        isolated = root/'tiny-budget'
        options = {'SGREP_CACHE_DIR': str(isolated), 'SGREP_CACHE_MAX_BYTES': '100'}
        assert call(overrides=options) == call('--no-cache')
        assert not list(isolated.glob('*.bin'))
        disabled = root/'disabled'
        assert call(overrides=options | {'SGREP_CACHE_DIR': str(disabled), 'SGREP_CACHE_MAX_BYTES':'0'}) == call('--no-cache')
        assert not disabled.exists()
    record('oversized corpus skips cache; zero budget writes nothing', oversized)

    def concurrent_access():
        expected = call('--no-cache')
        def search(i):
            return call(*(['--refresh-cache'] if i%2 else []), overrides={'SGREP_CACHE_MAX_BYTES':'8192'})
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            assert all(result == expected for result in pool.map(search, range(18)))
        assert sum(p.stat().st_size for p in entries() if not p.is_symlink()) <= 8192
    record('concurrent cache hits, refreshes and eviction preserve results', concurrent_access)

    def evaluation():
        queries = root/'queries.json'
        queries.write_text(json.dumps([dict(id='text-00', query='shipping', root=str(source))]))
        scratch = root/'eval-tmp'
        scratch.mkdir()
        output = root/'eval-results'
        before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in entries()}
        command = ['python3', str(Path(__file__).with_name('benchmark.py').resolve()), cli, cli,
                   str(queries), str(output), '--refresh-cache']
        result = subprocess.run(command, capture_output=True, text=True, env=env | {'TMPDIR':str(scratch)}, timeout=120)
        assert result.returncode == 0, result.stderr
        summary = json.loads((output/'summary.json').read_text())
        assert summary['identical_rankings']
        assert len([r for r in summary['rows'] if r['phase'] == 'prepare']) == 2
        assert len([r for r in summary['rows'] if r['phase'] == 'panel']) == 4
        assert 'shared assets' in summary['cache_policy']
        assert not list(scratch.iterdir())
        assert before == {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in entries()}
    record('offline eval refresh isolates caches and separates preparation timing', evaluation)

receipt = dict(ok=all(c['ok'] for c in checks), binary=cli,
               binary_sha256=hashlib.sha256(Path(cli).read_bytes()).hexdigest(), checks=checks)
args.receipt.parent.mkdir(parents=True, exist_ok=True)
args.receipt.write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt, indent=2))
raise SystemExit(0 if receipt['ok'] else 1)
