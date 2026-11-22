#!/usr/bin/env bash
set -euo pipefail

if [[ "$(uname -s)" != Linux ]]; then
  echo 'Use service-macos.sh on macOS or service-windows.ps1 on Windows.' >&2
  exit 1
fi
if ! command -v uv >/dev/null 2>&1; then
  echo 'Install uv and reopen the terminal before running this script.' >&2
  exit 1
fi

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
exec uv run --locked --inexact --project "$root/backend" \
  python "$root/scripts/service_manager.py" "${@:-start}"
