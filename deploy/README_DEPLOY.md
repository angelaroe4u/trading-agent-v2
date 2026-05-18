# Deploying V2 on the same Hetzner CCX23 as V1

V1 stays exactly where it is. V2 runs as a sibling systemd service on the
same box, sharing the same Python virtualenv (`/opt/tradingap/venv`) and
the same `.env` (so the existing Anthropic / Groq / Gemini / Alpaca keys
are automatically reused).

## What gets installed

| Artifact | Where | Owns |
|---|---|---|
| V2 code | `/opt/tradingap/Trading Agent 2.0/` | All V2 modules |
| V2 ledger | `/opt/tradingap/Trading Agent 2.0/v2_ledger.json` | V2 cash/pod/unsettled |
| V2 trade log | `/opt/tradingap/Trading Agent 2.0/v2_trade_log.jsonl` | V2 fills |
| V2 bot service | `/etc/systemd/system/angela-trade-fund-v2.service` | The main loop |
| V2 dashboard service | `/etc/systemd/system/angela-ui-v2.service` | Flask on :5001 |
| Comparison ledger | `/opt/tradingap/Trading Agent 2.0/comparison_ledger.jsonl` | V1↔V2 decision events |

## One-shot deploy from your laptop

```bat
cd "C:\Projects\tradingap\Trading Agent 2.0"
deploy\install_v2_on_hetzner.bat
```

This will:
1. Sync the V2 source tree to `/opt/tradingap/Trading Agent 2.0/` via scp.
2. SSH in and run `install_v2_on_hetzner.sh`, which:
   - installs the extra V2 pip deps into the shared venv
   - seeds `v2_ledger.json` with $2k (if it doesn't already exist)
   - installs the two systemd units
   - opens port 5001 on the firewall
   - enables + starts both services
3. Tails V2 logs so you can watch the first wakeup.

## Verifying it's running

```
ssh -i %USERPROFILE%\.ssh\id_ed25519_hetzner angela@5.161.197.162

sudo systemctl status angela-trade-fund            # V1
sudo systemctl status angela-trade-fund-v2         # V2

# Live logs side-by-side
sudo journalctl -u angela-trade-fund -f &
sudo journalctl -u angela-trade-fund-v2 -f
```

Dashboards:

- V1: `http://5.161.197.162:5000`
- V2: `http://5.161.197.162:5001`

## Rollback (kill V2, leave V1 untouched)

```
sudo systemctl disable --now angela-trade-fund-v2 angela-ui-v2
sudo rm /etc/systemd/system/angela-trade-fund-v2.service
sudo rm /etc/systemd/system/angela-ui-v2.service
sudo systemctl daemon-reload
```

V1's service is never modified by the V2 install or rollback.

## First-day checklist

- [ ] `v2_ledger.json` shows `settled_cash: 2000.0`.
- [ ] `sudo journalctl -u angela-trade-fund-v2 -n 50` shows the night-guard
      message ("V2: sleeping until 09:20 ET").
- [ ] At 9:55 ET tomorrow, the log shows "morning_deploy" and ends with
      "wrote event" + a row appears in `comparison_ledger.jsonl`.
- [ ] Open the V2 dashboard at :5001 — see V2's pod populate.
- [ ] At 15:50 ET the harvest runs; positions cleared; unsettled grows.
- [ ] V1's metrics (port 5000) are unaffected.
