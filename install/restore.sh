#!/usr/bin/env bash
# Restore a backup made by backup.sh. Paths that didn't exist at backup time are removed.
# Usage: restore.sh            -> restores the OLDEST backup (the pre-install one)
#        restore.sh <file>     -> restores that backup
#        restore.sh --list
set -euo pipefail

dir="${XDG_DATA_HOME:-$HOME/.local/share}/plasma-themer/backups"
if [[ ${1:-} == --list ]]; then ls -1 "$dir"/*.tar.zst; exit; fi
file="${1:-$(ls -1 "$dir"/*.tar.zst | head -n1)}"
[[ -f $file ]] || { echo "no backup found" >&2; exit 1; }

echo "Restoring $file"
cd "$HOME"
if [[ -f $file.paths ]]; then
  backed=$(tar --zstd -tf "$file" | sed 's:/$::')
  while IFS= read -r p; do
    # path was created after the backup -> remove it
    grep -qxF "$p" <<<"$backed" || grep -q "^$p/" <<<"$backed" || rm -rf -- "$p"
  done < "$file.paths"
  # directories that existed: clear them so files themer added are gone
  while IFS= read -r p; do
    [[ -d $p ]] && grep -qxF "$p" <<<"$backed" && rm -rf -- "$p"
  done < "$file.paths"
fi
tar --zstd -xf "$file"

# things themer creates outside the backed-up paths
rm -f "$HOME"/.local/share/applications/themer-*.desktop
rm -rf "$HOME"/.local/share/icons/Themer-Papirus-*
rm -rf "$HOME"/.local/share/plasma-themer/current
for c in themer-picker.desktop themer-bg-next.desktop themer-next.desktop; do
  gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
    --method org.kde.KGlobalAccel.unregister "$c" "_launch" >/dev/null 2>&1 || true
done
if [[ -f /etc/plasmalogin.conf.pre-themer ]]; then
  echo "Login screen: run  sudo cp /etc/plasmalogin.conf.pre-themer /etc/plasmalogin.conf"
fi

# reapply to the live session
if command -v plasma-apply-colorscheme >/dev/null; then
  scheme=$(kreadconfig6 --file kdeglobals --group General --key ColorScheme 2>/dev/null || true)
  [[ -n $scheme ]] && plasma-apply-colorscheme "$scheme" >/dev/null 2>&1 || true
  cursor=$(kreadconfig6 --file kcminputrc --group Mouse --key cursorTheme 2>/dev/null || true)
  [[ -n $cursor ]] && plasma-apply-cursortheme "$cursor" >/dev/null 2>&1 || true
  icons=$(kreadconfig6 --file kdeglobals --group Icons --key Theme 2>/dev/null || true)
  /usr/lib/plasma-changeicons "${icons:-breeze-dark}" >/dev/null 2>&1 || true
  qdbus6 org.kde.KWin /KWin reconfigure >/dev/null 2>&1 || true
fi
echo "Done. Log out and back in to make sure everything picked up the old config."
