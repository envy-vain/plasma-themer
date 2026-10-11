# plasma-themer

Omarchy-style, one-keystroke theme switching for KDE Plasma 6 (Wayland). One palette per theme drives the
whole desktop: Plasma, terminals, shell, browser, editor, chat, notes and the login screen.

Themes: **Tokyo Night · Matte Black · Catppuccin Mocha · Rosé Pine · Gruvbox · Everforest · Nord · Kanagawa**
(palettes and most wallpapers from [Omarchy](https://github.com/basecamp/omarchy); Rosé Pine uses the dark
"main" palette and generated wallpapers).

## Keys

| Keys | Action |
|---|---|
| `Super+Ctrl+Shift+Space` | Overlay picker (←/→ theme, ↑/↓ wallpaper, Enter apply, Esc close, 1–8 jump) |
| `Super+Ctrl+Space` | Next wallpaper in the current theme |
| `Super+Ctrl+Alt+Space` | Next theme |

## CLI

```
themer list | pick | set <theme> | next | prev | current | reapply
themer bg [next|prev]
themer set nord --only konsole firefox     # run only some integrations
themer setup                               # hotkeys, VSCodium theme extensions, Pywalfox host
themer doctor                              # what's installed / wired up
```

## What switches

| Target | How |
|---|---|
| Plasma colors + accent | generated `.colors`, alternating ids so KDE always reloads |
| Wallpaper + lock screen | `plasma-apply-wallpaperimage`, `kscreenlockerrc` |
| Login screen | Plasma Login Manager reads `/var/lib/plasma-themer/login-background.jpg` |
| Cursor | Bibata (Ice / Amber / Classic per theme) |
| Icons | Papirus-Dark + per-user overlay that recolors folders (no root, `/usr` untouched) |
| GTK apps | follow the Plasma scheme automatically |
| Konsole | generated colorscheme, live-switched over D-Bus in every open session |
| Alacritty | imported theme file, live reload |
| fish | universal `fish_color_*` + Pure prompt colors (live in every shell), fzf, `BAT_THEME=ansi` |
| btop · tmux · vim · fastfetch | generated theme files, live where the app supports it |
| Firefox | Pywalfox for live UI colors + `userChrome.css`/`userContent.css` for shape, new-tab page, about: pages |
| VSCodium | `workbench.colorTheme` (settings file is watched → instant) |
| Vesktop | `themes/plasma-themer.css` (hot reload) |
| Obsidian | CSS snippet in every vault (hot reload) |

## Adding a theme

`themes/<slug>/colors.toml` (same keys as Omarchy), `theme.toml` (`name`, `cursor`, `folders`),
optional `vscode.json` and `backgrounds/`. Personal themes can live in `~/.config/plasma-themer/themes/`.
`tools/genwall.py <slug> --style waves|aurora|dunes` paints matching wallpapers from the palette.

## Undo

- `install/restore.sh` puts every config back from the pre-install backup
  (`~/.local/share/plasma-themer/backups/`) and removes hotkeys + icon overlay.
- `konsave -a pre-plasma-themer` restores the KDE look.
- btrfs: snapper snapshot "pre plasma-themer" for `/`, read-only snapshot in `/home/.snapshots-themer/`.
- Login screen: `sudo cp /etc/plasmalogin.conf.pre-themer /etc/plasmalogin.conf`.
