#!/usr/bin/env bash
# Restore one E4 visible-preview rollout from its root-only preimage receipt.
set -euo pipefail

receipt_dir="${1:?usage: e4_visible_portfolio_preview_rollback.sh <receipt-dir>}"
nginx_config="/etc/nginx/sites-available/obsidian-exchange.org"
bot_path="/opt/obsidian-exchange/bot/main_bot.py"
release_base="/opt/obsidian-exchange/releases/e4-visible-portfolio-preview"

for required in nginx.conf.preimage bot.main_bot.py.preimage previous-preview-release; do
  test -f "$receipt_dir/$required" || { echo "missing rollback evidence: $required" >&2; exit 65; }
done

previous_target="$(<"$receipt_dir/previous-preview-release")"
if test "$previous_target" = "none"; then
  rm -f "$release_base/current"
else
  test -d "$previous_target" || { echo "previous preview release missing" >&2; exit 66; }
  pointer_tmp="$release_base/.current.rollback.$$.tmp"
  ln -s "$previous_target" "$pointer_tmp"
  mv -Tf "$pointer_tmp" "$release_base/current"
fi

install -o root -g root -m 0644 "$receipt_dir/nginx.conf.preimage" "$nginx_config"
nginx -t
systemctl reload nginx

install -o root -g root -m 0644 "$receipt_dir/bot.main_bot.py.preimage" "$bot_path"
/opt/obsidian-exchange/bot/venv/bin/python3 -m py_compile "$bot_path"
systemctl restart exchange-bot.service
systemctl is-active --quiet nginx.service
systemctl is-active --quiet exchange-bot.service
printf 'rolled_back_from=%s\n' "$receipt_dir"
