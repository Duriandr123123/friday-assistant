$ErrorActionPreference = 'Stop'
$taskRoot = Split-Path -Parent $PSScriptRoot
& (Join-Path $PSScriptRoot 'prepare-wake-model.ps1')
# Some Android/JVM tools on Windows misread Cyrillic paths. Use an isolated ASCII build copy.
$taskBuildRoot = Join-Path $env:LOCALAPPDATA 'JarvisThoughtsBuild'
$taskStage = Join-Path $taskBuildRoot 'android'
New-Item -ItemType Directory -Force -Path $taskStage | Out-Null
$taskSource = Join-Path $taskRoot 'android'
Get-ChildItem -LiteralPath $taskSource -Force | Where-Object { $_.Name -notin @('.gradle','build','local.properties','app') } | ForEach-Object {
    Copy-Item -LiteralPath $_.FullName -Destination $taskStage -Recurse -Force
}
New-Item -ItemType Directory -Force -Path (Join-Path $taskStage 'app') | Out-Null
Copy-Item -LiteralPath (Join-Path $taskSource 'app\build.gradle.kts') -Destination (Join-Path $taskStage 'app\build.gradle.kts') -Force
$taskStagedSource = [IO.Path]::GetFullPath((Join-Path $taskStage 'app\src'))
if (-not $taskStagedSource.StartsWith([IO.Path]::GetFullPath($taskBuildRoot) + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid build directory.' }
if (Test-Path -LiteralPath $taskStagedSource) { Remove-Item -LiteralPath $taskStagedSource -Recurse -Force }
Copy-Item -LiteralPath (Join-Path $taskSource 'app\src') -Destination $taskStagedSource -Recurse
$taskSdk = Join-Path $taskRoot '.tools\android-sdk'
if (-not (Test-Path -LiteralPath $taskSdk)) { $taskSdk = $env:ANDROID_HOME }
if (-not $taskSdk -or -not (Test-Path -LiteralPath $taskSdk)) { throw 'Install Android SDK and set ANDROID_HOME.' }
$taskSdkLink = Join-Path $taskBuildRoot 'sdk'
if (-not (Test-Path -LiteralPath $taskSdkLink)) { New-Item -ItemType Junction -Path $taskSdkLink -Target $taskSdk | Out-Null }
[IO.File]::WriteAllText((Join-Path $taskStage 'local.properties'), ('sdk.dir=' + $taskSdkLink.Replace('\','/')))
if (-not $env:JAVA_HOME) {
    $taskJava = (Get-Command java.exe).Source
    $ErrorActionPreference = 'Continue'
    $taskJavaInfo = & $taskJava -XshowSettings:properties -version 2>&1 | Out-String
    $ErrorActionPreference = 'Stop'
    $taskMatch = [regex]::Match($taskJavaInfo, 'java.home\s*=\s*(.+)')
    if ($taskMatch.Success) { $env:JAVA_HOME = $taskMatch.Groups[1].Value.Trim() }
}
$taskGradle = Join-Path $taskRoot '.tools\gradle-8.11.1\bin\gradle.bat'
if (-not (Test-Path -LiteralPath $taskGradle)) { $taskGradle = Join-Path $taskStage 'gradlew.bat' }
& $taskGradle -p $taskStage assembleDebug testDebugUnitTest lintDebug --console=plain
if ($LASTEXITCODE -ne 0) { throw 'Android checks failed.' }
$taskDist = Join-Path $taskRoot 'dist'
New-Item -ItemType Directory -Force -Path $taskDist | Out-Null
Copy-Item -LiteralPath (Join-Path $taskStage 'app\build\outputs\apk\debug\app-debug.apk') -Destination (Join-Path $taskDist 'jarvis-debug.apk') -Force
Write-Output 'APK ready: dist/jarvis-debug.apk'
