#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
app_user=${COLLECTSTARINFO_USER:-cang_tq}
app_group=$(id -gn "$app_user")
python3 - "$repo" "$app_user" "$app_group" <<'PY'
from pathlib import Path
import sys
root, user, group = sys.argv[1:]
if any(c in root + user + group for c in '\n\r@%') or ' ' in root:
    raise SystemExit('Unsupported service path or account')
text = (Path(root) / 'deploy/collectstarinfo.service').read_text()
for key, value in [('@ROOT@', root), ('@USER@', user), ('@GROUP@', group)]:
    text = text.replace(key, value)
Path('/etc/systemd/system/collectstarinfo.service').write_text(text)
PY
systemd-analyze verify /etc/systemd/system/collectstarinfo.service
systemctl daemon-reload
systemctl enable collectstarinfo.service
ln -sfn "$repo/scripts/update-server.sh" /usr/local/sbin/update-collectstarinfo
systemctl restart collectstarinfo.service
python3 "$repo/scripts/check-health.py"
systemctl is-active --quiet collectstarinfo.service
