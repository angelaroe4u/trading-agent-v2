@echo off
REM install_v2_on_hetzner.bat — push V2 to Hetzner, restart services.
setlocal
set KEY=%USERPROFILE%\.ssh\id_ed25519_hetzner
set HOST=angela@5.161.197.162
set REMOTE=/opt/tradingap/Trading Agent 2.0

echo === Syncing V2 source tree to Hetzner ===
ssh -i "%KEY%" %HOST% "sudo mkdir -p \"%REMOTE%\" && sudo chown -R angela:angela \"%REMOTE%\""

REM scp each top-level dir/file SEPARATELY so cmd's continuation handling can't drop any.
for %%D in (v2_engine shared paper_trade memory_v2 deploy tests background_pictures) do (
  if exist "%%D" (
    echo   ---^> %%D\
    scp -i "%KEY%" -r "%%D" %HOST%:"%REMOTE%/"
  ) else (
    echo   skip %%D ^(not present locally^)
  )
)
for %%F in (pyproject.toml MEMORY.md README.md ARCHITECTURE_V2.md FITNESS_FUNCTION.md COMPARISON_PROTOCOL.md DEPLOY.md GITHUB.md progress_tracker.json .env.example Procurement_Report.md) do (
  if exist "%%F" (
    echo   ---^> %%F
    scp -i "%KEY%" "%%F" %HOST%:"%REMOTE%/"
  )
)

echo === Running install script on Hetzner ===
ssh -i "%KEY%" %HOST% "bash \"%REMOTE%/deploy/install_v2_on_hetzner.sh\""

echo.
echo === Verifying V2 dashboard service ===
ssh -i "%KEY%" %HOST% "sudo systemctl status angela-ui-v2 --no-pager -n 15"

echo.
echo Open http://5.161.197.162:5001 and HARD REFRESH (Ctrl+F5).
echo If still wrong: ssh -i %%USERPROFILE%%\.ssh\id_ed25519_hetzner %HOST% "sudo journalctl -u angela-ui-v2 -n 60 --no-pager"
