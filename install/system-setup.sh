#!/usr/bin/env bash
# One-time root setup. Run as your normal user; it calls sudo where needed.
set -euo pipefail
stamp=$(date +%Y%m%d-%H%M%S)

echo "==> btrfs safety snapshots"
sudo snapper -c root create --type single --description "pre plasma-themer $stamp" --userdata important=yes
sudo mkdir -p /home/.snapshots-themer
sudo btrfs subvolume snapshot -r /home "/home/.snapshots-themer/home-$stamp"

echo "==> packages"
sudo pacman -S --needed --noconfirm papirus-icon-theme ttf-jetbrains-mono-nerd
paru -S --needed --noconfirm --skipreview python-pywalfox vscodium-bin vesktop-bin bibata-cursor-theme-bin

echo "==> login screen: user-owned wallpaper dir (no sudoers rule needed)"
sudo install -d -o "$USER" -g "$USER" -m 755 /var/lib/plasma-themer
if [[ -f /etc/plasmalogin.conf ]]; then   # Plasma Login Manager
  sudo cp -n /etc/plasmalogin.conf /etc/plasmalogin.conf.pre-themer
  sudo kwriteconfig6 --file /etc/plasmalogin.conf --group Greeter --group Wallpaper --group org.kde.image \
    --group General --key Image file:///var/lib/plasma-themer/login-background.jpg
fi
