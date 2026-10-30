# Creates (or replaces) the Windows scheduled task that runs the SMC
# Sweep-Break scan 5 minutes after every 4h candle close and logs each call
# and exit to journal/smc_paper.csv and journal/SMC_PAPER.md.
#
#   .\schedule-smc-scan.ps1           # create or update the task
#   .\schedule-smc-scan.ps1 -Remove   # delete it
#
# 4h candles close at 00/04/08/12/16/20 UTC = 05:30/09:30/13:30/17:30/21:30/
# 01:30 IST; the task runs at :35. It runs only while you are logged in. If
# the PC was asleep, it runs once when it wakes, and the journal still records
# exits it missed (only entries found late are flagged "late").
param([switch]$Remove)

$name = 'SMC Sweep-Break scan'
if ($Remove) {
    Unregister-ScheduledTask -TaskName $name -Confirm:$false
    return
}

$lab = $PSScriptRoot
$action = New-ScheduledTaskAction -Execute "$lab\.venv\Scripts\pythonw.exe" `
    -Argument 'research\scan_smc.py --log' -WorkingDirectory $lab
$firstUtc = [DateTime]::SpecifyKind([DateTime]::UtcNow.Date.AddMinutes(5), 'Utc')
$trigger = New-ScheduledTaskTrigger -Once -At $firstUtc.ToLocalTime() `
    -RepetitionInterval (New-TimeSpan -Hours 4)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $name -Action $action -Trigger $trigger `
    -Settings $settings -Force `
    -Description 'SMC Sweep-Break live scan + paper journal (freqtrade-lab/research/scan_smc.py --log). Read-only: places no orders.' |
    Out-Null
Get-ScheduledTask -TaskName $name | Get-ScheduledTaskInfo |
    Select-Object TaskName, NextRunTime, LastRunTime, LastTaskResult
