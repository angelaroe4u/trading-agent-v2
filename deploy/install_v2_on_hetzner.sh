#!/usr/bin/env bash
# install_v2_on_hetzner.sh — run ON the Hetzner box (5.161.197.162) as `angela`.
# Idempotent: rerun safely. Does NOT touch V1's running service.
#
# usage (from your laptop):
#   scp -i %USERPROFILE%\.ssh\id_ed25519_hetzner "C:\Projects\tradingap\Trading Agent 2.0\deploy\install_v2_on_hetzner.sh" angela@5.161.197.162:/tmp/
#   ssh -i %USERPROFILE%\.ssh\id_ed25519_hetzner angela@5.161.197.162 "bash /tmp/install_v2_on_hetzner.sh"
set -euo pipefail

REPO=/opt/tradingap
V2_DIR="$REPO/Trading Agent 2.0"
VENV="$REPO/venv"
SERVICE_BOT="angela-trade-fund-v2.service"
SERVICE_UI="angela-ui-v2.service"

echo "[v2 install] checking V1 layout"
test -d "$REPO" || { echo "V1 repo missing at $REPO"; exit 1; }
test -d "$V2_DIR" || { echo "V2 dir missing at $V2_DIR — git pull/sync first"; exit 1; }

echo "[v2 install] installing V2 python deps into shared venv"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -q \
    flask rank_bm25 faiss-cpu sentence-transformers tiktoken \
    || echo "[v2 install] WARN: some optional deps failed; FAISS path will skip gracefully"

echo "[v2 install] seeding V2 ledger if absent"
test -f "$V2_DIR/v2_ledger.json" || cat > "$V2_DIR/v2_ledger.json" <<EOF
{
  "settled_cash": 2000.0,
  "unsettled": [],
  "pod": [],
  "bench": [],
  "last_council_queue": [],
  "last_light_watch": "",
  "code_blue_paged": false,
  "daily_flush_blacklist": [],
  "blacklist_date": "",
  "day_start_vault": 2000.0,
  "last_deploy_date": ""
}
EOF

echo "[v2 install] installing systemd units"
sudo cp "$V2_DIR/deploy/$SERVICE_BOT" /etc/systemd/system/
sudo cp "$V2_DIR/deploy/$SERVICE_UI"  /etc/systemd/system/
sudo systemctl daemon-reload

echo "[v2 install] opening firewall for V2 dashboard (port 5001)"
sudo ufw allow 5001/tcp >/dev/null || true

echo "[v2 install] enabling + starting V2 bot service"
sudo systemctl enable --now "$SERVICE_BOT"

echo "[v2 install] enabling + starting V2 UI service"
sudo systemctl enable --now "$SERVICE_UI" || echo "[v2 install] WARN: V2 UI service start failed; bot still running"

echo "[v2 install] DONE."
echo
echo "V1: http://5.161.197.162:5000   |  V2: http://5.161.197.162:5001"
echo "Logs: sudo journalctl -u $SERVICE_BOT -f"
echo "      sudo journalctl -u angela-trade-fund -f      (V1)"
