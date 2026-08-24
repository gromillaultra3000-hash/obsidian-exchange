#!/bin/bash
set -eu

echo "This legacy launcher is retired: it referenced a missing payout worker." >&2
echo "Manage the production bot with: systemctl restart exchange-bot.service" >&2
exit 1
