#!/bin/bash
set -eu

echo "This legacy launcher is retired; the production bot is managed by systemd." >&2
echo "Use: systemctl restart exchange-bot.service" >&2
exit 1
