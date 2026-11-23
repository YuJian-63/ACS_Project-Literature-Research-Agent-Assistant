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

exec uv run --frozen python -u ablation.py
