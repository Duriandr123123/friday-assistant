$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskData = Join-Path $taskRoot 'data'
if (-not (Test-Path -LiteralPath $taskData)) { Write-Output 'Server is not running.'; exit 0 }
[IO.File]::WriteAllText((Join-Path $taskData 'stop.request'), 'stop')
Write-Output 'Stop requested. In-flight audio remains in the queue.'
