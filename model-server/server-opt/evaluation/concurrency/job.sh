#!/usr/bin/env bash
set -euo pipefail
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"
: "${CONDA_PREFIX:?SDK must activate proxy}"
test "$CONDA_PREFIX" = /mnt/home/public/course-envs/CSIT6000V/common/proxy
source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
trap 'rm -rf -- "$QWEN_RUN_DIR"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
cd "$TACC_WORKDIR"
QWEN_BASE_URL=$(qwen-python qwen_client.py --check-url --base-url "$(cat server-url.txt)")
export QWEN_BASE_URL
SERVICE_JOB_ID=$(tr -d '\r\n' < service-job-id.txt)
[[ "$SERVICE_JOB_ID" =~ ^[0-9]+$ ]]
CONCURRENCY_LEVEL=$(tr -d '\r\n' < concurrency-level.txt)
[[ "$CONCURRENCY_LEVEL" =~ ^(1|2|4)$ ]]
printf 'SERVICE_JOB_ID=%s\nQWEN_BASE_URL=%s\nCONCURRENCY_LEVEL=%s\n' "$SERVICE_JOB_ID" "$QWEN_BASE_URL" "$CONCURRENCY_LEVEL"
qwen-python -u concurrency_quality.py \
    --concurrency "$CONCURRENCY_LEVEL" \
    --service-job-id "$SERVICE_JOB_ID" \
    --service-config "$TACC_WORKDIR/service_config.json" \
    --output-dir "$TACC_USERDIR/model-server-results/job-$SLURM_JOB_ID"
