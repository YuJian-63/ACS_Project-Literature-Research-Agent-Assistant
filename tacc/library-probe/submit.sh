#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ $# != 2 ]]; then
    echo "Usage: bash submit.sh OUTBOX_DISPATCH_DIR TARGET_JSON" >&2
    exit 2
fi
probe=$(cd "$(dirname "$0")" && pwd)
agent="$probe/../../agent"
stage=$(mktemp -d "${TMPDIR:-/tmp}/acs-library-probe.XXXXXXXX")
trap 'rm -rf -- "$stage"' EXIT
mkdir "$stage/apis"
cp "$probe"/{tuxiv.conf,job.sh,main.py} "$stage/"
cp "$agent/config.py" "$stage/"
cp "$agent"/apis/{__init__,library,papers}.py "$stage/apis/"
install -m 600 "$1/library-access.json" "$stage/library-access.json"
install -m 600 "$2" "$stage/target.json"
(cd "$stage" && tcloud submit)
