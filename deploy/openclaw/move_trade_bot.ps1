<#
Move the CoinDCX trade bot (every account) from this laptop to OpenClaw on
EC2, or back. Run from the repo root in PowerShell:

    deploy\openclaw\move_trade_bot.ps1 -Check   # only test the server keys
    deploy\openclaw\move_trade_bot.ps1          # laptop -> EC2
    deploy\openclaw\move_trade_bot.ps1 -Back    # EC2 -> laptop

Before the first move, the server needs smc/.env with the Telegram lines and
CoinDCX keys bound to the server's IP (deploy/openclaw/README.md).

Laptop -> EC2:
  1. copy the code (git HEAD) to the server
  2. test the keys on the server; stop here if they fail
  3. stop the laptop bot and turn off its log-in task
  4. copy trading.db, trading_sehe.db and recovery_sehe.csv to the server
  5. switch the server bot on (and the scan's Place offers)
EC2 -> laptop: switch the server bot off, copy the three files back, and
start the laptop bot again. Old copies are kept as *.bak.
#>
param(
    [switch]$Back,
    [switch]$Check,
    [string]$Server = 'ubuntu@13.207.59.231',
    [string]$Key = "$HOME\Downloads\myClawNew.pem"
)
$ErrorActionPreference = 'Stop'
Set-Location (git rev-parse --show-toplevel)
$Task = 'Trade bot (all accounts)'
$HostDir = 'openclaw/workspace/smc'                  # the folder, as the host sees it
$BoxDir = '/home/node/.openclaw/workspace/smc'       # the same folder in the container
$State = 'trading.db', 'trading_sehe.db', 'recovery_sehe.csv'
$Ssh = @('-i', $Key, '-o', 'BatchMode=yes')

function OnServer([string]$cmd) {
    ssh @Ssh $Server $cmd
    if ($LASTEXITCODE -ne 0) { throw "server step failed: $cmd" }
}
function Box([string]$what) {
    OnServer "sudo docker exec `$(sudo docker ps -qf name=openclaw-gateway) sh $BoxDir/trade_bot_switch.sh $what"
}
function StopLaptopBot {
    Disable-ScheduledTask -TaskName $Task | Out-Null
    Get-CimInstance Win32_Process -Filter "Name like 'python%'" |
        Where-Object { $_.CommandLine -like '*trade_bot_bg.py*' } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force; "stopped laptop bot (pid $($_.ProcessId))" }
    Start-Sleep -Seconds 2
}

if ($Check) { Box 'check'; exit 0 }

if ($Back) {
    Box 'off'
    foreach ($f in $State) {
        if (Test-Path "data_cache\$f") { Copy-Item "data_cache\$f" "data_cache\$f.bak" -Force }
        scp @Ssh "${Server}:$HostDir/data_cache/$f" "data_cache\$f"
        if ($LASTEXITCODE -ne 0) { throw "copy back failed: $f" }
    }
    Enable-ScheduledTask -TaskName $Task | Out-Null
    Start-ScheduledTask -TaskName $Task
    "Trade bot is back on the laptop. The server scan no longer offers Place buttons."
    exit 0
}

# 1. code: git HEAD of what the bot and the scan use
$tar = Join-Path $env:TEMP 'smc_code.tar'
git archive --format=tar -o $tar HEAD backend deploy/trade_bot_bg.py `
    deploy/openclaw/start_trade_bot.sh deploy/openclaw/trade_bot_switch.sh deploy/openclaw/create_jobs.sh `
    freqtrade-lab/research/harness.py freqtrade-lab/research/smc.py freqtrade-lab/research/smc_loop.py `
    freqtrade-lab/research/smc_account.py freqtrade-lab/research/smc_oos.py freqtrade-lab/research/smc_paper.py `
    freqtrade-lab/research/scan_smc.py freqtrade-lab/research/smc_trade.py
scp @Ssh -q $tar "${Server}:/tmp/smc_code.tar"
scp @Ssh -q config.yaml "${Server}:$HostDir/config.yaml"
OnServer ("tar -x -C $HostDir -f /tmp/smc_code.tar && rm /tmp/smc_code.tar && " +
          "cp $HostDir/deploy/openclaw/start_trade_bot.sh $HostDir/deploy/openclaw/trade_bot_switch.sh " +
          "$HostDir/deploy/openclaw/create_jobs.sh $HostDir/")
Remove-Item $tar

# 2. keys work from the server?
Box 'check'

# 3-4. stop the laptop bot, then copy its state (nothing writes it now)
StopLaptopBot
OnServer "mkdir -p $HostDir/data_cache && cd $HostDir/data_cache && for f in $($State -join ' '); do [ -f `$f ] && cp `$f `$f.bak; done; true"
foreach ($f in $State) {
    if (Test-Path "data_cache\$f") {
        scp @Ssh -q "data_cache\$f" "${Server}:$HostDir/data_cache/$f"
        if ($LASTEXITCODE -ne 0) { throw "copy failed: $f" }
    }
}

# 5. on
Box 'on'
Start-Sleep -Seconds 20
Box 'status'
"Trade bot now runs on the server. The laptop task '$Task' is disabled."
"Use Telegram for Place / Confirm. The laptop Trade page shows old data now."
