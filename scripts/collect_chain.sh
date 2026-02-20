#!/usr/bin/env bash
# Chain price history collection: wait for >1M batch, then run 100K+ batch
set -e

PID=${1:?Usage: collect_chain.sh <pid_of_current_batch>}

echo "[$(date)] Waiting for PID $PID (>1M batch) to finish..."
while kill -0 "$PID" 2>/dev/null; do
    sleep 30
done
echo "[$(date)] >1M batch finished."

echo "[$(date)] Starting 100K+ batch..."
cd /home/openclaw/code/trading
uv run polymarket backtest collect --histories-only --min-volume 100000
echo "[$(date)] 100K+ batch complete."
