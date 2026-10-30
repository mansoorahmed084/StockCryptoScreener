# Creates (or replaces) the Windows task that starts the all-accounts trade
# bot in the background when you log in (deploy\trade_bot_bg.py, no window).
#
#   .\deploy\schedule-trade-bot.ps1           # create or update, and start it now
#   .\deploy\schedule-trade-bot.ps1 -Remove   # stop it and delete the task
#
# Log: data_cache\trade_bot.log. Only one copy can run (a local port lock),
# so a manual trade_bot_all.bat exits if this one is on. If the bot process
# dies, Windows starts it again (up to 999 times, 1 minute apart). It places
# a trade only after you tap Place and then Confirm in Telegram.
param([switch]$Remove)

$name = 'Trade bot (all accounts)'
if ($Remove) {
    Stop-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    return
}

$repo = Split-Path $PSScriptRoot -Parent
$action = New-ScheduledTaskAction -Execute "$repo\.venv\Scripts\pythonw.exe" `
    -Argument 'deploy\trade_bot_bg.py' -WorkingDirectory $repo
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1)
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger -Settings $settings `
    -Force -Description 'All-accounts CoinDCX trade bot (backend.cli trade bot) for Telegram Place/Confirm taps. Places nothing without two taps.' |
    Out-Null
Start-ScheduledTask -TaskName $name
Start-Sleep -Seconds 8
Get-ScheduledTask -TaskName $name | Get-ScheduledTaskInfo |
    Select-Object TaskName, LastRunTime, LastTaskResult
