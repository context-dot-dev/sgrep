"""Real CLI acceptance checks. Run after installing the package and ripgrep.

Failure contract: bad arguments, absent ripgrep, empty results, ignore leaks,
unsafe query/path handling, wrong source offsets, missing module-level code,
non-Python files, stale results after edits, broken offline model reuse, and
unexpected writes to the searched repository, incorrect auto model selection,
manual overrides ignored, mixed embedding spaces, and missing offline text weights.
No mocked embedding model.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time


def main():
    checks = []
    cli = shutil.which("sgrep")
    assert cli, 'install sgrep or put its binary on PATH'
    with tempfile.TemporaryDirectory(prefix="sgrep-e2e-") as tmp:
        root = Path(tmp)
        subprocess.run(["git", "init", "-q", str(root)], check=True)
        (root / ".gitignore").write_text("ignored.py\n")
        source = 'DEFAULT_TIMEOUT = 30\n\ndef read_file(path):\n    """Read a file from disk."""\n    return path.read_text()\n\ndef sort_names(names):\n    return sorted(names)\n'
        (root / "file utils.py").write_text(source)
        (root / "ignored.py").write_text('ignoredneedle = "read a file from disk"\n')
        (root / ".hidden.py").write_text('hiddenneedle = "read a file from disk"\n')
        (root / "odd\nname.js").write_text('export function retryRequest(send) { return send(); }\n')
        (root / "broken.py").write_text('def brokenSyntax(:\n    pass\n')
        (root / "nested.py").write_text('try:\n    raise ValueError()\nexcept ValueError:\n    def exceptneedle():\n        pass\n\nmatch 1:\n    case 1:\n        def matchneedle():\n            pass\n\ndef outer():\n    def innerneedle():\n        pass\n    return innerneedle\n')
        (root / "binary").write_bytes(b'\x00binaryneedle\x00')
        (root / "docs").mkdir()
        (root / "docs" / "shipping.MD").write_text("# Shipping orders\n\nDelivery takes three business days. Track your shipment with the delivery confirmation.\n")
        (root / "docs" / "returns.txt").write_text("# Returning orders\n\nRefunds are available within thirty days of purchase.\n")
        before = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}

        def run(name, args, code=0, env=None):
            start = time.perf_counter()
            p = subprocess.run([cli, *args], cwd=root, env=os.environ | (env or {}), capture_output=True, text=True, timeout=120)
            checks.append({"name":name,"exit_code":p.returncode,"seconds":time.perf_counter()-start,"stdout":p.stdout,"stderr":p.stderr})
            assert p.returncode == code, (name, p.returncode, p.stderr)
            assert "Traceback" not in p.stderr, (name, p.stderr)
            return p.stdout

        run("help", ["--help"])
        run("blank query", ["   "], 2)
        run("punctuation query", ["***"], 2)
        run("invalid model", ["read", "--model", "wrong"], 2)
        run("invalid count", ["read", "-n", "0"], 2)
        run("missing path", ["read", "missing-dir"], 2)
        run("missing ripgrep", ["read"], 2, {"PATH":str(Path(os.sys.executable).parent)})
        for name, query in [("no matches", "absentuniquezz"), ("gitignore", "ignoredneedle"), ("hidden files", "hiddenneedle"), ("binary files", "binaryneedle")]:
            assert json.loads(run(name, [query, "--json"], 1, {"HF_HUB_OFFLINE":"1"})) == []
        results = json.loads(run("semantic search", ["read a file from disk", "--json", "-n", "1"]))
        assert len(results)==1 and results[0]['path']=='file utils.py' and 'def read_file' in results[0]['content']
        for b in results:
            assert b['content']==''.join((root/b['path']).read_text().splitlines(keepends=True)[b['start']-1:b['end']])
        assert json.loads(run("forced code", ["read a file from disk", "--model", "code", "--json", "-n", "1"])) == results
        text_args = ["track shipping delivery", "docs", "--json"]
        text_results = json.loads(run("auto text", text_args))
        assert text_results and text_results[0]['path'] == 'shipping.MD'
        assert json.loads(run("forced text", text_args + ["--model", "text"])) == text_results
        assert json.loads(run("offline text", text_args, env={"HF_HUB_OFFLINE":"1"})) == text_results
        run("text model on code", ["read a file", "file utils.py", "--model", "text", "--json"])
        mixed = json.loads(run("auto mixed", ["read shipping", "--json"]))
        assert json.loads(run("code mixed", ["read shipping", "--model", "code", "--json"])) == mixed
        with tempfile.TemporaryDirectory(prefix="sgrep-empty-cache-") as cache:
            env = {"HF_HUB_CACHE":cache, "HF_HUB_OFFLINE":"1"}
            run("text cache missing offline", text_args, 2, env)
            assert not list(Path(cache).rglob('*')), 'offline search wrote to empty cache'
        assert json.loads(run("offline repeat", ["read a file from disk", "--json", "-n", "1"], env={"HF_HUB_OFFLINE":"1"})) == results
        pipe = subprocess.Popen([cli, "read a file", "--json"], cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        pipe.stdout.close()
        assert pipe.wait(timeout=120) == 0, pipe.stderr.read().decode()
        checks.append({"name":"closed output pipe","exit_code":0})
        run("text output", ["read a file", "file utils.py", "-n", "1"])
        assert 'DEFAULT_TIMEOUT' in run("module level", ["default timeout", "--json"])
        assert 'retryRequest' in run("other language and newline path", ["retry request", "odd\nname.js", "--json"])
        assert 'brokenSyntax' in run("invalid Python fallback", ["broken syntax", "broken.py", "--json"])
        for name in ('exceptneedle', 'matchneedle', 'innerneedle'):
            chunks = json.loads(run(name, [name, "nested.py", "--json"]))
            assert chunks and any(f'def {name}' in b['content'] for b in chunks)
            for b in chunks:
                assert b['content']==''.join((root/b['path']).read_text().splitlines(keepends=True)[b['start']-1:b['end']])
        run("query is not shell", ['read; $(touch PWNED)', "--json"])
        assert not (root/'PWNED').exists()
        after = {str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in root.rglob('*') if p.is_file()}
        assert before == after, 'search modified the repository'
        (root/'file utils.py').write_text('def changed():\n    return "freshneedle"\n')
        assert 'freshneedle' in run("fresh edits", ["freshneedle", "--json"], env={"HF_HUB_OFFLINE":"1"})
    print(json.dumps({"ok":True,"checks":checks}, indent=2))


if __name__ == "__main__":
    main()
