[CmdletBinding()]
param(
  [Parameter(Position = 0)]
  [string]$Command = "help",

  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$RemainingArgs
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:OML_CLI_VERSION = "0.1.0"
$script:ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$script:RepoRoot = (Resolve-Path (Join-Path $script:ScriptDir "../..")).Path
$script:StateDir = if ($env:OML_STATE_DIR) { $env:OML_STATE_DIR } else { Join-Path $script:RepoRoot ".oml" }
$script:RunDir = Join-Path $script:StateDir "run"
$script:LogDir = Join-Path $script:StateDir "log"
$script:ConfigEnv = Join-Path $script:StateDir "config.env"

function Write-Info([string]$Message) {
  Write-Output "[oml] $Message"
}

function Write-WarnCli([string]$Message) {
  Write-Warning "[oml] $Message"
}

function Write-ErrorCli([string]$Message) {
  Write-Error "[oml] $Message"
}

function Ensure-RuntimeDirs {
  New-Item -ItemType Directory -Path $script:RunDir -Force | Out-Null
  New-Item -ItemType Directory -Path $script:LogDir -Force | Out-Null
}

function Test-Integer([string]$Value) {
  return $Value -match '^[0-9]+$'
}

function Normalize-ProxyMode([string]$Value) {
  $raw = ""
  if ($null -ne $Value) {
    $raw = $Value.Trim().ToLowerInvariant()
  }

  switch ($raw) {
    "1" { return "true" }
    "true" { return "true" }
    "yes" { return "true" }
    "on" { return "true" }
    "0" { return "false" }
    "false" { return "false" }
    "no" { return "false" }
    "off" { return "false" }
    "inherit" { return "inherit" }
    default { throw "OML_ENABLE_FRONTEND_PROXY must be true, false, or inherit" }
  }
}

function Get-ConfigFileValues {
  $values = @{}
  if (-not (Test-Path $script:ConfigEnv)) {
    return $values
  }

  foreach ($line in Get-Content -Path $script:ConfigEnv) {
    $trimmed = $line.Trim()
    if ([string]::IsNullOrWhiteSpace($trimmed) -or $trimmed.StartsWith("#")) {
      continue
    }
    $separator = $trimmed.IndexOf("=")
    if ($separator -lt 1) {
      continue
    }

    $key = $trimmed.Substring(0, $separator).Trim()
    $value = $trimmed.Substring($separator + 1).Trim()
    if (
      (($value.StartsWith('"')) -and ($value.EndsWith('"'))) -or
      (($value.StartsWith("'")) -and ($value.EndsWith("'")))
    ) {
      $value = $value.Substring(1, $value.Length - 2)
    }
    $values[$key] = $value
  }

  return $values
}

function Resolve-ConfigValue([hashtable]$ConfigValues, [string]$Name, [string]$DefaultValue) {
  $envValue = [Environment]::GetEnvironmentVariable($Name)
  if (-not [string]::IsNullOrWhiteSpace($envValue)) {
    return $envValue
  }
  if ($ConfigValues.ContainsKey($Name) -and -not [string]::IsNullOrWhiteSpace([string]$ConfigValues[$Name])) {
    return [string]$ConfigValues[$Name]
  }
  return $DefaultValue
}

function Load-ConfigEnv {
  $configValues = Get-ConfigFileValues

  $script:OML_BACKEND_HOST = Resolve-ConfigValue $configValues "OML_BACKEND_HOST" "127.0.0.1"
  $script:OML_BACKEND_PORT = Resolve-ConfigValue $configValues "OML_BACKEND_PORT" "8000"
  $script:OML_FRONTEND_HOST = Resolve-ConfigValue $configValues "OML_FRONTEND_HOST" "127.0.0.1"
  $script:OML_FRONTEND_PORT = Resolve-ConfigValue $configValues "OML_FRONTEND_PORT" "3000"
  $script:OML_HEALTH_TIMEOUT_SECONDS = Resolve-ConfigValue $configValues "OML_HEALTH_TIMEOUT_SECONDS" "30"
  $script:OML_ENABLE_FRONTEND_PROXY = Normalize-ProxyMode (Resolve-ConfigValue $configValues "OML_ENABLE_FRONTEND_PROXY" "true")
  $script:OML_FRONTEND_PROXY_URL = Resolve-ConfigValue $configValues "OML_FRONTEND_PROXY_URL" ""
  $script:OML_BACKEND_CMD = Resolve-ConfigValue $configValues "OML_BACKEND_CMD" ""
  $script:OML_FRONTEND_CMD = Resolve-ConfigValue $configValues "OML_FRONTEND_CMD" ""

  if (-not (Test-Integer $script:OML_BACKEND_PORT)) {
    throw "OML_BACKEND_PORT must be an integer"
  }
  if (-not (Test-Integer $script:OML_FRONTEND_PORT)) {
    throw "OML_FRONTEND_PORT must be an integer"
  }
  if (-not (Test-Integer $script:OML_HEALTH_TIMEOUT_SECONDS)) {
    throw "OML_HEALTH_TIMEOUT_SECONDS must be an integer"
  }

  if ([string]::IsNullOrWhiteSpace($script:OML_FRONTEND_PROXY_URL)) {
    $script:OML_FRONTEND_PROXY_URL = "http://$($script:OML_FRONTEND_HOST):$($script:OML_FRONTEND_PORT)"
  }
}

function Get-PidFile([string]$Service) {
  return Join-Path $script:RunDir "$Service.pid"
}

function Get-LogFile([string]$Service) {
  return Join-Path $script:LogDir "$Service.log"
}

function Get-ServicePort([string]$Service) {
  if ($Service -eq "backend") {
    return $script:OML_BACKEND_PORT
  }
  return $script:OML_FRONTEND_PORT
}

function Get-ServiceHost([string]$Service) {
  if ($Service -eq "backend") {
    return $script:OML_BACKEND_HOST
  }
  return $script:OML_FRONTEND_HOST
}

function Get-ServiceUrl([string]$Service) {
  $hostName = Get-ServiceHost $Service
  $port = Get-ServicePort $Service
  if ($Service -eq "backend") {
    return "http://$hostName`:$port/api/v1/health"
  }
  return "http://$hostName`:$port"
}

function Get-ServiceSignature([string]$Service) {
  if ($Service -eq "backend") {
    return "uvicorn app:app"
  }
  return "next dev"
}

function Read-Pid([string]$Service) {
  $pidFile = Get-PidFile $Service
  if (-not (Test-Path $pidFile)) {
    return $null
  }
  $value = (Get-Content -Path $pidFile -Raw).Trim()
  if (-not (Test-Integer $value)) {
    return $null
  }
  return [int]$value
}

function Test-PidRunning([int]$PidValue) {
  try {
    Get-Process -Id $PidValue -ErrorAction Stop | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Get-ProcessCommandLine([int]$PidValue) {
  try {
    $processInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $PidValue" -ErrorAction Stop
    if ($null -eq $processInfo) {
      return ""
    }
    if ($null -eq $processInfo.CommandLine) {
      return ""
    }
    return $processInfo.CommandLine.Trim()
  } catch {
    return ""
  }
}

function Test-PidMatchesService([int]$PidValue, [string]$Service) {
  $commandLine = Get-ProcessCommandLine $PidValue
  if ([string]::IsNullOrWhiteSpace($commandLine)) {
    return $false
  }
  $signature = Get-ServiceSignature $Service
  return $commandLine -like "*$signature*"
}

function Clear-Pid([string]$Service) {
  $pidFile = Get-PidFile $Service
  if (Test-Path $pidFile) {
    Remove-Item -Path $pidFile -Force
  }
}

function Test-ServiceRunning([string]$Service) {
  $pidValue = Read-Pid $Service
  if ($null -eq $pidValue) {
    return $false
  }
  if (-not (Test-PidRunning $pidValue)) {
    Clear-Pid $Service
    return $false
  }
  if (-not (Test-PidMatchesService $pidValue $Service)) {
    Write-WarnCli "Ignoring stale PID for $Service (pid=$pidValue did not match signature)."
    Clear-Pid $Service
    return $false
  }
  return $true
}

function Require-Command([string]$Name) {
  try {
    Get-Command $Name -ErrorAction Stop | Out-Null
  } catch {
    throw "Missing required binary: $Name"
  }
}

function Get-CmdExe {
  return (Get-Command "cmd.exe" -ErrorAction Stop).Source
}

function Get-PortOwnerPid([int]$Port) {
  if (Get-Command Get-NetTCPConnection -ErrorAction SilentlyContinue) {
    try {
      $connection = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop | Select-Object -First 1
      if ($null -ne $connection) {
        return [string]$connection.OwningProcess
      }
    } catch {
    }
  }

  foreach ($line in netstat -ano) {
    if ($line -match "[:\.]$Port\s+.*LISTENING\s+(\d+)$") {
      return $matches[1]
    }
  }

  return $null
}

function Test-PortInUse([int]$Port) {
  return $null -ne (Get-PortOwnerPid $Port)
}

function Assert-Target([string]$Target) {
  switch ($Target) {
    "all" { return }
    "backend" { return }
    "frontend" { return }
    default { throw "Invalid target: $Target (expected all|backend|frontend)" }
  }
}

function Quote-Cmd([string]$Value) {
  return '"' + ($Value -replace '"', '""') + '"'
}

function Get-BackendPythonPath {
  return Join-Path (Join-Path $script:RepoRoot "backend") ".venv\Scripts\python.exe"
}

function Build-BackendCommand {
  $workingDir = Join-Path $script:RepoRoot "backend"
  if (-not [string]::IsNullOrWhiteSpace($script:OML_BACKEND_CMD)) {
    return "cd /d $(Quote-Cmd $workingDir) && $($script:OML_BACKEND_CMD)"
  }

  $pythonPath = Get-BackendPythonPath
  $parts = @("cd /d $(Quote-Cmd $workingDir)")

  switch ($script:OML_ENABLE_FRONTEND_PROXY) {
    "true" {
      $parts += "set ""APP_ENABLE_FRONTEND_PROXY=true"""
      $parts += "set ""APP_FRONTEND_PROXY_URL=$($script:OML_FRONTEND_PROXY_URL)"""
    }
    "false" {
      $parts += "set ""APP_ENABLE_FRONTEND_PROXY=false"""
    }
    default {
    }
  }

  $parts += "$(Quote-Cmd $pythonPath) -m uvicorn app:app --host $($script:OML_BACKEND_HOST) --port $($script:OML_BACKEND_PORT)"
  return ($parts -join " && ")
}

function Build-FrontendCommand {
  $workingDir = Join-Path $script:RepoRoot "frontend"
  if (-not [string]::IsNullOrWhiteSpace($script:OML_FRONTEND_CMD)) {
    return "cd /d $(Quote-Cmd $workingDir) && $($script:OML_FRONTEND_CMD)"
  }

  $npmPath = (Get-Command npm -ErrorAction Stop).Source
  return "cd /d $(Quote-Cmd $workingDir) && $(Quote-Cmd $npmPath) exec -- next dev -p $($script:OML_FRONTEND_PORT) -H $($script:OML_FRONTEND_HOST)"
}

function Start-ServiceInternal([string]$Service) {
  Ensure-RuntimeDirs
  $pidFile = Get-PidFile $Service
  $logFile = Get-LogFile $Service

  if (Test-ServiceRunning $Service) {
    Write-Info "$Service is already running (pid $(Read-Pid $Service))."
    return
  }

  $commandText = if ($Service -eq "backend") { Build-BackendCommand } else { Build-FrontendCommand }
  $commandText = "$commandText >> $(Quote-Cmd $logFile) 2>&1"
  $process = Start-Process -FilePath (Get-CmdExe) -ArgumentList @("/d", "/c", $commandText) -WindowStyle Hidden -PassThru
  Set-Content -Path $pidFile -Value $process.Id -NoNewline
  Write-Info "Started $Service (pid=$($process.Id))."
}

function Check-ServiceHealth([string]$Service) {
  $url = Get-ServiceUrl $Service
  try {
    $response = Invoke-WebRequest -Uri $url -Method Get -TimeoutSec 2
    return $response.StatusCode -ge 200 -and $response.StatusCode -lt 400
  } catch {
    return $false
  }
}

function Wait-ForHealth([string]$Service) {
  if ($env:OML_SKIP_HEALTH -eq "1") {
    return $true
  }

  $timeout = [int]$script:OML_HEALTH_TIMEOUT_SECONDS
  for ($waited = 0; $waited -lt $timeout; $waited++) {
    if (-not (Test-ServiceRunning $Service)) {
      return $false
    }
    if (Check-ServiceHealth $Service) {
      return $true
    }
    Start-Sleep -Seconds 1
  }

  return $false
}

function Stop-ServiceInternal([string]$Service) {
  $pidValue = Read-Pid $Service
  if ($null -eq $pidValue) {
    Write-Info "$Service is not running."
    return
  }

  if (-not (Test-PidRunning $pidValue)) {
    Clear-Pid $Service
    Write-Info "$Service pid file was stale and has been cleaned."
    return
  }

  if (-not (Test-PidMatchesService $pidValue $Service)) {
    throw "Refusing to stop $Service: pid $pidValue does not match expected signature."
  }

  try {
    Stop-Process -Id $pidValue -ErrorAction SilentlyContinue
  } catch {
  }

  for ($waited = 0; $waited -lt 10; $waited++) {
    if (-not (Test-PidRunning $pidValue)) {
      break
    }
    Start-Sleep -Seconds 1
  }

  if (Test-PidRunning $pidValue) {
    & taskkill.exe /F /T /PID $pidValue | Out-Null
  }

  Clear-Pid $Service
  Write-Info "Stopped $Service."
}

function Show-LogsForService([string]$Service, [int]$Lines, [bool]$Follow) {
  $logFile = Get-LogFile $Service
  if (-not (Test-Path $logFile)) {
    Write-WarnCli "No log file for $Service yet: $logFile"
    return
  }

  if ($Follow) {
    Get-Content -Path $logFile -Tail $Lines -Wait
    return
  }

  Write-Output "== $Service ($logFile) =="
  Get-Content -Path $logFile -Tail $Lines
}

function Invoke-CmdHelp {
@"
Usage: .\oml.ps1 <command> [options]

Commands:
  help                           Show command help
  version                        Print CLI, backend, frontend, and git versions
  start [all|backend|frontend]   Start services in background (default: all)
  stop [all|backend|frontend]    Stop services (default: all)
  restart [all|backend|frontend] Restart services (default: all)
  status                         Show runtime status and health
  logs [all|backend|frontend] [--follow] [--lines N]
                                 Show logs (default target: all, default lines: 50)
  ports                          Show effective host/port URLs
  update                         Safe local dependency sync (no git history mutation)
  doctor                         Validate local prerequisites and runtime readiness

Runtime state:
  .oml\run\*.pid                Managed process IDs
  .oml\log\*.log                Service logs
  .oml\config.env               Optional overrides

Proxy defaults:
  OML_ENABLE_FRONTEND_PROXY=true
  OML_FRONTEND_PROXY_URL=http://127.0.0.1:3000
  OML_ENABLE_FRONTEND_PROXY=inherit lets backend/.env control APP_ENABLE_FRONTEND_PROXY

Examples:
  .\oml.ps1 start
  .\oml.ps1 restart backend
  .\oml.ps1 logs backend --follow
  .\oml.ps1 update
"@ | Write-Output
}

function Invoke-CmdVersion {
  $backendVersion = "unknown"
  $frontendVersion = "unknown"
  $gitSha = "unknown"

  $backendApp = Join-Path (Join-Path $script:RepoRoot "backend") "app.py"
  $backendMatch = Select-String -Path $backendApp -Pattern 'version="([^"]+)"' | Select-Object -First 1
  if ($backendMatch) {
    $backendVersion = $backendMatch.Matches[0].Groups[1].Value
  }

  $packagePath = Join-Path (Join-Path $script:RepoRoot "frontend") "package.json"
  if (Test-Path $packagePath) {
    $packageJson = Get-Content -Path $packagePath -Raw | ConvertFrom-Json
    if ($packageJson.version) {
      $frontendVersion = [string]$packageJson.version
    }
  }

  try {
    $gitSha = (& git -C $script:RepoRoot rev-parse --short HEAD).Trim()
  } catch {
  }

  Write-Output "oml: $($script:OML_CLI_VERSION)"
  Write-Output "backend_api: $backendVersion"
  Write-Output "frontend: $frontendVersion"
  Write-Output "git_sha: $gitSha"
}

function Invoke-CmdStart([string]$Target = "all") {
  Assert-Target $Target

  if ($Target -eq "all" -or $Target -eq "backend") {
    if ([string]::IsNullOrWhiteSpace($script:OML_BACKEND_CMD)) {
      $pythonPath = Get-BackendPythonPath
      if (-not (Test-Path $pythonPath)) {
        throw "Missing backend interpreter: $pythonPath"
      }
    }
  }
  if ($Target -eq "all" -or $Target -eq "frontend") {
    if ([string]::IsNullOrWhiteSpace($script:OML_FRONTEND_CMD)) {
      Require-Command "npm"
    }
  }

  $startedBackend = $false
  $startedFrontend = $false

  if ($Target -eq "all" -or $Target -eq "backend") {
    if (-not (Test-ServiceRunning "backend")) {
      Start-ServiceInternal "backend"
      $startedBackend = $true
    } else {
      Write-Info "backend already running."
    }
    if (-not (Wait-ForHealth "backend")) {
      Write-ErrorCli "backend failed to become healthy."
      if ($startedBackend) {
        Stop-ServiceInternal "backend"
      }
      exit 3
    }
  }

  if ($Target -eq "all" -or $Target -eq "frontend") {
    if (-not (Test-ServiceRunning "frontend")) {
      Start-ServiceInternal "frontend"
      $startedFrontend = $true
    } else {
      Write-Info "frontend already running."
    }
    if (-not (Wait-ForHealth "frontend")) {
      Write-ErrorCli "frontend failed to become healthy."
      if ($startedFrontend) {
        Stop-ServiceInternal "frontend"
      }
      if ($Target -eq "all" -and $startedBackend) {
        Stop-ServiceInternal "backend"
      }
      exit 3
    }
  }

  Write-Info "Start command completed."
}

function Invoke-CmdStop([string]$Target = "all") {
  Assert-Target $Target
  if ($Target -eq "all" -or $Target -eq "frontend") {
    Stop-ServiceInternal "frontend"
  }
  if ($Target -eq "all" -or $Target -eq "backend") {
    Stop-ServiceInternal "backend"
  }
}

function Invoke-CmdRestart([string]$Target = "all") {
  Invoke-CmdStop $Target
  Invoke-CmdStart $Target
}

function Write-ServiceStatus([string]$Service) {
  $url = Get-ServiceUrl $Service
  $port = Get-ServicePort $Service

  if (Test-ServiceRunning $Service) {
    $pidValue = Read-Pid $Service
    $health = if (Check-ServiceHealth $Service) { "ok" } else { "degraded" }
    Write-Output ("{0,-8} running  pid={1}  health={2}  url={3}" -f $Service, $pidValue, $health, $url)
    return
  }

  if (Test-PortInUse ([int]$port)) {
    Write-Output ("{0,-8} stopped  port={1} in use by another process" -f $Service, $port)
    return
  }

  Write-Output ("{0,-8} stopped  url={1}" -f $Service, $url)
}

function Invoke-CmdStatus {
  Write-ServiceStatus "backend"
  Write-ServiceStatus "frontend"
}

function Invoke-CmdLogs([string[]]$ArgsList) {
  $target = "all"
  $lines = 50
  $follow = $false
  $index = 0

  while ($index -lt $ArgsList.Count) {
    $arg = $ArgsList[$index]
    switch -Regex ($arg) {
      "^(all|backend|frontend)$" {
        $target = $arg
      }
      "^--follow$|^-f$" {
        $follow = $true
      }
      "^--lines=(\d+)$" {
        $lines = [int]$matches[1]
      }
      "^--lines$" {
        $index++
        if ($index -ge $ArgsList.Count) {
          throw "--lines requires a value"
        }
        if (-not (Test-Integer $ArgsList[$index])) {
          throw "--lines must be an integer"
        }
        $lines = [int]$ArgsList[$index]
      }
      default {
        throw "Unknown logs option: $arg"
      }
    }
    $index++
  }

  if ($target -eq "all") {
    if ($follow) {
      $backendLog = Get-LogFile "backend"
      $frontendLog = Get-LogFile "frontend"
      Ensure-RuntimeDirs
      if (-not (Test-Path $backendLog)) { New-Item -ItemType File -Path $backendLog -Force | Out-Null }
      if (-not (Test-Path $frontendLog)) { New-Item -ItemType File -Path $frontendLog -Force | Out-Null }
      Get-Content -Path @($backendLog, $frontendLog) -Tail $lines -Wait
      return
    }

    Show-LogsForService "backend" $lines $false
    Write-Output ""
    Show-LogsForService "frontend" $lines $false
    return
  }

  Show-LogsForService $target $lines $follow
}

function Invoke-CmdPorts {
  Write-Output "backend_health_url: http://$($script:OML_BACKEND_HOST):$($script:OML_BACKEND_PORT)/api/v1/health"
  Write-Output "frontend_dev_url: http://$($script:OML_FRONTEND_HOST):$($script:OML_FRONTEND_PORT)"
  Write-Output "manual_dev_api_proxy_url: $((Resolve-ConfigValue (Get-ConfigFileValues) "NEXT_DEV_API_PROXY_URL" "http://127.0.0.1:8000"))/api/v1"
  Write-Output "backend_frontend_proxy_mode: $($script:OML_ENABLE_FRONTEND_PROXY)"
  if ($script:OML_ENABLE_FRONTEND_PROXY -eq "inherit") {
    Write-Output "backend_frontend_proxy_url: inherited from backend env"
  } else {
    Write-Output "backend_frontend_proxy_url: $($script:OML_FRONTEND_PROXY_URL)"
  }
}

function Invoke-CmdUpdate {
  Require-Command "uv"
  Require-Command "npm"

  Write-Info "Syncing backend dependencies..."
  Push-Location (Join-Path $script:RepoRoot "backend")
  try {
    if (-not (Test-Path ".venv\Scripts\python.exe")) {
      & uv venv .venv
    }
    & uv pip install --python ".venv\Scripts\python.exe" -r requirements.txt
    if (Test-Path "requirements-dev.txt") {
      & uv pip install --python ".venv\Scripts\python.exe" -r requirements-dev.txt
    }
    if (Test-Path "requirements-pdf.txt") {
      & uv pip install --python ".venv\Scripts\python.exe" -r requirements-pdf.txt
    }
  } finally {
    Pop-Location
  }

  Write-Info "Syncing frontend dependencies..."
  Push-Location (Join-Path $script:RepoRoot "frontend")
  try {
    if (Test-Path "package-lock.json") {
      & npm ci
    } else {
      & npm install
    }
  } finally {
    Pop-Location
  }

  Write-Info "Dependency sync complete."
  Write-Info "No git pull/rebase/reset executed."
  try {
    & git -C $script:RepoRoot status --short
  } catch {
  }
}

function Invoke-CmdDoctor {
  $critical = $false
  Write-Output "Doctor checks:"

  foreach ($binary in @("node", "npm", "git")) {
    if (Get-Command $binary -ErrorAction SilentlyContinue) {
      Write-Output "  [ok]   binary $binary"
    } else {
      Write-Output "  [fail] binary $binary missing"
      $critical = $true
    }
  }

  if (Get-Command "uv" -ErrorAction SilentlyContinue) {
    Write-Output "  [ok]   binary uv"
  } else {
    Write-Output "  [warn] binary uv missing (required for update)"
  }

  $backendPython = Get-BackendPythonPath
  if (Test-Path $backendPython) {
    Write-Output "  [ok]   backend virtualenv interpreter present"
  } else {
    Write-Output "  [warn] backend virtualenv interpreter missing ($backendPython)"
  }

  if (Test-Path (Join-Path (Join-Path $script:RepoRoot "backend") ".env")) {
    Write-Output "  [ok]   backend/.env present"
  } else {
    Write-Output "  [fail] backend/.env missing"
    $critical = $true
  }

  if ($script:OML_ENABLE_FRONTEND_PROXY -eq "inherit") {
    Write-Output "  [ok]   frontend proxy mode inherited from backend env"
  } else {
    Write-Output "  [ok]   frontend proxy mode $($script:OML_ENABLE_FRONTEND_PROXY) ($($script:OML_FRONTEND_PROXY_URL))"
  }

  if (Test-ServiceRunning "backend") {
    $backendPid = Read-Pid "backend"
    if (Check-ServiceHealth "backend") {
      Write-Output "  [ok]   backend running (pid=$backendPid) and healthy"
    } else {
      Write-Output "  [warn] backend running (pid=$backendPid) but health check failed"
    }
  } else {
    $backendOwner = Get-PortOwnerPid ([int]$script:OML_BACKEND_PORT)
    if ($null -ne $backendOwner) {
      Write-Output "  [fail] backend port $($script:OML_BACKEND_PORT) in use by pid $backendOwner"
      $critical = $true
    } else {
      Write-Output "  [ok]   backend port $($script:OML_BACKEND_PORT) available"
    }
  }

  if (Test-ServiceRunning "frontend") {
    $frontendPid = Read-Pid "frontend"
    if (Check-ServiceHealth "frontend") {
      Write-Output "  [ok]   frontend running (pid=$frontendPid) and reachable"
    } else {
      Write-Output "  [warn] frontend running (pid=$frontendPid) but HTTP check failed"
    }
  } else {
    $frontendOwner = Get-PortOwnerPid ([int]$script:OML_FRONTEND_PORT)
    if ($null -ne $frontendOwner) {
      Write-Output "  [fail] frontend port $($script:OML_FRONTEND_PORT) in use by pid $frontendOwner"
      $critical = $true
    } else {
      Write-Output "  [ok]   frontend port $($script:OML_FRONTEND_PORT) available"
    }
  }

  if ($critical) {
    throw "Doctor found critical issues."
  }

  Write-Info "Doctor passed."
}

Load-ConfigEnv

try {
  switch ($Command) {
    { $_ -in @("help", "-h", "--help") } { Invoke-CmdHelp }
    "version" { Invoke-CmdVersion }
    "start" { Invoke-CmdStart ($(if ($RemainingArgs.Count -gt 0) { $RemainingArgs[0] } else { "all" })) }
    "stop" { Invoke-CmdStop ($(if ($RemainingArgs.Count -gt 0) { $RemainingArgs[0] } else { "all" })) }
    "restart" { Invoke-CmdRestart ($(if ($RemainingArgs.Count -gt 0) { $RemainingArgs[0] } else { "all" })) }
    "status" { Invoke-CmdStatus }
    "logs" { Invoke-CmdLogs $RemainingArgs }
    "ports" { Invoke-CmdPorts }
    "update" { Invoke-CmdUpdate }
    "doctor" { Invoke-CmdDoctor }
    default {
      throw "Unknown command: $Command"
    }
  }
  exit 0
} catch {
  Write-ErrorCli $_.Exception.Message
  if ($_.Exception.Message -like "Missing required binary:*") {
    exit 2
  }
  if ($_.Exception.Message -eq "Doctor found critical issues.") {
    exit 6
  }
  if ($_.Exception.Message -like "*failed to become healthy*") {
    exit 3
  }
  if ($_.Exception.Message -like "Refusing to stop*") {
    exit 4
  }
  exit 1
}
