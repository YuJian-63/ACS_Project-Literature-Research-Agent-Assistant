#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

test "$(id -u)" = 0
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo=/home/acs/ACS_Project-Literature-Research-Agent-Assistant
site=/var/www/acs-frontend
for command in sudo visudo runuser flock docker nginx python3; do
    command -v "$command" >/dev/null
done
test -x "$repo/backend/.venv/bin/python"
test -x /home/acs/.local/bin/uv
test -d "$site"
test ! -L "$site"
test -z "$(find "$site" -type l -print -quit)"
for file in deploy-ecs.sh release.py backup_database.py; do
    test -f "$source_dir/$file"
    test ! -L "$source_dir/$file"
done
bash -n "$source_dir/deploy-ecs.sh"
install -d -o root -g root -m 755 /usr/local/libexec/acs-deploy
install -o root -g root -m 755 "$source_dir/deploy-ecs.sh" /usr/local/sbin/acs-deploy-release
install -o root -g root -m 644 "$source_dir/release.py" "$source_dir/backup_database.py" /usr/local/libexec/acs-deploy/
install -d -o root -g root -m 700 /var/backups/acs
for directory in /home/acs/acs-deploy/auto /home/acs/acs-deploy/auto/incoming /home/acs/acs-deploy/auto/releases; do
    install -d -o acs -g acs -m 700 "$directory"
done
chown -R --no-dereference acs:acs "$site"
temporary=$(mktemp)
trap 'rm -f -- "$temporary"' EXIT
printf 'acs ALL=(root) NOPASSWD: /usr/local/sbin/acs-deploy-release\n' > "$temporary"
visudo -cf "$temporary"
install -o root -g root -m 440 "$temporary" /etc/sudoers.d/acs-deploy
visudo -c
nginx -t
printf 'Automatic deployment entrypoint installed. No application service was restarted.\n'
