#!/bin/bash
systemctl restart relay
echo "Ретранслятор перезапущен."
systemctl status relay --no-pager
