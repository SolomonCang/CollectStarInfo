#!/usr/bin/env bash
set -euo pipefail
[[ $(id -u) -eq 0 ]] || { echo "Run with sudo." >&2; exit 1; }
[[ $# -eq 0 || ( $# -eq 1 && $1 == --no-pull ) ]] || {
  echo "Usage: update-server.sh [--no-pull]" >&2; exit 1;
}
repo=$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)
app_user=${COLLECTSTARINFO_USER:-cang_tq}
exec 9>/run/lock/collectstarinfo-update.lock
flock -n 9 || { echo "Another CollectStarInfo update is running." >&2; exit 1; }
if [[ ${1:-} != --no-pull ]]; then
  [[ -z $(sudo -H -u "$app_user" git -C "$repo" status --porcelain) ]] || {
    echo "Server source has local changes; resolve them before updating." >&2; exit 1;
  }
  [[ $(sudo -H -u "$app_user" git -C "$repo" branch --show-current) == main ]] || {
    echo "Server checkout must be on main." >&2; exit 1;
  }
  sudo -H -u "$app_user" git -C "$repo" fetch origin main
  sudo -H -u "$app_user" git -C "$repo" merge --ff-only origin/main
  [[ $(sudo -H -u "$app_user" git -C "$repo" rev-parse HEAD) == \
     $(sudo -H -u "$app_user" git -C "$repo" rev-parse origin/main) ]] || {
    echo "Server main contains commits absent from GitHub; resolve them first." >&2; exit 1;
  }
fi
sudo -H -u "$app_user" bash "$repo/scripts/prepare-app.sh"
bash "$repo/scripts/install-service.sh"
echo "CollectStarInfo deployed successfully."
