#!/usr/bin/env bash
# Source from job.sh. Cache archives in USERDIR and run Python on node-local disk.
set -euo pipefail
umask 077
runtime_root="${TACC_USERDIR:?}/acs-research/runtime"
scratch=${ACS_JOB_TMP:?}
mkdir -p "$runtime_root"
archive="$runtime_root/acs-cpython312-linux.tar.gz"
python_sha=ce4f6d0a6cfdb3bed6e44c2f9affd85943c76a42e25ad3a259002f31d6fb8a20
lock_id=$(sha256sum requirements.txt | cut -c1-16)
site_archive="$runtime_root/acs-site-$lock_id.tar.gz"

if [[ ! -f "$archive" ]]; then
    (
        flock -x 9
        [[ ! -f "$archive" ]] || exit 0
        archive_tmp=$(mktemp "$runtime_root/cpython-XXXXXX")
        trap 'rm -f -- "$archive_tmp"' EXIT
        url=https://releases.astral.sh/github/python-build-standalone/releases/download/20261026/cpython-3.12.16%2B20261026-x86_64-unknown-linux-gnu-install_only_stripped.tar.gz
        curl --fail --location --retry 2 --connect-timeout 15 --silent --show-error "$url" -o "$archive_tmp"
        printf '%s  %s\n' "$python_sha" "$archive_tmp" | sha256sum -c -
        mv -- "$archive_tmp" "$archive"
    ) 9>"$runtime_root/cpython.lock"
fi
printf '%s  %s\n' "$python_sha" "$archive" | sha256sum -c -
tar -xzf "$archive" -C "$scratch"
export ACS_AGENT_PYTHON="$scratch/python/bin/python3"

if [[ ! -f "$site_archive.sha256" ]]; then
    (
        flock -x 9
        [[ ! -f "$site_archive.sha256" ]] || exit 0
        site_tmp=$(mktemp "$runtime_root/site-XXXXXX")
        trap 'rm -f -- "$site_tmp" "$site_tmp.sha256"' EXIT
        "$ACS_AGENT_PYTHON" -m pip install --disable-pip-version-check --no-cache-dir \
            --no-compile --only-binary=:all: --target "$scratch/site" -r requirements.txt
        tar -czf "$site_tmp" --exclude bin --exclude __pycache__ -C "$scratch/site" .
        sha256sum "$site_tmp" | cut -d' ' -f1 > "$site_tmp.sha256"
        mv -- "$site_tmp" "$site_archive"
        mv -- "$site_tmp.sha256" "$site_archive.sha256"
    ) 9>"$runtime_root/site-$lock_id.lock"
fi
read -r site_sha < "$site_archive.sha256"
[[ "$site_sha" =~ ^[a-f0-9]{64}$ ]]
printf '%s  %s\n' "$site_sha" "$site_archive" | sha256sum -c -
tar --warning=no-unknown-keyword -xzf "$site_archive" -C "$scratch/python/lib/python3.12/site-packages"
