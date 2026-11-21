#!/usr/bin/env bash
set -euo pipefail
umask 077
: "${TACC_WORKDIR:?Submit with tcloud submit}"
: "${TACC_USERDIR:?Submit with tcloud submit}"
: "${SLURM_JOB_ID:?Submit with tcloud submit}"
: "${CONDA_PREFIX:?SDK must activate the course management environment}"
test "$CONDA_PREFIX" = /mnt/home/public/course-envs/CSIT6000V/common/proxy || {
    printf 'Unexpected SDK environment: %s\nRun setup-sdk-account.sh from the same package as this job.\n' "$CONDA_PREFIX" >&2
    exit 1
}
printf 'SDK_BOOTSTRAP=%s\n' "$CONDA_PREFIX"
project="$TACC_USERDIR/CSIT6000V-private-vllm-latency"
runtime_mode=$(tr -d '\r\n' < "$TACC_WORKDIR/runtime-mode.txt")
export QWEN_RUNTIME_MODE="$runtime_mode"
startup_snapshot() {
    if ! /usr/bin/python3 -u "$TACC_WORKDIR/startup_diagnostics.py" "$1"; then
        printf 'STARTUP_DIAGNOSTICS_UNAVAILABLE phase=%s\n' "$1"
    fi
}
startup_snapshot before-activation
case "$runtime_mode" in
    public)
        unset QWEN_PRIVATE_ENV
        mkdir -p "$project"
        source /mnt/home/public/course-envs/CSIT6000V/project/activate.sh
        ;;
    private)
        export QWEN_PRIVATE_ENV="$project/.venv"
        if [[ -d "$project/.build-in-progress" || -e "$project/.build-failed" || ! -x "$QWEN_PRIVATE_ENV/bin/python" ]]; then
            echo 'Private vLLM is not ready. Complete the private build first.' >&2
            exit 1
        fi
        source /mnt/home/public/course-envs/CSIT6000V/project-private-vllm/activate.sh
        ;;
    *) echo 'runtime-mode.txt must contain public or private' >&2; exit 1 ;;
