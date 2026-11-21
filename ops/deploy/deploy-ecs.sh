#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

if [ "$#" -ne 2 ] || [[ ! "$1" =~ ^[0-9a-f]{40}$ ]] || [[ ! "$2" =~ ^[0-9]+-[0-9]+$ ]]; then
    printf 'Usage: acs-deploy-release COMMIT_SHA RUN_ID-ATTEMPT\n' >&2
    exit 2
fi
if [ "$(id -u)" -ne 0 ]; then
    printf 'Invoke the installed entrypoint through sudo.\n' >&2
    exit 1
fi

target=$1
run_id=$2
repo=/home/acs/ACS_Project-Literature-Research-Agent-Assistant
base=/home/acs/acs-deploy/auto
incoming="$base/incoming/$target/$run_id"
release="$base/releases/$target-$run_id"
site=/var/www/acs-frontend
helper=/usr/local/libexec/acs-deploy/release.py
uv=/home/acs/.local/bin/uv
old_python="$repo/backend/.venv/bin/python"
backup=
maintenance=0
code_switched=0
migration=not-started
services=(acs-api.service acs-runner.service acs-parser.service acs-import.service acs-mail.service)
workers=(acs-runner.service acs-parser.service acs-import.service acs-mail.service)

as_acs() {
    runuser -u acs -- env HOME=/home/acs PYTHONNOUSERSITE=1 \
        PATH=/home/acs/.local/bin:/usr/local/bin:/usr/bin:/bin "$@" 9>&-
}

failure() {
    status=$1
    trap - ERR EXIT HUP INT TERM
    if [ "$status" -eq 0 ]; then
        return
    fi
    printf '\nDeployment failed: exit=%s migration=%s backup=%s\n' "$status" "$migration" "${backup:-not-created}" >&2
    if [ "$maintenance" = 1 ] && [ "$code_switched" = 0 ]; then
        systemctl start "${services[@]}" || true
    elif [ "$maintenance" = 1 ]; then
        if systemctl stop "${services[@]}"; then
            printf 'Application services are stopped. Inspect the backup and migration before recovery.\n' >&2
        else
            printf 'Some application services could not be stopped; inspect their state immediately.\n' >&2
        fi
    fi
    exit "$status"
}
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
trap 'failure "$?"' EXIT

exec 9>/run/lock/acs-deploy.lock
flock -w 1800 9
cd "$repo/backend"
test -x "$old_python"
test -x "$uv"
test -d "$incoming"
test -d "$site"
test ! -L "$site"
test -f "$repo/backend/.env"
test "$(as_acs git -C "$repo" branch --show-current)" = main
test -z "$(as_acs git -C "$repo" status --porcelain)"
for service in "${services[@]}" nginx; do
    systemctl is-active --quiet "$service"
done
nginx -t
as_acs "$old_python" -I "$helper" verify "$incoming" "$target"
as_acs git -C "$repo" bundle verify "$incoming/source.bundle"
test "$(as_acs git -C "$repo" bundle list-heads "$incoming/source.bundle" HEAD)" = "$target HEAD"
as_acs git -C "$repo" fetch --no-tags "$incoming/source.bundle" HEAD
before=$(as_acs git -C "$repo" rev-parse HEAD)
as_acs git -C "$repo" merge-base --is-ancestor "$before" "$target"
available=$(df --output=avail -k "$base" | tail -n 1)
test "$available" -ge 2097152

