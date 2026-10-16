param([string]$GoogleDesktopClient = '')
$ErrorActionPreference = 'Stop'
$fridayRoot = Split-Path -Parent $PSScriptRoot
Push-Location $fridayRoot
try {
    $fridayPython = Join-Path $fridayRoot '.venv\Scripts\python.exe'
    $fridayWeb = Join-Path $fridayRoot 'backend\app\web'
    $fridayMigrations = Join-Path $fridayRoot 'backend\migrations'
    $fridayRunner = Join-Path $fridayRoot 'backend\app\agent_runner.py'
    $fridayGoogleArgs = @()
    if ($GoogleDesktopClient) {
        $fridayGoogleConfig = Get-Content -LiteralPath $GoogleDesktopClient -Raw | ConvertFrom-Json
        if (-not $fridayGoogleConfig.installed.client_id -or -not $fridayGoogleConfig.installed.client_secret) { throw 'Google credentials must be a Desktop OAuth client' }
        $fridayGoogleStaging = Join-Path $fridayRoot '.tools\google-desktop-client.json'
        New-Item -ItemType Directory -Force -Path (Split-Path $fridayGoogleStaging) | Out-Null
        Copy-Item -LiteralPath $GoogleDesktopClient -Destination $fridayGoogleStaging
        $fridayGoogleArgs = @('--add-data', "${fridayGoogleStaging};backend\app")
    }
    & $fridayPython -m PyInstaller --noconfirm --onedir --windowed --name Friday --distpath dist --workpath .tools\desktop-build --specpath .tools --paths $fridayRoot --add-data "${fridayWeb};backend\app\web" --add-data "${fridayMigrations};backend\migrations" --add-data "${fridayRunner};backend\app" @fridayGoogleArgs --collect-data tzdata --collect-submodules uvicorn --collect-submodules qrcode --exclude-module faster_whisper --exclude-module torch scripts\desktop.py
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
    $fridayPayload = Join-Path $fridayRoot 'dist\Friday'
    $fridayLines = @()
    Get-ChildItem -LiteralPath $fridayPayload -Recurse -File | ForEach-Object {
        $fridayRelative = $_.FullName.Substring($fridayPayload.Length + 1)
        $fridayLines += 'Delete "$INSTDIR\' + $fridayRelative + '"'
    }
    Get-ChildItem -LiteralPath $fridayPayload -Recurse -Directory | Sort-Object { $_.FullName.Length } -Descending | ForEach-Object {
        $fridayRelative = $_.FullName.Substring($fridayPayload.Length + 1)
        $fridayLines += 'RMDir "$INSTDIR\' + $fridayRelative + '"'
    }
    $fridayLines | Set-Content -LiteralPath '.tools\friday-uninstall.nsh' -Encoding UTF8
    $fridayCompiler = Join-Path ${env:ProgramFiles(x86)} 'NSIS\makensis.exe'
    & $fridayCompiler scripts\friday.nsi
    if ($LASTEXITCODE -ne 0) { throw 'Installer build failed' }
} finally { Pop-Location }
