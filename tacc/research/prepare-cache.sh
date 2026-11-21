#!/usr/bin/env bash
# Build the optional Linux CPU runtime archives on a workstation with uv and Python 3.
set -euo pipefail
output=${1:?Pass a directory for the public runtime archives}
mkdir -p "$output"
output=$(cd "$output" && pwd)
cd "$(dirname "$0")"
scratch=$(mktemp -d)
trap 'rm -rf -- "$scratch"' EXIT
python3 - "$output" "$scratch" <<'PY'
import hashlib
import shutil
import sys
from pathlib import Path
from urllib.request import urlopen

out, tmp = map(Path, sys.argv[1:])
archive = out / "acs-cpython312-linux.tar.gz"
digest = "ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20"
if not archive.exists() or hashlib.sha256(archive.read_bytes()).hexdigest() != digest:
    url = ("https://releases.astral.sh/github/python-build-standalone/releases/download/20261026/"
           "cpython-3.12.16%2B20261026-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz")
    download = tmp / archive.name
    with urlopen(url, timeout=90) as response, download.open("wb") as dest:
        shutil.copyfileobj(response, dest)
    if hashlib.sha256(download.read_bytes()).hexdigest() != digest:
        raise SystemExit("CPython release checksum mismatch")
    shutil.move(download, archive)
PY
uv pip install --target "$scratch/site" --python-version 3.12.16 \
    --python-platform x86_64-manylinux_2_17 --only-binary=:all: -r requirements.txt
lock_id=$(python3 -c 'import hashlib; print(hashlib.sha256(open("requirements.txt", "rb").read()).hexdigest()[:16])')
site="$output/acs-site-$lock_id.tar.gz"
COPYFILE_DISABLE=1 tar --no-xattrs -czf "$site" --exclude .lock --exclude bin --exclude __pycache__ -C "$scratch/site" .
python3 - "$site" <<'PY'
import hashlib, sys
from pathlib import Path
archive = Path(sys.argv[1])
Path(str(archive) + ".sha256").write_text(hashlib.sha256(archive.read_bytes()).hexdigest() + "\n")
PY
printf 'Prepared %s, %s and %s.sha256\n' "$output/acs-cpython312-linux.tar.gz" "$site" "$site"
