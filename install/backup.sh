#!/usr/bin/env bash
# Snapshot every user config plasma-themer touches, so restore.sh can put it all back.
# Usage: backup.sh [label]   -> ~/.local/share/plasma-themer/backups/<timestamp>-<label>.tar.zst
set -euo pipefail

label="${1:-manual}"
dest="${XDG_DATA_HOME:-$HOME/.local/share}/plasma-themer/backups"
mkdir -p "$dest"
out="$dest/$(date +%Y%m%d-%H%M%S)-$label.tar.zst"

ff_profile() {
  local ini="$HOME/.config/mozilla/firefox/installs.ini" base="$HOME/.config/mozilla/firefox"
  [[ -f $ini ]] || { ini="$HOME/.mozilla/firefox/installs.ini"; base="$HOME/.mozilla/firefox"; }
  [[ -f $ini ]] && echo "$base/$(grep -m1 '^Default=' "$ini" | cut -d= -f2)"
}

cd "$HOME"
paths=(
  # Plasma / KDE
  .config/kdeglobals .config/kwinrc .config/plasmarc .config/plasmashellrc
  .config/plasma-org.kde.plasma.desktop-appletsrc .config/kscreenlockerrc
  .config/kcminputrc .config/kglobalshortcutsrc .config/khotkeysrc .config/ksplashrc
  .config/konsolerc .config/breezerc .config/Trolltech.conf
  .local/share/color-schemes .local/share/konsole .local/share/plasma
  .local/share/icons .local/share/wallpapers .local/share/kxmlgui5
  # GTK
  .config/gtk-3.0 .config/gtk-4.0 .gtkrc-2.0 .config/xsettingsd
  # Terminals + CLI
  .config/alacritty .config/btop .config/fastfetch .config/fish .config/starship.toml
  .config/bat .tmux.conf .config/tmux .vimrc .vim/colors
  # Apps
  .config/VSCodium/User/settings.json .config/vesktop/settings .config/vesktop/themes
  .config/plasma-themer .local/bin/themer
  .mozilla/native-messaging-hosts .config/mozilla/native-messaging-hosts
)
ff=$(ff_profile || true)
if [[ -n ${ff:-} ]]; then
  rel="${ff#"$HOME"/}"
  for f in chrome user.js prefs.js xulstore.json; do paths+=("$rel/$f"); done
fi
# Obsidian vault snippets + appearance
while IFS= read -r v; do
  paths+=("${v#"$HOME"/}/snippets" "${v#"$HOME"/}/appearance.json")
done < <(find "$HOME" -maxdepth 4 -type d -name .obsidian -not -path '*/.cache/*' 2>/dev/null)

existing=()
for p in "${paths[@]}"; do [[ -e $p ]] && existing+=("$p"); done

tar --zstd -cf "$out" "${existing[@]}"
# manifest of what did NOT exist, so restore can delete files themer created
printf '%s\n' "${paths[@]}" > "$out.paths"
echo "$out"
