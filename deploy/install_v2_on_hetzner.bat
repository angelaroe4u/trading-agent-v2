@echo off
REM install_v2_on_hetzner.bat — push V2 to Hetzner and install the systemd unit.
REM Run from C:\Projects\tradingap\Trading Agent 2.0

setlocal
set KEY=%USERPROFILE%\.ssh\id_ed25519_hetzner
set HOST=angela@5.161.197.162
set REMOTE_DIR=/opt/tradingap/Trading Agent 2.0

echo === Syncing V2 code to Hetzner ===
ssh -i "%KEY%" %HOST% "sudo mkdir -p \"%REMOTE_DIR%\" && sudo chown -R angela:angela \"%REMOTE_DIR%\""
scp -i "%KEY%" -r ^
  ".\v2_engine" ".\shared" ".\paper_trade" ".\memory_v2" ".\deploy" ".\tests" ^
  ".\pyproject.toml" ".\MEMORY.md" ".\README.md" ".\ARCHITECTURE_V2.md" ^
  ".\FITNESS_FUNCTION.md" ".\COMPARISON_PROTOCOL.md" ".\progress_tracker.json" ^
  %HOST%:"%REMOTE_DIR%/"

echo === Running install script on Hetzner ===
ssh -i "%KEY%" %HOST% "bash \"%REMOTE_DIR%/deploy/install_v2_on_hetzner.sh\""

echo.
echo === Tail V2 logs (Ctrl+C to exit) ===
ssh -i "%KEY%" %HOST% "sudo journalctl -u angela-trade-fund-v2 -f"
