$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "cli/oml/cli.ps1"
& $scriptPath @args
exit $LASTEXITCODE
