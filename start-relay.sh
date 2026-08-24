#!/bin/bash
cd /root/relay
pkill -f "python3 app.py" 2>/dev/null || true
nohup python3 app.py > relay.log 2>&1 &
echo "[$(date)] Retranslator started"
