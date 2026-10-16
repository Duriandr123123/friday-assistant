$ErrorActionPreference = 'Stop'
$fridayRoot = Split-Path -Parent $PSScriptRoot
$fridayBootstrap = Join-Path $fridayRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $fridayBootstrap)) { throw 'Run setup.bat first.' }
$fridayAgentEnv = Join-Path $fridayRoot '.tools\assistant-agents'
$fridayGoogleEnv = Join-Path $fridayRoot '.tools\google-workspace-mcp'
& $fridayBootstrap -m venv $fridayAgentEnv
if ($LASTEXITCODE -ne 0) { throw 'Could not create agent environment' }
$fridayAgentPython = Join-Path $fridayAgentEnv 'Scripts\python.exe'
& $fridayAgentPython -m pip install -r (Join-Path $fridayRoot 'requirements-agents.lock.txt')
if ($LASTEXITCODE -ne 0) { throw 'Agent installation failed' }
& $fridayAgentPython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Agent dependency check failed' }
& $fridayBootstrap -m venv $fridayGoogleEnv
if ($LASTEXITCODE -ne 0) { throw 'Could not create Google environment' }
$fridayGooglePython = Join-Path $fridayGoogleEnv 'Scripts\python.exe'
& $fridayGooglePython -m pip install 'workspace-mcp==2.1.0'
if ($LASTEXITCODE -ne 0) { throw 'Google tools installation failed' }
& $fridayGooglePython -m pip check
if ($LASTEXITCODE -ne 0) { throw 'Google dependency check failed' }
$fridayManifestCode = 'import importlib.metadata as m,json,pathlib,sys; names=sys.argv[2:]; pathlib.Path(sys.argv[1]).write_text(json.dumps({n:m.version(n) for n in names}),encoding="utf-8")'
& $fridayAgentPython -c $fridayManifestCode (Join-Path $fridayAgentEnv 'friday-components.json') browser-use gpt-researcher mem0ai markitdown
if ($LASTEXITCODE -ne 0) { throw 'Agent manifest failed' }
& $fridayGooglePython -c $fridayManifestCode (Join-Path $fridayGoogleEnv 'friday-components.json') workspace-mcp
if ($LASTEXITCODE -ne 0) { throw 'Google manifest failed' }
Write-Output 'Components installed. Restart Jarvis manually. Additional Google tools require separate authorization.'
