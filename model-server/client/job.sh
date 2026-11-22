#!/usr/bin/env bash
set -euo pipefail
echo "VERIFY_STARTED_AT=$(date +%s)"
cd "${TACC_WORKDIR:?}"
exec /usr/bin/python3 -u main.py
