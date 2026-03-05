$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "scripts/oml/cli.ps1"
& $scriptPath @args
exit $LASTEXITCODE
