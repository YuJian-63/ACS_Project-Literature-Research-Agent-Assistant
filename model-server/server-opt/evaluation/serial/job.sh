#!/usr/bin/env bash
set -euo pipefail
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"
: "${CONDA_PREFIX:?SDK must activate proxy}"
test "$CONDA_PREFIX" = /mnt/home/public/course-envs/CSIT6000V/common/proxy
# A user-requested storage cleanup runs without activating the model runtime.
if [[ -f "$TACC_WORKDIR/storage-cleanup.json" ]]; then
    exec /usr/bin/python3 -u "$TACC_WORKDIR/clean_storage.py" run
fi
source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
trap 'rm -rf -- "$QWEN_RUN_DIR"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
cd "$TACC_WORKDIR"
QWEN_BASE_URL=$(qwen-python qwen_client.py --check-url --base-url "$(cat server-url.txt)")
export QWEN_BASE_URL
SERVICE_JOB_ID=$(tr -d '\r\n' < service-job-id.txt)
[[ "$SERVICE_JOB_ID" =~ ^[0-9]+$ ]]
printf 'SERVICE_JOB_ID=%s\nQWEN_BASE_URL=%s\n' "$SERVICE_JOB_ID" "$QWEN_BASE_URL"
measurement_mode=short
if [[ -f "$TACC_WORKDIR/measurement-mode.txt" ]]; then
    measurement_mode=$(tr -d '\r\n' < "$TACC_WORKDIR/measurement-mode.txt")
fi
case "$measurement_mode" in
    short) measurement=(cache_quality.py --trials 4) ;;
    long) measurement=(long_quality.py) ;;
    quick) measurement=(quick_quality.py) ;;
    *) echo 'measurement-mode.txt must contain short, quick or long' >&2; exit 1 ;;
esac
printf 'MEASUREMENT_MODE=%s\n' "$measurement_mode"
qwen-python -u "${measurement[@]}" --service-job-id "$SERVICE_JOB_ID" \
    --service-config "$TACC_WORKDIR/service_config.json" \
    --output-dir "$TACC_USERDIR/model-server-results/job-$SLURM_JOB_ID"
