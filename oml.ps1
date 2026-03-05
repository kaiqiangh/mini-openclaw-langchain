param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $PSScriptRoot "cli/oml/cli.ps1"
& $scriptPath @RemainingArgs
exit $LASTEXITCODE
