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

# extra monochrome wallpapers for vantablack from community forks of the theme
vb="$here/themes/vantablack/backgrounds"
ab=https://raw.githubusercontent.com/ABetancourt03/vantablack-customized/main/backgrounds
onyx=https://raw.githubusercontent.com/ggregoro/onyx/master/backgrounds
while read -r name url; do
  [[ -e $vb/$name ]] || curl -fsSL -o "$vb/$name" "$url"
done <<EOF
4-topo-waves.jpg $ab/black-and-white-waves.jpg
5-black-hole.png $ab/black-hole.png
6-misty-forest.jpg $ab/monochrome-landscape.jpg
7-lone-tree.jpg $ab/monochrome-tree.jpg
8-dark-ocean.jpg $ab/monochrone-ocean.jpg
9-street-light.jpg $onyx/Dark%20Street%20Light.jpeg
EOF
echo "  vantablack: $(ls "$vb" | wc -l) wallpapers"
