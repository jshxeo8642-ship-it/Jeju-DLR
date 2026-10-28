param([int]$Port = 8765)
$ErrorActionPreference = 'Stop'
$localPython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
$bundledPython = Join-Path $env:USERPROFILE '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
if (Test-Path -LiteralPath $localPython) { $dlrPython = $localPython }
elseif (Test-Path -LiteralPath $bundledPython) { $dlrPython = $bundledPython }
else { $dlrPython = 'python' }
& $dlrPython -X utf8 (Join-Path $PSScriptRoot 'run.py') ui --port $Port
