#!/bin/sh
set -eu
cd "$(dirname "$0")"

status=0
for task in qa summary review; do
    for workflow in baseline extension; do
        printf '\nRunning %s/%s\n' "$workflow" "$task"
        if ! uv run --frozen python "$workflow.py" --task "examples/$task.json"; then
            printf 'Failed %s/%s\n' "$workflow" "$task" >&2
            status=1
        fi
    done
done
exit "$status"
