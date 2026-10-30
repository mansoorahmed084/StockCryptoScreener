@echo off
rem Trade bot for EVERY account (main and sehe): handles the Telegram Place and
rem Confirm taps on SMC calls and Sehe setups, watches trades, trails stops
rem that asked for a trail, and scans the Sehe recovery-ledger coins.
rem It places a trade only after you tap Place and then Confirm in Telegram.
rem Run this INSTEAD of trade_bot_sehe.bat, never both: two bots on one
rem Telegram bot fight over the taps.
title Trade bot (all accounts) - close this window to stop it
cd /d "%~dp0.."
:run
.venv\Scripts\python.exe -m backend.cli trade bot
echo The bot stopped. Restarting in 30 seconds (close this window to stop)...
timeout /t 30 /nobreak >nul
goto run