backup=$(mktemp -d "/var/backups/acs/$target-$run_id-XXXXXX")
exec > >(tee -a "$backup/deploy.log") 2>&1
printf 'Preparing %s -> %s\nBackup: %s\n' "$before" "$target" "$backup"
as_acs "$old_python" -I "$helper" snapshot > "$backup/configuration.json"
as_acs mkdir -m 700 "$release"
as_acs git -C "$repo" archive --format=tar --output="$release/source.tar" "$target"
as_acs "$old_python" -I "$helper" extract "$release/source.tar" "$release/source"
as_acs "$old_python" -I "$helper" extract "$incoming/frontend.tar.gz" "$release/frontend"
test -f "$release/frontend/index.html"
test -d "$release/frontend/assets"
as_acs ln -s "$repo/backend/.env" "$release/source/backend/.env"
as_acs "$uv" venv --python "$old_python" "$release/venv"
python="$release/venv/bin/python"
as_acs "$uv" pip sync --python "$python" --no-config \
    --default-index https://pypi.org/simple --require-hashes "$incoming/requirements.txt"
as_acs "$uv" pip install --python "$python" --no-config \
    --default-index https://pypi.org/simple --no-deps --editable "$release/source/backend"
as_acs "$python" -I "$helper" snapshot > "$backup/new-configuration.json"
cmp "$backup/configuration.json" "$backup/new-configuration.json"

printf 'Deploying %s -> %s\nBackup: %s\n' "$before" "$target" "$backup"
printf '%s\n' "$before" > "$backup/previous-commit.txt"
printf '%s\n' "$release" > "$backup/release-directory.txt"
as_acs cat "$repo/backend/.env" > "$backup/backend.env"
as_acs tar -czf - -C "$site" . > "$backup/frontend.tar.gz"
cp /etc/nginx/conf.d/acs.conf "$backup/acs.conf"

maintenance=1
systemctl stop "${services[@]}"
/usr/bin/python3 -I /usr/local/libexec/acs-deploy/backup_database.py \
    "$backup/configuration.json" "$backup/database.dump"
code_switched=1
as_acs git -C "$repo" merge --ff-only "$target"
as_acs git -C "$repo" update-ref refs/remotes/origin/main "$target"
as_acs mv "$repo/backend/.venv" "$release/previous-venv"
as_acs ln -s "$release/venv" "$repo/backend/.venv"
migration=started
as_acs "$python" -m alembic -c "$release/source/backend/alembic.ini" upgrade head
as_acs "$python" -m alembic -c "$release/source/backend/alembic.ini" current
migration=completed
systemctl start acs-api.service
ready=0
for attempt in {1..60}; do
    if curl --noproxy '*' --connect-timeout 2 --max-time 5 -fsS \
        http://127.0.0.1:8000/ready > "$backup/ready.json"; then
        ready=1
        break
    fi
    sleep 1
done
test "$ready" = 1
systemctl start "${workers[@]}"
for service in "${services[@]}"; do
    systemctl is-active --quiet "$service"
done
maintenance=0

as_acs mkdir -p "$site/assets"
as_acs cp -R "$release/frontend/assets/." "$site/assets/"
as_acs find "$site/assets" -type d -exec chmod 755 '{}' +
as_acs find "$site/assets" -type f -exec chmod 644 '{}' +
while IFS= read -r -d '' entry; do
    name=$(basename "$entry")
    if [ "$name" != index.html ]; then
        as_acs install -m 644 "$entry" "$site/$name"
    fi
done < <(find "$release/frontend" -maxdepth 1 -type f -print0)
as_acs install -m 644 "$release/frontend/index.html" "$site/.index-$run_id.html"
as_acs mv -f "$site/.index-$run_id.html" "$site/index.html"
curl --noproxy '*' --connect-timeout 5 --max-time 15 -fsS \
    --resolve 8.218.149.237:443:127.0.0.1 \
    https://8.218.149.237/ > "$backup/served-index.html"
cmp "$release/frontend/index.html" "$backup/served-index.html"
curl --noproxy '*' --retry 3 --connect-timeout 5 --max-time 15 -fsS \
    https://8.218.149.237/ready
test "$(as_acs git -C "$repo" rev-parse HEAD)" = "$target"
test -z "$(as_acs git -C "$repo" status --porcelain)"
systemctl is-active "${services[@]}" nginx
printf '\nDeployment complete: %s\nBackup: %s\n' "$target" "$backup"
trap - ERR EXIT HUP INT TERM
