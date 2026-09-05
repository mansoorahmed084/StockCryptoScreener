# Starts the Freqtrade paper-trading bot with the web UI.
Set-Location $PSScriptRoot
.\.venv\Scripts\freqtrade.exe trade --config config.json --strategy SampleStrategy
