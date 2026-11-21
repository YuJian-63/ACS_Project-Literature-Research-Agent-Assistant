#!/usr/bin/env bash
set -euo pipefail
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"
umask 077
cd "$TACC_WORKDIR"

# Install on the node's local disk; keep only reports in persistent storage.
probe_home="$TACC_USERDIR/api-probe"
mkdir -p "$probe_home/runs"
probe_runtime=$(mktemp -d /tmp/api-probe.XXXXXX)
trap 'rm -rf -- "$probe_runtime"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
echo "Preparing probe dependencies for job $SLURM_JOB_ID"
python -m pip install --disable-pip-version-check --timeout 30 --retries 1 --no-compile --only-binary=:all: \
    --target "$probe_runtime" -r requirements.txt
export PYTHONPATH="$probe_runtime${PYTHONPATH:+:$PYTHONPATH}"
echo 'Starting API checks'
python -u main.py --output "$probe_home/runs/$SLURM_JOB_ID.json" "$@"
