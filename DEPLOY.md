# V2 Deploy — Quick Card

## Prerequisites (one-time)

- V1 is already running on Hetzner at `/opt/tradingap`. Don't touch it.
- `.env` at `/opt/tradingap/.env` has working ANTHROPIC_API_KEY, GROQ_API_KEY,
  GEMINI_API_KEY, XAI_API_KEY, ALPACA_API_KEY, ALPACA_SECRET_KEY.

## Deploy V2 alongside V1

```bat
cd "C:\Projects\tradingap\Trading Agent 2.0"
deploy\install_v2_on_hetzner.bat
```

This script will:
1. scp the V2 source tree to `/opt/tradingap/Trading Agent 2.0/`.
2. SSH in and run `install_v2_on_hetzner.sh`, which installs deps into
   the shared venv, seeds `v2_ledger.json` with $2k, installs the two
   systemd units, opens port 5001, enables + starts both V2 services.
3. Tail V2 logs so the first night-guard sleep is visible.

## Verify

```
ssh -i %USERPROFILE%\.ssh\id_ed25519_hetzner angela@5.161.197.162
sudo systemctl status angela-trade-fund                # V1 — must be active
sudo systemctl status angela-trade-fund-v2             # V2 — must be active
```

Dashboards:
- V1: http://5.161.197.162:5000
- V2: http://5.161.197.162:5001

## Hard rollback (V1 untouched)

```
ssh -i %USERPROFILE%\.ssh\id_ed25519_hetzner angela@5.161.197.162
sudo systemctl disable --now angela-trade-fund-v2 angela-ui-v2
sudo rm /etc/systemd/system/angela-trade-fund-v2.service
sudo rm /etc/systemd/system/angela-ui-v2.service
sudo systemctl daemon-reload
```

## What to watch on Day 1

- `sudo journalctl -u angela-trade-fund-v2 -n 50` after the install — should
  log "night-guard sleeping until 09:20 ET".
- At 09:55 ET tomorrow: V2 logs "morning_deploy", V2 dashboard pod populates.
- `cat "/opt/tradingap/Trading Agent 2.0/comparison_ledger.jsonl" | tail -1`
  should show one decision event with `agreement_top3` and `mirror_correlation`.
- Daily email lands at 16:35 ET as usual (V1's reporter; V2 appendix is on
  the roadmap for batch 8).
