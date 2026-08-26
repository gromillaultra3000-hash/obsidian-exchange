#!/usr/bin/env bash
# Capture rollback evidence before changing the E4 preview's Nginx or bot bytes.
set -euo pipefail

receipt_root="/var/lib/obsidian-exchange/deployment-preimages"
nginx_config="/etc/nginx/sites-available/obsidian-exchange.org"
bot_path="/opt/obsidian-exchange/bot/main_bot.py"
current="/opt/obsidian-exchange/releases/e4-visible-portfolio-preview/current"

install -d -o root -g root -m 0700 "$receipt_root"
receipt_dir="$(mktemp -d "$receipt_root/e4-visible-preview-preimage.XXXXXX")"
install -o root -g root -m 0400 "$nginx_config" "$receipt_dir/nginx.conf.preimage"
install -o root -g root -m 0400 "$bot_path" "$receipt_dir/bot.main_bot.py.preimage"
if test -L "$current"; then
  readlink -f "$current" > "$receipt_dir/previous-preview-release"
else
  printf '%s\n' none > "$receipt_dir/previous-preview-release"
fi
chmod 0700 "$receipt_dir"
printf 'rollback_receipt=%s\n' "$receipt_dir"
