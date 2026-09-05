# Starts only the web UI, for backtesting from the browser. No bot running.
Set-Location $PSScriptRoot
.\.venv\Scripts\freqtrade.exe webserver --config config.json
