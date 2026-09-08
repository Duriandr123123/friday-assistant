$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $taskRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { throw 'Run setup.bat first.' }
& $taskPython (Join-Path $PSScriptRoot 'setup.py')
if ($LASTEXITCODE -ne 0) { throw 'Configuration failed.' }
$taskInfo = (& $taskPython (Join-Path $PSScriptRoot 'connection_info.py')) | ConvertFrom-Json
$taskPidFile = Join-Path $taskInfo.data 'server.pid'
if (Test-Path -LiteralPath $taskPidFile) {
    $taskExistingId = [int](Get-Content -LiteralPath $taskPidFile)
    $taskExisting = Get-CimInstance Win32_Process -Filter "ProcessId=$taskExistingId"
    if ($taskExisting -and $taskExisting.CommandLine -like '*scripts*server.py*') {
        Write-Output "Jarvis is already running. Open http://127.0.0.1:$($taskInfo.port)"
        exit 0
    }
}
$taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('scripts/server.py') -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskInfo.data 'startup.out.log') -RedirectStandardError (Join-Path $taskInfo.data 'startup.err.log')
Start-Sleep -Seconds 2
if ($taskProcess.HasExited) { throw 'Server failed. See data/startup.err.log' }
Write-Output "Jarvis started. Open http://127.0.0.1:$($taskInfo.port)"
