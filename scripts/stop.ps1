$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskInfo = (& (Join-Path $taskRoot '.venv\Scripts\python.exe') (Join-Path $PSScriptRoot 'connection_info.py')) | ConvertFrom-Json
$taskData = $taskInfo.data
if (-not (Test-Path -LiteralPath $taskData)) { Write-Output 'Server is not running.'; exit 0 }
[IO.File]::WriteAllText((Join-Path $taskData 'stop.request'), 'stop')
Write-Output 'Stop requested. In-flight audio remains in the queue.'
