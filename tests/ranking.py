"""Real CLI ranking failure contract, written before the implementation.

Exact whole identifiers must outrank fuzzy matches, even outside retrieval
shortlists. Prefix/suffix and Unicode-adjacent names must not count as exact.
Cached, uncached, and stdin-only searches must agree on the protection; stdin
must never pull in an exact match from an unsupplied file. Natural questions
must retain semantic discovery, source slices, and count-prefix stability.
"""
import json, os, shutil, subprocess, tempfile
from pathlib import Path

cli = shutil.which('sgrep')
assert cli
checks = []
with tempfile.TemporaryDirectory(prefix='sgrep-ranking-') as tmp:
    root = Path(tmp) / 'repo'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', str(root)], check=True)
    env = os.environ | {'HF_HUB_OFFLINE': '1', 'SGREP_CACHE_DIR': str(Path(tmp) / 'cache')}
    for i in range(240):
        (root / f'decoy{i:03}.txt').write_text('Timing safe equal comparison ensures that equality checks take consistent time.\n')
    (root / 'actual.txt').write_text('ordinary unrelated material ' * 5000 + ' timingSafeEqual(value, expected);\n')
    (root / 'prefix.txt').write_text('timingSafeEqualExtra timingSafeEqualExtra timingSafeEqualExtra\n')
    (root / 'unicode.txt').write_text('timingSafeEqualé étimingSafeEqual\n')
    (root / 'transport.txt').write_text('Vehicles have engines and wheels. Drivers travel along roads.\n')

    def call(name, args, stdin=None):
        p = subprocess.run([cli, *args], cwd=root, env=env, input=stdin, text=True, capture_output=True, timeout=120)
        checks.append(dict(name=name, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr))
        assert p.returncode == 0, (name, p.stderr)
        rows = json.loads(p.stdout)
        for r in rows:
            assert r['content'] == ''.join((root / r['path']).read_text().splitlines(keepends=True)[r['start']-1:r['end']])
        return rows

    args = ['timingSafeEqual', '.', '--json', '--explain', '-n', '5']
    cold = call('exact match survives shortlist', args)
    assert cold[0]['path'] == 'actual.txt', [(r['path'], r['scores']) for r in cold]
    assert call('warm cache parity', args) == cold
    assert call('uncached parity', args + ['--no-cache']) == cold
    assert call('count prefix', args[:-1] + ['1']) == cold[:1]
    raw = subprocess.run(['rg', '--json', '-e', 'timingSafeEqual', '.'], cwd=root, text=True, capture_output=True, check=True).stdout
    assert call('stdin exact protection', args + ['--stdin'], raw)[0]['path'] == 'actual.txt'
    raw = subprocess.run(['rg', '--json', 'timingSafeEqualExtra', 'prefix.txt'], cwd=root, text=True, capture_output=True, check=True).stdout
    assert {r['path'] for r in call('stdin stays within supplied scope', args + ['--stdin'], raw)} == {'prefix.txt'}
    assert call('semantic discovery remains', ['automobile', '.', '--json', '-n', '1'])[0]['path'] == 'transport.txt'
print(json.dumps({'ok': True, 'checks': checks}, indent=2))
