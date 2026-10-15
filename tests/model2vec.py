"""Compare real CLI embeddings against a frozen binary, saving a JSON receipt.

Failure contract: changed tokenization/unknown-token filtering, truncated long
inputs, code/text model drift, lost ordering, non-finite scores, or incompatible
existing indexes. No mocked models. Usage: BEFORE AFTER OUTPUT.json.
"""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile

before, after, output = map(Path, sys.argv[1:])
checks = []
with tempfile.TemporaryDirectory(prefix='sgrep-model2vec-') as tmp:
    root = Path(tmp) / 'corpus'
    root.mkdir()
    subprocess.run(['git', 'init', '-q', root], check=True)
    (root / 'billing.py').write_text('def charge_request(failed):\n    """Failed requests do not consume credits."""\n    return not failed\n')
    (root / 'unicode.txt').write_text('Café 東京 αβγ 😀\nRefunds and failed requests.\n')
    (root / 'long.txt').write_text('apple banana orange ' * 1500 + ' refund failed request credits ' * 1000 + '\n')
    (root / 'unknown.txt').write_text('\U0001ffff ' * 20 + '\n')
    (root / 'empty.txt').write_text('')
    env = os.environ | {'HF_HUB_OFFLINE': '1', 'SGREP_CACHE_DIR': str(Path(tmp) / 'index')}

    def run(binary, query, model, flags, stdin=None):
        command = [str(binary.resolve()), query, str(root), '--model', model,
                   '--json', '--explain', '-n', '200', *flags]
        p = subprocess.run(command, input=stdin, text=True, capture_output=True,
                           env=env, cwd=root, timeout=120)
        assert p.returncode in (0, 1), (command, p.stderr)
        return json.loads(p.stdout)

    def compare(name, old, new):
        assert [{k: v for k, v in row.items() if k != 'scores'} for row in old] == [
            {k: v for k, v in row.items() if k != 'scores'} for row in new], name
        max_delta = 0
        for a, b in zip(old, new):
            for key, value in a['scores'].items():
                actual = b['scores'][key]
                assert math.isfinite(actual), (name, key, actual)
                assert math.isclose(value, actual, abs_tol=2e-6, rel_tol=2e-6), (name, key, value, actual)
                max_delta = max(max_delta, abs(value - actual))
        checks.append({'name': name, 'results': len(new), 'max_score_delta': max_delta})

    for model in ('code', 'text'):
        for query in ('failed requests consume credits', 'Café 東京', 'charge_request', '\U0001ffff refund'):
            expected = run(before, query, model, ['--no-cache'])
            compare(f'{model}: {query}: no cache', expected, run(after, query, model, ['--no-cache']))
            run(before, query, model, ['--refresh-cache'])
            compare(f'{model}: {query}: old index', expected, run(after, query, model, []))
            compare(f'{model}: {query}: new index', expected, run(after, query, model, ['--refresh-cache']))
            compare(f'{model}: {query}: reverse index', expected, run(before, query, model, []))
        pipe = subprocess.run(['rg', '--json', '-e', '.', '.'], cwd=root, capture_output=True, text=True, check=True).stdout
        compare(f'{model}: long piped input', run(before, 'refund credits', model, ['--stdin'], pipe),
                run(after, 'refund credits', model, ['--stdin'], pipe))
        compare(f'{model}: empty pipe', run(before, 'refund', model, ['--stdin'], ''),
                run(after, 'refund', model, ['--stdin'], ''))
Path(output).write_text(json.dumps({'ok': True, 'checks': checks}, indent=2) + '\n')
print(f'{len(checks)} model2vec CLI compatibility checks passed')
