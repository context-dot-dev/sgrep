from pathlib import Path
import json, time
import modal

B = Path(__file__).resolve().parent
app = modal.App.lookup('sgrep-swe-benchmark-20261012', create_if_missing=True)
volume = modal.Volume.from_name('sgrep-benchmark-tools-20261012', create_if_missing=True)
image = (modal.Image.from_registry('ubuntu:22.04', add_python='3.12')
    .apt_install('build-essential', 'pkg-config', 'libssl-dev', 'curl', 'git', 'ripgrep', 'xz-utils', 'ca-certificates')
    .add_local_dir(B/'vendor/sgrep', '/src/sgrep', copy=True))
script = r'''
set -euxo pipefail
mkdir -p /bench-tools/bin /bench-tools/cache /bench-tools/npm
export HOME=/bench-tools/home
mkdir -p "$HOME"
curl -fsSL https://nodejs.org/dist/v22.15.0/node-v22.15.0-linux-x64.tar.xz | tar -xJ -C /bench-tools
export PATH=/bench-tools/node-v22.15.0-linux-x64/bin:$PATH
npm install --prefix /bench-tools/npm @dzhng/jevgrep@0.8.0 @beaconbay/ck-search@0.8.1
ln -sf /bench-tools/node-v22.15.0-linux-x64/bin/node /bench-tools/bin/node
ln -sf /bench-tools/npm/node_modules/.bin/ck /bench-tools/bin/ck
ln -sf /bench-tools/npm/node_modules/.bin/jg /bench-tools/bin/jg
cp /usr/bin/rg /bench-tools/bin/rg
curl -fsSL https://github.com/lightonai/next-plaid/releases/download/v1.8.5/colgrep-x86_64-unknown-linux-gnu.tar.xz -o /tmp/colgrep.tar.xz
curl -fsSL https://github.com/lightonai/next-plaid/releases/download/v1.8.5/colgrep-x86_64-unknown-linux-gnu.tar.xz.sha256 -o /tmp/colgrep.sha256
python -c "import hashlib,pathlib; assert hashlib.sha256(pathlib.Path('/tmp/colgrep.tar.xz').read_bytes()).hexdigest() == pathlib.Path('/tmp/colgrep.sha256').read_text().split()[0]"
tar -tJf /tmp/colgrep.tar.xz
mkdir -p /bench-tools/colgrep
tar -xJf /tmp/colgrep.tar.xz -C /bench-tools/colgrep
find /bench-tools/colgrep -type f -name colgrep -exec ln -sf '{}' /bench-tools/bin/colgrep \;
curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain 1.90.0
export PATH="$HOME/.cargo/bin:/bench-tools/bin:$PATH"
cd /src/sgrep
cargo build --release --locked -j 4
cp target/release/sgrep /bench-tools/bin/sgrep
sgrep --version
jg --version
sha256sum /bench-tools/bin/sgrep /tmp/colgrep.tar.xz
printf 'DONE\n' > /bench-tools/READY
'''
t = time.monotonic()
with modal.enable_output():
    sb = modal.Sandbox.create(app=app, image=image, volumes={'/bench-tools':volume}, cpu=4, memory=8192, timeout=1800)
    (B/'builder.json').write_text(json.dumps({'sandbox_id':sb.object_id,'started':time.time()}))
    try:
        p = sb.exec('bash','-lc',script,timeout=1700)
        out=p.stdout.read(); err=p.stderr.read();p.wait()
        (B/'build-tools.stdout').write_text(out)
        (B/'build-tools.stderr').write_text(err)
        print(out[-3000:],err[-3000:],flush=True)
        (B/'build-tools-result.json').write_text(json.dumps({'exit_code':p.returncode,'seconds':time.monotonic()-t,'sandbox_id':sb.object_id}))
    finally:
        sb.terminate()
