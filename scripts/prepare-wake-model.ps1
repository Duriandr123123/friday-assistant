$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
$taskAssetFolder = Join-Path $taskRoot 'android\app\src\main\assets'
$taskAsset = Join-Path $taskAssetFolder 'wake-model.zip'
$taskExpected = '961d5ff98a17f4aa6de69864d0aa71fa5bac682301d2b5d17a3f24c5c99a46d4'
New-Item -ItemType Directory -Force -Path $taskAssetFolder | Out-Null
if (-not (Test-Path -LiteralPath $taskAsset)) {
    Invoke-WebRequest -UseBasicParsing -Uri 'https://alphacephei.com/vosk/models/vosk-model-small-ru-0.22.zip' -OutFile $taskAsset
}
if ((Get-FileHash -LiteralPath $taskAsset -Algorithm SHA256).Hash.ToLowerInvariant() -ne $taskExpected) {
    throw 'Wake model checksum mismatch. Replace android/app/src/main/assets/wake-model.zip with the official model.'
}
Write-Output 'Offline wake model verified.'
