#!/usr/bin/env bash
# plasma-themer installer. Safe to re-run.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)

# preflight: Plasma 6 + Python 3.11 (tomllib) are hard requirements
major=$(plasmashell --version 2>/dev/null | grep -oE '[0-9]+' | head -1 || true)
if [[ ${major:-0} -lt 6 ]]; then
  echo "plasma-themer needs KDE Plasma 6 (found: ${major:-none})." >&2; exit 1
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))'; then
  echo "plasma-themer needs Python 3.11 or newer." >&2; exit 1
fi

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
