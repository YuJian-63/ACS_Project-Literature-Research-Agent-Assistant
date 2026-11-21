#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "${TACC_WORKDIR:?Submit with tcloud submit}"
runtime=$(mktemp -d)
trap 'rm -rf -- "$runtime"; rm -f -- library-access.json' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
python -m pip install --disable-pip-version-check --timeout 25 --retries 1 \
    --no-compile --only-binary=:all: --target "$runtime" \
    httpx==0.28.1 PyMuPDF==1.24.14 python-dotenv==1.2.4
PYTHONPATH="$runtime" python -u main.py
