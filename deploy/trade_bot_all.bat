@echo off
rem Trade bot for EVERY account (main and sehe), in this window: handles the
rem Telegram Place and Confirm taps on SMC calls and Sehe setups, watches
rem trades, trails stops that asked for a trail, and scans the Sehe ledger.
rem It places a trade only after you tap Place and then Confirm in Telegram.
rem
rem The log-in task (deploy\schedule-trade-bot.ps1) already runs this bot in
rem the background. Both go through deploy\trade_bot_bg.py, which lets only
rem one copy run, so this window just exits if the background one is on.
rem Do not also run trade_bot_sehe.bat: it does not share that lock.
title Trade bot (all accounts) - close this window to stop it
cd /d "%~dp0.."
.venv\Scripts\python.exe deploy\trade_bot_bg.py
echo.
echo Stopped. The log is data_cache\trade_bot.log
pause
