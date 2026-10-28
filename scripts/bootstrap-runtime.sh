#!/usr/bin/env bash
# Run once as the application account on an Internet-enabled Linux x86_64 host.
set -euo pipefail
[[ $(uname -s) == Linux && $(uname -m) == x86_64 ]] || {
  echo "This bootstrap supports Linux x86_64 only." >&2; exit 1;
}
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
runtime_home=${COLLECTSTARINFO_RUNTIME_HOME:-$HOME/.local/share/collectstarinfo}
mkdir -p "$runtime_home"
temporary=$(mktemp -d)
trap 'rm -rf "$temporary"' EXIT
python3 -m pip install --disable-pip-version-check --index-url https://pypi.tuna.tsinghua.edu.cn/simple --target "$temporary/tools" uv==0.13.6
export UV_PYTHON_INSTALL_DIR="$runtime_home/python"
"$temporary/tools/bin/uv" --no-config python install 3.12
python_bin=$("$temporary/tools/bin/uv" --no-config python find --managed-python 3.12)
if [[ ! -x "$repo/.venv/bin/python" ]]; then "$python_bin" -m venv "$repo/.venv"; fi
python3 - "$runtime_home" "$temporary" <<'PY'
import hashlib
from pathlib import Path
import subprocess
import sys
from urllib.request import urlopen
runtime, temporary = map(Path, sys.argv[1:])
version = 'v22.23.4'
filename = f'node-{version}-linux-x64.tar.xz'
base = f'https://nodejs.org/dist/{version}/'
with urlopen(base + 'SHASUMS256.txt', timeout=30) as response:
    checksums = response.read().decode().splitlines()
expected = next(line.split()[0] for line in checksums if line.split()[-1] == filename)
archive = temporary / filename
with urlopen(base + filename, timeout=120) as response, archive.open('wb') as output:
    while chunk := response.read(1024 * 1024):
        output.write(chunk)
if hashlib.sha256(archive.read_bytes()).hexdigest() != expected:
    raise SystemExit('Node.js checksum mismatch')
destination = runtime / 'node'
destination.mkdir(exist_ok=True)
subprocess.run(['tar', '-xJf', str(archive), '--strip-components=1', '-C', str(destination)], check=True)
print('Python 3.12 and checksum-verified Node.js 22 are ready.')
PY
