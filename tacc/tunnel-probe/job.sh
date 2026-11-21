#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "${TACC_WORKDIR:?Submit with tcloud submit}"

probe_runtime=$(mktemp -d /tmp/pdf-tunnel-probe.XXXXXX)
trap 'rm -rf -- "$probe_runtime"' EXIT
python -m pip install --disable-pip-version-check --timeout 25 --retries 1 \
    --no-compile --only-binary=:all: --target "$probe_runtime" PyMuPDF==1.24.14
export PYTHONPATH="$probe_runtime${PYTHONPATH:+:$PYTHONPATH}"
python -u main.py
