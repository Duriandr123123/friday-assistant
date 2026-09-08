$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskAction = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument ('-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "' + (Join-Path $taskRoot 'scripts\start.ps1') + '"') -WorkingDirectory $taskRoot
$taskTrigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
Register-ScheduledTask -TaskName 'JarvisThoughts' -Action $taskAction -Trigger $taskTrigger -Description 'Personal voice notes backend' -Force | Out-Null
Write-Output 'Autostart enabled for this user.'
