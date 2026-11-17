#!/usr/bin/env bash
# Stage this as job.sh beside tacc_tools_client.py (renamed main.py) and private.json.
set -euo pipefail
umask 077
: "${TACC_WORKDIR:?Submit through tcloud}"
: "${TACC_USERDIR:?Submit through tcloud}"
: "${SLURM_JOB_ID:?Submit through tcloud}"
cleanup() {
  rm -f -- "$TACC_WORKDIR/private.json"
  if [[ -n ${QWEN_RUN_DIR:-} ]]; then rm -rf -- "$QWEN_RUN_DIR"; fi
}
trap cleanup EXIT
source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
cd "$TACC_WORKDIR"
chmod 600 private.json
# The course Python has no default CA file. Keep HTTPS verification enabled.
SSL_CERT_FILE=$(qwen-python -c 'import certifi; print(certifi.where())')
export SSL_CERT_FILE
mkdir -p "$TACC_USERDIR/CSIT6000V-backend-tools-results"
result="$TACC_USERDIR/CSIT6000V-backend-tools-results/job-${SLURM_JOB_ID}.json"
printf 'TEST_JOB_ID=%s\n' "$SLURM_JOB_ID"
code=0
qwen-python -u main.py --config private.json --output "$result" || code=$?
cat "$result"
exit "$code"
