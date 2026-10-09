"""Real CLI cache acceptance checks; writes a repeatable JSON receipt.

Failure contract: stale source after same-size/mtime edits, rename/delete/ignore
changes; trusting damaged model bytes; offline aliases allowing parser downloads;
cache overrides leaking into shared caches; refresh reusing old assets; warm runs
accumulating files; refresh leaving downloads after success/failure; concurrent
cold downloads producing partial assets. --online exercises real downloads.
"""
import argparse
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('binary', type=Path)
parser.add_argument('receipt', type=Path)
parser.add_argument('--online', action='store_true')
args = parser.parse_args()
cli = str(args.binary.resolve())
checks = []
model = 'models--minishlab--potion-base-8M/snapshots/bf8b056651a2c21b8d2565580b8569da283cab23'
hub = Path(os.environ.get('HF_HUB_CACHE', os.environ.get('HUGGINGFACE_HUB_CACHE', str(Path(os.environ.get('HF_HOME', str(Path.home()/'.cache/huggingface'))) / 'hub'))))


def record(name, action):
    try:
        action()
        checks.append(dict(name=name, ok=True))
    except Exception as error:
        checks.append(dict(name=name, ok=False, error=str(error)))


with tempfile.TemporaryDirectory(prefix='sgrep-cache-e2e-') as temporary:
    root = Path(temporary)
    source = root/'source'
    source.mkdir()
    subprocess.run(['git', 'init', '-q', source], check=True)
    document = source/'guide.txt'
    document.write_text('shipping oldneedle\n')
    cache = root/'hub'
    snapshot = cache/model
    snapshot.mkdir(parents=True)
    for name in ('tokenizer.json', 'model.safetensors'):
        shutil.copyfile(hub/model/name, snapshot/name)
    scratch = root/'tmp'
    scratch.mkdir()
    env = os.environ | {'HF_HUB_CACHE': str(cache), 'HF_HUB_OFFLINE': '1', 'SGREP_CACHE_DIR': str(root/'embeddings'),
                        'TREE_SITTER_LANGUAGE_PACK_CACHE_DIR': str(root/'parsers'), 'TMPDIR': str(scratch)}

    def call(*extra, code=0, overrides=None, query='shipping'):
        result = subprocess.run([cli, query, str(source), '--json', *extra],
                                env=env | (overrides or {}), capture_output=True, text=True, timeout=180)
        assert result.returncode == code, (result.returncode, result.stderr)
        return result

    def fresh_source():
        first = json.loads(call().stdout)
        assert 'oldneedle' in first[0]['content']
        stat = document.stat()
        document.write_text('shipping newneedle\n')
        os.utime(document, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert 'newneedle' in call().stdout and 'oldneedle' not in call().stdout
        renamed = source/'renamed.txt'
        document.rename(renamed)
        assert json.loads(call().stdout)[0]['path'] == 'renamed.txt'
        (source/'.gitignore').write_text('renamed.txt\n')
        assert json.loads(call(code=1).stdout) == []
        (source/'.gitignore').unlink()
        renamed.unlink()
        assert json.loads(call(code=1).stdout) == []
        document.write_text('shipping oldneedle\n')
    record('live source: same-size/mtime edit, rename, ignore, delete', fresh_source)

    def warm():
        before = {str(p.relative_to(cache)): (p.stat().st_size, p.stat().st_mtime_ns) for p in cache.rglob('*') if p.is_file()}
        for _ in range(5):
            call()
        after = {str(p.relative_to(cache)): (p.stat().st_size, p.stat().st_mtime_ns) for p in cache.rglob('*') if p.is_file()}
        assert before == after, 'warm search changed or grew the cache'
    record('warm reuse leaves cache unchanged', warm)

    def corrupt(name):
        file = snapshot/name
        good = file.read_bytes()
        damaged = bytearray(good)
        damaged[-10] ^= 1
        file.write_bytes(damaged)
        try:
            assert 'integrity' in call(code=2).stderr.lower()
        finally:
            file.write_bytes(good)
    for name in ('model.safetensors', 'tokenizer.json'):
        record(f'reject corrupted {name} offline', lambda name=name: corrupt(name))

    def parser_offline(value):
        file = source/'large.py'
        file.write_text('def shipping():\n' + '    value = "shipping"\n'*200)
        try:
            result = call(code=2, overrides={'HF_HUB_OFFLINE': value, 'TREE_SITTER_LANGUAGE_PACK_MANIFEST_URL': 'file:///nonexistent-sgrep-manifest.json'})
            assert 'parser is not cached' in result.stderr, result.stderr
            assert not list((root/'parsers').rglob('*'))
        finally:
            file.unlink()
    for value in ('1', 'true', 'YES', 'On'):
        record(f'parser offline value {value}', lambda value=value: parser_offline(value))

    def isolated():
        destination = root/'isolated'
        result = call('--cache-dir', str(destination), code=2)
        assert 'not cached' in result.stderr, result.stderr
        assert not [p for p in destination.rglob('*') if p.is_file() and p.name != '.sgrep-index.lock'], 'offline miss wrote assets or an index'
    record('cache directory isolates assets from shared caches', isolated)

    def offline_refresh():
        before = sorted(str(p) for p in root.rglob('*'))
        result = call('--fresh-assets', code=2)
        assert 'offline' in result.stderr.lower()
        assert before == sorted(str(p) for p in root.rglob('*'))
    record('offline refresh fails without writes', offline_refresh)

    if args.online:
        online = {'HF_HUB_OFFLINE': '0'}
        def refresh():
            before = {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.rglob('*') if p.is_file()}
            expected = call().stdout
            assert call('--fresh-assets', overrides=online).stdout == expected
            assert before == {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.rglob('*') if p.is_file()}
            assert not list(scratch.iterdir()), 'refresh left temporary downloads'
        record('real refresh bypasses cache, preserves rankings, cleans downloads', refresh)

        def refresh_parser():
            file = source/'large.py'
            file.write_text('def shipping():\n' + '    value = "shipping"\n'*200)
            try:
                result = call('--fresh-assets', '--model', 'code', overrides=online)
                assert any(block['path'] == 'large.py' for block in json.loads(result.stdout))
                assert not list(scratch.iterdir()), 'parser refresh left temporary downloads'
            finally:
                file.unlink()
        record('real code model and parser refresh cleans all downloaded assets', refresh_parser)

        def failed_refresh():
            call('--fresh-assets', code=2, overrides=online | {'HF_ENDPOINT': 'http://127.0.0.1:1'})
            assert not list(scratch.iterdir()), 'failed refresh left temporary downloads'
        record('failed refresh cleans temporary downloads', failed_refresh)

        def repair():
            file = snapshot/'tokenizer.json'
            good = file.read_bytes()
            file.write_bytes(b'broken')
            assert call(overrides=online).returncode == 0
            assert file.read_bytes() == good
            call()
        record('online repair replaces damaged regular snapshot file', repair)

        def concurrent_downloads():
            destination = root/'concurrent'
            def search(_):
                return call('--cache-dir', str(destination), overrides=online).stdout
            with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                outputs = list(pool.map(search, range(3)))
            assert len(set(outputs)) == 1
            assert call('--cache-dir', str(destination)).stdout == outputs[0]
        record('concurrent cold downloads and offline repeat', concurrent_downloads)

        def benchmark_refresh():
            queries = root/'queries.json'
            queries.write_text(json.dumps([dict(id='text-00', query='shipping', root=str(source))]))
            output = root/'benchmark'
            command = ['python3', str(Path(__file__).with_name('benchmark.py').resolve()), cli, cli,
                       str(queries), str(output), '--fresh-assets']
            result = subprocess.run(command, capture_output=True, text=True, env=env | online, timeout=180)
            assert result.returncode == 0, result.stderr
            summary = json.loads((output/'summary.json').read_text())
            assert summary['identical_rankings']
            assert len([r for r in summary['rows'] if r['phase'] == 'prepare']) == 2
            assert len([r for r in summary['rows'] if r['phase'] == 'panel']) == 4
            assert 'fresh disposable' in summary['cache_policy']
            assert not list(scratch.iterdir()), 'benchmark left asset caches'
            command[2] = str(root/'missing-executable')
            result = subprocess.run(command, capture_output=True, text=True, env=env | online, timeout=180)
            assert result.returncode != 0
            assert not list(scratch.iterdir()), 'failed benchmark left asset caches'
        record('eval separates preparation and cleans both caches on success/failure', benchmark_refresh)

receipt = dict(ok=all(c['ok'] for c in checks), binary=cli, binary_sha256=hashlib.sha256(Path(cli).read_bytes()).hexdigest(), online=args.online, checks=checks)
args.receipt.parent.mkdir(parents=True, exist_ok=True)
args.receipt.write_text(json.dumps(receipt, indent=2)+'\n')
print(json.dumps(receipt, indent=2))
raise SystemExit(0 if receipt['ok'] else 1)
