"""CLI acceptance: Unicode offsets, malformed syntax, source coverage and text routing.
Run with sgrep on PATH; emits repeatable JSON receipts. No mocked embeddings.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

cli = shutil.which('sgrep')
assert cli
receipts = []
with tempfile.TemporaryDirectory(prefix='sgrep-chunks-') as tmp:
    root = Path(tmp)
    for ext in ['py', 'c', 'cpp', 'go', 'java', 'rs', 'ts', 'tsx', 'js', 'MD', 'txt', 'unknown']:
        for name, text in {
            'unicode': '// café 中文 🦛\n' * 250 + 'terminalneedle\n',
            'long': 'needle ' + '🦛abc ' * 3000 + 'terminalneedle\n',
            'malformed': 'def broken(:\r\n' + '    # padding\r\n' * 220 + 'terminalneedle',
        }.items():
            file = root / f'{name}.{ext}'
            file.write_bytes(text.encode())
            p = subprocess.run([cli, 'terminalneedle', str(file), '--json', '--model', 'code', '-n', '50'], capture_output=True, text=True, env=os.environ | {'HF_HUB_OFFLINE':'1'}, timeout=60)
            assert p.returncode == 0, (file, p.stderr)
            blocks = json.loads(p.stdout)
            assert any('terminalneedle' in b['content'] for b in blocks), file
            lines = text.replace('\r\n', '\n').splitlines(keepends=True)
            for b in blocks:
                assert b['content'] == ''.join(lines[b['start']-1:b['end']]), file
            assert file.read_bytes() == text.encode(), file
            receipts.append({'fixture': file.name, 'blocks': blocks})
    # Golden line ranges from Chonkie 1.7.0 CodeChunker, character/2048.
    for ext, expected in [('py', [(1, 162), (163, 300)]), ('rs', [(1, 164), (165, 328), (329, 400)])]:
        text = ''.join(
            f'def needle_{i}():\n    return "café 🦛"\n\n' if ext == 'py'
            else f"fn needle_{i}() -> &'static str {{\n    \"café 🦛\"\n}}\n\n"
            for i in range(100)
        )
        file = root / f'golden.{ext}'
        file.write_text(text)
        p = subprocess.run([cli, 'needle', str(file), '--json', '--model', 'code', '-n', '50'], capture_output=True, text=True, env=os.environ | {'HF_HUB_OFFLINE':'1'}, timeout=60)
        assert p.returncode == 0, p.stderr
        blocks = json.loads(p.stdout)
        assert sorted((b['start'], b['end']) for b in blocks) == expected, blocks
        receipts.append({'fixture':file.name, 'blocks':blocks})
    file = root / 'offline.py'
    file.write_text('terminalneedle = 1\n' * 300)
    cache = root / 'empty-parser-cache'
    env = os.environ | {'HF_HUB_OFFLINE':'1', 'TREE_SITTER_LANGUAGE_PACK_CACHE_DIR':str(cache)}
    p = subprocess.run([cli, 'terminalneedle', str(file), '--json'], capture_output=True, text=True, env=env, timeout=10)
    assert p.returncode == 2 and 'parser is not cached' in p.stderr, p.stderr
    assert not list(cache.rglob('*')), 'offline search wrote parser files'
    receipts.append({'fixture':'missing offline parser', 'stderr':p.stderr})
print(json.dumps({'ok': True, 'checks': receipts}, indent=2))