esac
startup_snapshot after-activation
cd "$project"
printf 'RUNTIME_MODE=%s\n' "$runtime_mode"
trap 'rm -rf -- "$QWEN_RUN_DIR"' EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
# Apply the GPU selection portion of the TA's cinecontext-qwen-e2e fix.
gpu_indices=$(nvidia-smi --query-gpu=index --format=csv,noheader)
mapfile -t visible_gpus <<< "$gpu_indices"
if [[ ${#visible_gpus[@]} -ne 2 ]]; then
    echo 'Expected exactly two GPU devices in the Slurm job' >&2
    exit 1
fi
for gpu_index in "${visible_gpus[@]}"; do
    [[ "$gpu_index" =~ ^[0-9]+$ ]] || {
        printf 'Unexpected GPU index: %s\n' "$gpu_index" >&2
        exit 1
    }
done
[[ "${visible_gpus[0]}" != "${visible_gpus[1]}" ]] || {
    echo 'Expected two distinct GPU devices' >&2
    exit 1
}
export CUDA_VISIBLE_DEVICES="${visible_gpus[0]},${visible_gpus[1]}"
printf 'Runtime GPU selection: %s\n' "$CUDA_VISIBLE_DEVICES"
export QWEN_CACHE_HOME="$project/cache"
mkdir -p -m 700 "$QWEN_CACHE_HOME"
hostname
if command -v nvidia-smi >/dev/null 2>&1; then
    nvidia-smi --query-gpu=index,name,uuid,memory.total,memory.free --format=csv || true
fi
service_host=$(hostname)
if [[ "$service_host" =~ ^([0-9]+)-([0-9]+)-([0-9]+)-([0-9]+)$ ]]; then
    service_host="${BASH_REMATCH[1]}.${BASH_REMATCH[2]}.${BASH_REMATCH[3]}.${BASH_REMATCH[4]}"
fi
export QWEN_BASE_URL="http://${service_host}:8000/v1"
printf 'SERVICE_JOB_ID=%s\nSERVICE_BASE_URL=%s\n' "$SLURM_JOB_ID" "$QWEN_BASE_URL"
agent_telemetry=$(qwen-python -c 'import json,sys; print("on" if json.load(open(sys.argv[1])).get("agent_telemetry") is True else "off")' "$TACC_WORKDIR/service_config.json")
if [[ "$agent_telemetry" == on ]]; then
    [[ "$runtime_mode" == public ]] || { echo 'First Agent integration uses the public runtime' >&2; exit 1; }
    export PYTHONPATH="$TACC_WORKDIR${PYTHONPATH:+:$PYTHONPATH}"
    telemetry_uuids=$(nvidia-smi --query-gpu=uuid --format=csv,noheader)
    mapfile -t telemetry_uuid_list <<< "$telemetry_uuids"
    [[ ${#telemetry_uuid_list[@]} -eq 2 ]] || { echo 'Expected two allocated GPU UUIDs for telemetry' >&2; exit 1; }
    export QWEN_TELEMETRY_GPU_UUIDS="${telemetry_uuid_list[0]},${telemetry_uuid_list[1]}"
    export QWEN_AGENT_TELEMETRY_LOG="$TACC_USERDIR/model-server-results/agent-service-${SLURM_JOB_ID}/requests.jsonl"
    printf 'AGENT_BASE_URL=%s\nAGENT_MODEL=qwen3.8-27b\nAGENT_TELEMETRY_LOG=%s\n' "$QWEN_BASE_URL" "$QWEN_AGENT_TELEMETRY_LOG"
fi
if [[ "$runtime_mode" == public ]]; then
    qwen-python "$TACC_WORKDIR/check-public-env.py"
else
    qwen-python "$TACC_WORKDIR/check-private-env.py"
fi
qwen-python "$TACC_WORKDIR/patch_serve.py" "$QWEN_PROJECT_ROOT/serve.sh" \
    "$QWEN_RUN_DIR/serve-configured.sh" "$TACC_WORKDIR/service_config.json"
bash -n "$QWEN_RUN_DIR/serve-configured.sh"
if [[ "$runtime_mode" == private ]]; then
    qwen-python "$TACC_WORKDIR/check-gdn-kernel.py"
fi
startup_snapshot after-kernel-check
supervisor_digest=$(sha256sum "$TACC_WORKDIR/service_supervisor.py")
[[ "${supervisor_digest%% *}" == 7c19cf3c15ca8686b491b37c5179adf77cfd44dbd4ad79ad186170235a4109af ]] || {
    echo 'Use the unchanged TA service_supervisor.py from cinecontext-qwen-e2e-fix.zip.' >&2
    exit 1
}
printf 'TA_SUPERVISOR_SHA256=%s\nLIFECYCLE=ta-supervisor-deployment\n' "${supervisor_digest%% *}"
/usr/bin/python3 -u "$TACC_WORKDIR/service_supervisor.py" \
    "$QWEN_RUN_DIR/serve-configured.sh" "$TACC_WORKDIR/check.py" &
supervisor_pid=$!
forward_stop() {
    kill -"$1" "$supervisor_pid" 2>/dev/null || true
    wait "$supervisor_pid" || true
    exit "$2"
}
trap 'forward_stop TERM 143' TERM
trap 'forward_stop INT 130' INT
result=0
wait "$supervisor_pid" || result=$?
printf 'SERVICE_EXIT_CODE=%s\nPOST_SUPERVISOR_GPU_MEMORY_BEGIN\n' "$result"
nvidia-smi --query-gpu=index,uuid,memory.used,memory.free --format=csv || true
nvidia-smi --query-compute-apps=gpu_uuid,pid,process_name,used_gpu_memory --format=csv || true
printf 'POST_SUPERVISOR_GPU_MEMORY_END\n'
exit "$result"
