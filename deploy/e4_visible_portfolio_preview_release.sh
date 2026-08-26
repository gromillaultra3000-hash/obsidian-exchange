#!/usr/bin/env bash
# Publish only the static E4 preview tree. Nginx routing is deliberately a
# separate, preflighted operation so this script cannot alter Relay or a money
# writer by accident.
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source_tree="$repo_root/preview/e4-visible-portfolio-preview"
release_base="/opt/obsidian-exchange/releases/e4-visible-portfolio-preview"
release_id="${1:?usage: e4_visible_portfolio_preview_release.sh <immutable-release-id>}"

case "$release_id" in
  *[!A-Za-z0-9._-]*|'') echo "invalid release id" >&2; exit 64 ;;
esac

for required in index.html assets/preview.css assets/preview.js api/v1/overview.json portfolio/index.html portfolio/portfolio.js; do
  test -f "$source_tree/$required" || { echo "missing preview asset: $required" >&2; exit 65; }
done

if rg -n -e '/api/create_order' -e '/pay/' -e '/swap/' -e '/wallet/' -e '/sell/' \
    -e '/admin/' -e 'sendData' -e 'localStorage' -e 'initData' \
    "$source_tree/index.html" "$source_tree/assets" "$source_tree/api"; then
  echo "public preview source contains a prohibited execution or identity marker" >&2
  exit 66
fi
if rg -n -e '/api/create_order' -e '/pay/' -e '/swap/' -e '/sell/' -e '/admin/' \
    -e 'sendData' -e 'localStorage' "$source_tree/portfolio"; then
  echo "personal preview contains a prohibited execution marker" >&2
  exit 66
fi
rg -q "'/api/wallet/portfolio'" "$source_tree/portfolio/portfolio.js" \
  || { echo "personal preview misses the exact read-only portfolio endpoint" >&2; exit 66; }

target="$release_base/$release_id"
current="$release_base/current"
test ! -e "$target" && test ! -L "$target" || { echo "release already exists: $target" >&2; exit 67; }

install -d -o root -g root -m 0755 "$release_base"
staging="$(mktemp -d "$release_base/.staging.XXXXXX")"
cleanup() { rm -rf "$staging"; }
trap cleanup EXIT

install -d -o root -g root -m 0755 "$staging/assets" "$staging/api/v1" "$staging/portfolio"
install -o root -g root -m 0444 "$source_tree/index.html" "$staging/index.html"
install -o root -g root -m 0444 "$source_tree/assets/preview.css" "$staging/assets/preview.css"
install -o root -g root -m 0444 "$source_tree/assets/preview.js" "$staging/assets/preview.js"
install -o root -g root -m 0444 "$source_tree/api/v1/overview.json" "$staging/api/v1/overview.json"
install -o root -g root -m 0444 "$source_tree/portfolio/index.html" "$staging/portfolio/index.html"
install -o root -g root -m 0444 "$source_tree/portfolio/portfolio.js" "$staging/portfolio/portfolio.js"

find "$staging" -type d -exec chmod 0555 {} +
find "$staging" -type f -exec chmod 0444 {} +
mv "$staging" "$target"
trap - EXIT

pointer_tmp="$release_base/.current.$$.tmp"
previous="$release_base/previous"
if test -L "$current"; then
  previous_target="$(readlink -f "$current")"
  test -d "$previous_target" || { echo "current release target is invalid" >&2; exit 68; }
  previous_tmp="$release_base/.previous.$$.tmp"
  ln -s "$previous_target" "$previous_tmp"
  mv -Tf "$previous_tmp" "$previous"
else
  previous_target=""
fi
ln -s "$target" "$pointer_tmp"
mv -Tf "$pointer_tmp" "$current"

printf 'preview_release=%s\n' "$target"
printf 'previous_preview_release=%s\n' "${previous_target:-none}"
sha256sum "$target/index.html" "$target/assets/preview.css" "$target/assets/preview.js" "$target/api/v1/overview.json" "$target/portfolio/index.html" "$target/portfolio/portfolio.js"
