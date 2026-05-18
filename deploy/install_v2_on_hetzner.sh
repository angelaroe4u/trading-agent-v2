#!/usr/bin/env bash
# install_v2_on_hetzner.sh — idempotent V2 install on the Hetzner box.
set -euo pipefail

REPO=/opt/tradingap
V2_DIR="$REPO/Trading Agent 2.0"
VENV="$REPO/venv"
SERVICE_BOT="angela-trade-fund-v2.service"
SERVICE_UI="angela-ui-v2.service"

echo "[v2 install] checking V1 layout"
test -d "$REPO" || { echo "V1 repo missing at $REPO"; exit 1; }
test -d "$V2_DIR" || { echo "V2 dir missing at $V2_DIR"; exit 1; }

echo "[v2 install] installing V2 python deps into shared venv"
"$VENV/bin/pip" install --upgrade pip >/dev/null
"$VENV/bin/pip" install -q \
    flask rank_bm25 faiss-cpu sentence-transformers tiktoken \
    || echo "[v2 install] WARN: some optional deps failed (heavy ML stack is OK to skip)"

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

echo "[v2 install] confirming background_pictures landed"
if [ -d "$V2_DIR/background_pictures" ]; then
  ls -1 "$V2_DIR/background_pictures" | head
else
  echo "  !! background_pictures NOT FOUND on box — dashboard will have no backgrounds"
fi

echo "[v2 install] installing systemd units"
sudo cp "$V2_DIR/deploy/$SERVICE_BOT" /etc/systemd/system/
sudo cp "$V2_DIR/deploy/$SERVICE_UI"  /etc/systemd/system/
sudo systemctl daemon-reload

echo "[v2 install] opening firewall for V2 dashboard (port 5001)"
sudo ufw allow 5001/tcp >/dev/null || true

echo "[v2 install] enabling services (won't restart if already running)"
sudo systemctl enable "$SERVICE_BOT" >/dev/null 2>&1 || true
sudo systemctl enable "$SERVICE_UI"  >/dev/null 2>&1 || true

# *** the bug fix: ALWAYS restart, so Flask reloads dashboard_v2.py ***
echo "[v2 install] RESTARTING both V2 services so Python picks up new source"
sudo systemctl restart "$SERVICE_BOT"
sudo systemctl restart "$SERVICE_UI"

sleep 2
echo "[v2 install] post-restart status:"
sudo systemctl is-active "$SERVICE_BOT" | sed 's/^/  bot: /'
sudo systemctl is-active "$SERVICE_UI"  | sed 's/^/  ui : /'

echo "[v2 install] DONE."
echo "V1: http://5.161.197.162:5000   |  V2: http://5.161.197.162:5001"
