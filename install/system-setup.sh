#!/usr/bin/env bash
# One-time system setup. Run as your normal user; it calls sudo where needed.
# Works on Arch-likes, Fedora, Debian/Ubuntu/KDE neon and openSUSE. Every step is best-effort:
# anything that can't be done here is reported and skipped, never fatal.
set -uo pipefail

say()  { printf '\033[1m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[33m  ! %s\033[0m\n' "$*"; }
ok()   { printf '\033[32m  ✓ %s\033[0m\n' "$*"; }
have() { command -v "$1" >/dev/null 2>&1; }

stamp=$(date +%Y%m%d-%H%M%S)
. /etc/os-release 2>/dev/null || true
family=unknown
case " ${ID:-} ${ID_LIKE:-} " in
  *" arch "*|*" cachyos "*|*" endeavouros "*|*" manjaro "*) family=arch ;;
  *" fedora "*|*" rhel "*)                                family=fedora ;;
  *" debian "*|*" ubuntu "*)                              family=debian ;;
  *" suse "*|*" opensuse "*)                              family=suse ;;
esac
say "distro: ${PRETTY_NAME:-unknown} ($family)"

# ------------------------------------------------------------------ 1. safety snapshots
say "1/5 safety snapshots"
if have snapper && sudo snapper list-configs 2>/dev/null | grep -q '^root\b'; then
  sudo snapper -c root create --type single --description "pre plasma-themer $stamp" --userdata important=yes \
    && ok "snapper snapshot of /"
else
  warn "no snapper root config — skipping / snapshot"
fi
if [[ $(findmnt -no FSTYPE /home 2>/dev/null) == btrfs ]] && sudo btrfs subvolume show /home >/dev/null 2>&1; then
  sudo mkdir -p /home/.snapshots-themer &&
    sudo btrfs subvolume snapshot -r /home "/home/.snapshots-themer/home-$stamp" >/dev/null &&
    ok "read-only snapshot /home/.snapshots-themer/home-$stamp"
else
  warn "/home is not a btrfs subvolume — skipping (your configs are still backed up by backup.sh)"
fi

# ------------------------------------------------------------------ 2. packages
say "2/5 packages"
# required: python jinja2 + pillow, QML runtime; nice-to-have: dbus-python, numpy (wallpaper generator), Papirus
case $family in
  arch)
    sudo pacman -S --needed --noconfirm python-jinja python-pillow python-dbus python-numpy qt6-declarative \
      papirus-icon-theme ttf-jetbrains-mono-nerd && ok "repo packages"
    aur=$(command -v paru || command -v yay || true)
    if [[ -n $aur ]]; then
      "$aur" -S --needed --noconfirm python-pywalfox vscodium-bin vesktop-bin bibata-cursor-theme-bin \
        && ok "AUR packages" || warn "some AUR packages failed"
    else
      warn "no AUR helper (paru/yay): Pywalfox/VSCodium/Vesktop/Bibata use the fallbacks below"
    fi ;;
  fedora)
    sudo dnf install -y python3-jinja2 python3-pillow python3-dbus python3-numpy qt6-qtdeclarative qt6-qtdeclarative-devel \
      papirus-icon-theme && ok "dnf packages" ;;
  debian)
    sudo apt-get update -qq
    sudo apt-get install -y python3-jinja2 python3-pil python3-dbus python3-numpy papirus-icon-theme \
      qml-qt6 qml6-module-qtquick qml6-module-qtquick-window && ok "apt packages" ;;
  suse)
    sudo zypper --non-interactive install python3-Jinja2 python3-Pillow python3-dbus-python python3-numpy \
      papirus-icon-theme qt6-declarative-tools && ok "zypper packages" ;;
  *) warn "unknown distro: install python3 jinja2 + pillow and a Qt 6 'qml' runtime yourself" ;;
esac

# Cursors: not packaged everywhere — the upstream release works for any distro (user-level, no root)
for c in Bibata-Modern-Ice Bibata-Modern-Classic Bibata-Modern-Amber; do
  if [[ ! -d /usr/share/icons/$c && ! -d $HOME/.icons/$c && ! -d $HOME/.local/share/icons/$c ]]; then
    mkdir -p "$HOME/.local/share/icons"
    curl -fsSL "https://github.com/ful1e5/Bibata_Cursor/releases/latest/download/$c.tar.xz" |
      tar -xJ -C "$HOME/.local/share/icons" && ok "$c cursor" || warn "$c download failed"
  fi
done

# Optional apps outside Arch: Flatpak where available (themer finds Flatpak configs too)
if [[ $family != arch ]] && have flatpak; then
  if ! have codium; then
    flatpak install -y --user flathub com.vscodium.codium >/dev/null 2>&1 && ok "VSCodium (Flatpak)"
  fi
  if ! have vesktop; then
    flatpak install -y --user flathub dev.vencord.Vesktop >/dev/null 2>&1 && ok "Vesktop (Flatpak)"
  fi
fi
if ! have pywalfox; then
  if have pipx; then pipx install pywalfox >/dev/null 2>&1 && ok "pywalfox (pipx)"
  else python3 -m pip install --user --break-system-packages pywalfox >/dev/null 2>&1 && ok "pywalfox (pip --user)" \
    || warn "pywalfox not installed: Firefox keeps userChrome styling but won't recolor live"; fi
fi

# ------------------------------------------------------------------ 3. login screen
say "3/5 login screen"
sudo install -d -o "$USER" -g "$(id -gn)" -m 755 /var/lib/plasma-themer
dm=$(basename "$(readlink -f /etc/systemd/system/display-manager.service 2>/dev/null)" .service)
case $dm in
  plasmalogin)
    sudo cp -n /etc/plasmalogin.conf /etc/plasmalogin.conf.pre-themer 2>/dev/null
    sudo kwriteconfig6 --file /etc/plasmalogin.conf --group Greeter --group Wallpaper --group org.kde.image \
      --group General --key Image file:///var/lib/plasma-themer/login-background.jpg && ok "Plasma Login Manager" ;;
  sddm)
    breeze=/usr/share/sddm/themes/breeze
    if [[ -d $breeze ]]; then
      [[ -e $breeze/theme.conf.user && ! -L $breeze/theme.conf.user ]] &&
        sudo cp -n "$breeze/theme.conf.user" "$breeze/theme.conf.user.pre-themer"
      printf '[General]\ntype=image\n' > /var/lib/plasma-themer/sddm-breeze.conf
      sudo ln -sfn /var/lib/plasma-themer/sddm-breeze.conf "$breeze/theme.conf.user" && ok "SDDM (Breeze theme)"
    else
      warn "SDDM without the Breeze theme — login screen not themed"
    fi ;;
  *) warn "display manager '${dm:-none}' not supported — login screen not themed" ;;
esac

say "4/5 checks"
have plasmashell && ok "$(plasmashell --version 2>/dev/null)" || warn "Plasma not found"
python3 -c 'import jinja2, PIL' 2>/dev/null && ok "python modules" || warn "python3 jinja2/pillow missing"

say "5/5 done"
