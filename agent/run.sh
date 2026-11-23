#!/bin/sh
set -eu
cd "$(dirname "$0")"

case $# in
    0) ;;
    2) export AGENT_LIBRARY_USERNAME="$1" AGENT_LIBRARY_PASSWORD="$2" ;;
    *) echo "用法: $0 [用户名 密码]" >&2; exit 2 ;;
esac
if [ "$#" -eq 2 ] || [ -n "${AGENT_LIBRARY_USERNAME:-}${AGENT_LIBRARY_PASSWORD:-}" ]; then
    if [ -z "${AGENT_LIBRARY_USERNAME:-}" ] || [ -z "${AGENT_LIBRARY_PASSWORD:-}" ]; then
        echo "请同时提供论文库用户名和密码。" >&2
        exit 2
    fi
fi

status=0
for example in examples/*.json; do
    task=${example##*/}
    task=${task%.json}
    set -- --task "$example"
    if [ -n "${AGENT_LIBRARY_USERNAME:-}" ]; then
        case "$task" in
            discovery|library-qa) set -- "$@" --library-login ;;
        esac
    fi
    for workflow in baseline extension; do
        printf '\nRunning %s/%s\n' "$workflow" "$task"
        if ! uv run --frozen python "$workflow.py" "$@"; then
            printf 'Failed %s/%s\n' "$workflow" "$task" >&2
            status=1
        fi
    done
done
exit "$status"
