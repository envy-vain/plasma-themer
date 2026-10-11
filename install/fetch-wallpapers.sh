#!/usr/bin/env bash
# Pull theme wallpapers from upstream Omarchy (not redistributed in this repo).
set -euo pipefail
here=$(cd "$(dirname "$0")/.." && pwd)
tmp=$(mktemp -d)
trap 'rm -rf -- "$tmp"' EXIT
git clone -q --depth 1 --filter=blob:none --sparse https://github.com/basecamp/omarchy "$tmp/omarchy"
git -C "$tmp/omarchy" sparse-checkout set themes >/dev/null
for t in "$here"/themes/*/; do
  slug=$(basename "$t")
  [[ $slug == rose-pine ]] && continue   # upstream ships light Dawn wallpapers; we use generated dark ones
  [[ $slug == cachy-night ]] && continue # ours, not an Omarchy theme
  src="$tmp/omarchy/themes/$slug/backgrounds"
  [[ -d $src ]] || continue
  mkdir -p "$t/backgrounds"
  # skip the ones that are just Omarchy branding (logo wallpapers)
  find "$src" -maxdepth 1 -type f \( -name '*.jpg' -o -name '*.png' -o -name '*.webp' \) \
    ! -name 'omarchy.*' ! -name '*oma-cityscape*' ! -name '6-oma.*' -exec cp -n {} "$t/backgrounds/" \;
  echo "  $slug: $(ls "$t/backgrounds" | wc -l) wallpapers"
done
