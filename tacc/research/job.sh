#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "${TACC_WORKDIR:?Submit with tcloud submit}"
if [[ "${1:-}" == --execute ]]; then
    source ./runtime.sh
    export PYTHONPATH="$TACC_WORKDIR/agent"
    export ACS_MODEL_CONFIG="$TACC_WORKDIR/model.env"
    if [[ ! -f "$ACS_MODEL_CONFIG" ]]; then
        export ACS_MODEL_CONFIG="$TACC_USERDIR/acs-research/model.env"
    fi
    exec "$ACS_AGENT_PYTHON" -u run_job.py
fi
bootstrap_python=$(command -v python)
started=0
export ACS_JOB_TMP
ACS_JOB_TMP=$(mktemp -d)
finish() {
    status=$?
    rm -rf -- "$ACS_JOB_TMP"
    if (( !started && status == 73 )); then
        return  # A different active job owns these files in the shared work directory.
    fi
    if (( started && status != 0 )); then
        "$bootstrap_python" run_job.py --bootstrap-failed || true
    fi
    rm -f -- model.env library-access.json
}
trap finish EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
seconds=$("$bootstrap_python" run_job.py --start)
started=1
timeout --kill-after=5 "$seconds" bash "$TACC_WORKDIR/job.sh" --execute
