@echo off
rem Sehe trade bot: watches trades, trails stops, scans the recovery-ledger coins
rem every 15 minutes and sends ready setups to Telegram with a Place button.
rem It places a trade only after you tap Place and then Confirm in Telegram.
title Sehe trade bot - close this window to stop it
cd /d "%~dp0.."
:run
.venv\Scripts\python.exe -m backend.cli trade bot --account sehe
echo The bot stopped. Restarting in 30 seconds (close this window to stop)...
timeout /t 30 /nobreak >nul
goto run
