#!/usr/bin/env bash
# plasma-themer installer. Safe to re-run.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)

echo "==> backing up current configs"
"$here/install/backup.sh" pre-install
command -v konsave >/dev/null && konsave -s pre-plasma-themer -f >/dev/null || true

if [[ ${1:-} != --no-system ]]; then
  echo "==> system setup (snapshots, packages, login screen) — asks for sudo"
  "$here/install/system-setup.sh"
fi

echo "==> wallpapers"
"$here/install/fetch-wallpapers.sh"

echo "==> linking themer into ~/.local/bin"
mkdir -p "$HOME/.local/bin"
ln -sf "$here/bin/themer" "$HOME/.local/bin/themer"

"$here/bin/themer" setup
"$here/bin/themer" doctor
echo
echo "Press Super+Ctrl+Shift+Space, or run: themer pick"
