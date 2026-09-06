#!/bin/bash
# Install reviewed automation bytes without starting/enabling the writer.
set -euo pipefail
test "$(id -u)" = 0
repo_dir=$(cd -- "$(dirname -- "$0")/.." && pwd)
install_dir=/usr/local/lib/obsidian-roadmap-autopilot
unit_file=/etc/systemd/system/obsidian-roadmap-autopilot.service
if systemctl is-active --quiet obsidian-roadmap-autopilot.service; then
    echo 'Stop the active autopilot before replacing automation.' >&2
    exit 1
fi
install -d -o root -g root -m 0700 /var/lib/obsidian-roadmap-autopilot
exec 9>/var/lib/obsidian-roadmap-autopilot/writer.lock
flock -n 9 || { echo 'Shared writer lock is held; installation stopped.' >&2; exit 1; }
backup_dir=$(mktemp -d /var/lib/obsidian-roadmap-autopilot/install-preimage.XXXXXX)
if test -d "$install_dir"; then cp -a "$install_dir" "$backup_dir/package"; fi
if test -f "$unit_file"; then cp -a "$unit_file" "$backup_dir/unit.service"; fi
install -d -o root -g root -m 0755 "$install_dir"
install -o root -g root -m 0644 "$repo_dir/scripts/obsidian_roadmap_autopilot.py" "$install_dir/obsidian_roadmap_autopilot.py"
install -o root -g root -m 0644 "$repo_dir/deploy/obsidian-roadmap-autopilot/iteration-prompt.md" "$install_dir/iteration-prompt.md"
install -o root -g root -m 0644 "$repo_dir/deploy/obsidian-roadmap-autopilot/iteration.schema.json" "$install_dir/iteration.schema.json"
install -o root -g root -m 0644 "$repo_dir/deploy/systemd/obsidian-roadmap-autopilot.service" "$unit_file"
systemd-analyze verify "$unit_file"
systemctl daemon-reload
echo 'Installed, not started or enabled. Arm only after the interactive writer has finished.'
echo "Install rollback preimage: $backup_dir"
echo "Status: python3 $install_dir/obsidian_roadmap_autopilot.py status"
echo 'Stop: systemctl stop obsidian-roadmap-autopilot.service'
