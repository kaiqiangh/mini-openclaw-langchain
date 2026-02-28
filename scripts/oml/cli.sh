#!/usr/bin/env bash
set -euo pipefail

OML_CLI_VERSION="0.1.0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

STATE_DIR="${OML_STATE_DIR:-$REPO_ROOT/.oml}"
RUN_DIR="$STATE_DIR/run"
LOG_DIR="$STATE_DIR/log"
CONFIG_ENV="$STATE_DIR/config.env"

OML_BACKEND_HOST=""
OML_BACKEND_PORT=""
OML_FRONTEND_HOST=""
OML_FRONTEND_PORT=""
OML_HEALTH_TIMEOUT_SECONDS=""

info() {
  printf '[oml] %s\n' "$*"
}

warn() {
  printf '[oml] WARN: %s\n' "$*" >&2
}

error() {
  printf '[oml] ERROR: %s\n' "$*" >&2
}

ensure_runtime_dirs() {
  umask 077
  mkdir -p "$RUN_DIR" "$LOG_DIR"
}

is_integer() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

load_config_env() {
  local env_backend_host="${OML_BACKEND_HOST-}"
  local env_backend_port="${OML_BACKEND_PORT-}"
  local env_frontend_host="${OML_FRONTEND_HOST-}"
  local env_frontend_port="${OML_FRONTEND_PORT-}"
  local env_health_timeout="${OML_HEALTH_TIMEOUT_SECONDS-}"

  OML_BACKEND_HOST="127.0.0.1"
  OML_BACKEND_PORT="8002"
  OML_FRONTEND_HOST="127.0.0.1"
  OML_FRONTEND_PORT="3000"
  OML_HEALTH_TIMEOUT_SECONDS="30"

  if [ -f "$CONFIG_ENV" ]; then
    # shellcheck disable=SC1090
    source "$CONFIG_ENV"
  fi

  if [ -n "$env_backend_host" ]; then
    OML_BACKEND_HOST="$env_backend_host"
  fi
  if [ -n "$env_backend_port" ]; then
    OML_BACKEND_PORT="$env_backend_port"
  fi
  if [ -n "$env_frontend_host" ]; then
    OML_FRONTEND_HOST="$env_frontend_host"
  fi
  if [ -n "$env_frontend_port" ]; then
    OML_FRONTEND_PORT="$env_frontend_port"
  fi
  if [ -n "$env_health_timeout" ]; then
    OML_HEALTH_TIMEOUT_SECONDS="$env_health_timeout"
  fi

  if ! is_integer "$OML_BACKEND_PORT"; then
    error "OML_BACKEND_PORT must be an integer"
    exit 1
  fi
  if ! is_integer "$OML_FRONTEND_PORT"; then
    error "OML_FRONTEND_PORT must be an integer"
    exit 1
  fi
  if ! is_integer "$OML_HEALTH_TIMEOUT_SECONDS"; then
    error "OML_HEALTH_TIMEOUT_SECONDS must be an integer"
    exit 1
  fi

  export OML_BACKEND_HOST OML_BACKEND_PORT OML_FRONTEND_HOST OML_FRONTEND_PORT OML_HEALTH_TIMEOUT_SECONDS
}

pid_file_for() {
  printf '%s/%s.pid' "$RUN_DIR" "$1"
}

log_file_for() {
  printf '%s/%s.log' "$LOG_DIR" "$1"
}

service_port() {
  if [ "$1" = "backend" ]; then
    printf '%s' "$OML_BACKEND_PORT"
    return
  fi
  printf '%s' "$OML_FRONTEND_PORT"
}

service_host() {
  if [ "$1" = "backend" ]; then
    printf '%s' "$OML_BACKEND_HOST"
    return
  fi
  printf '%s' "$OML_FRONTEND_HOST"
}

service_url() {
  local service="$1"
  local host
  local port
  host="$(service_host "$service")"
  port="$(service_port "$service")"
  if [ "$service" = "backend" ]; then
    printf 'http://%s:%s/api/health' "$host" "$port"
    return
  fi
  printf 'http://%s:%s' "$host" "$port"
}

service_signature() {
  if [ "$1" = "backend" ]; then
    printf '%s' 'uvicorn app:app'
    return
  fi
  printf '%s' 'next dev'
}

read_pid() {
  local service="$1"
  local pid_file
  local pid
  pid_file="$(pid_file_for "$service")"
  if [ ! -f "$pid_file" ]; then
    return 1
  fi
  pid="$(tr -d '[:space:]' < "$pid_file")"
  if ! is_integer "$pid"; then
    return 1
  fi
  printf '%s' "$pid"
}

is_pid_running() {
  local pid="$1"
  if ! is_integer "$pid"; then
    return 1
  fi
  kill -0 "$pid" >/dev/null 2>&1
}

pid_command() {
  local pid="$1"
  ps -p "$pid" -o command= 2>/dev/null | sed 's/^[[:space:]]*//'
}

pid_matches_service() {
  local pid="$1"
  local service="$2"
  local cmd
  local sig
  cmd="$(pid_command "$pid")"
  sig="$(service_signature "$service")"
  if [ -z "$cmd" ]; then
    return 1
  fi
  if [[ "$cmd" == *"$sig"* ]]; then
    return 0
  fi
  return 1
}

cleanup_pid() {
  local service="$1"
  local pid_file
  pid_file="$(pid_file_for "$service")"
  rm -f "$pid_file"
}

is_service_running() {
  local service="$1"
  local pid
  if ! pid="$(read_pid "$service")"; then
    return 1
  fi
  if ! is_pid_running "$pid"; then
    cleanup_pid "$service"
    return 1
  fi
  if ! pid_matches_service "$pid" "$service"; then
    warn "Ignoring stale PID for $service (pid=$pid did not match signature)."
    cleanup_pid "$service"
    return 1
  fi
  return 0
}

require_bin() {
  local bin="$1"
  if ! command -v "$bin" >/dev/null 2>&1; then
    error "Missing required binary: $bin"
    return 2
  fi
  return 0
}

is_port_in_use() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn "sport = :$port" 2>/dev/null | awk 'NR>1 {found=1} END{exit found?0:1}'
    return $?
  fi
  if command -v netstat >/dev/null 2>&1; then
    netstat -an 2>/dev/null | grep -E "[\.:]$port[[:space:]]" | grep -q LISTEN
    return $?
  fi
  return 2
}

port_owner_pid() {
  local port="$1"
  if command -v lsof >/dev/null 2>&1; then
    lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1
    return 0
  fi
  printf ''
}

assert_target() {
  case "$1" in
    all|backend|frontend)
      return 0
      ;;
    *)
      error "Invalid target: $1 (expected all|backend|frontend)"
      return 1
      ;;
  esac
}

backend_command() {
  if [ -n "${OML_BACKEND_CMD:-}" ]; then
    printf '%s' "$OML_BACKEND_CMD"
    return
  fi
  printf '%s' "cd '$REPO_ROOT/backend' && exec uv run --python .venv/bin/python uvicorn app:app --host '$OML_BACKEND_HOST' --port '$OML_BACKEND_PORT'"
}

frontend_command() {
  if [ -n "${OML_FRONTEND_CMD:-}" ]; then
    printf '%s' "$OML_FRONTEND_CMD"
    return
  fi
  printf '%s' "cd '$REPO_ROOT/frontend' && exec npm exec -- next dev -p '$OML_FRONTEND_PORT' -H '$OML_FRONTEND_HOST'"
}

start_service() {
  local service="$1"
  local pid_file
  local log_file
  local cmd

  ensure_runtime_dirs
  pid_file="$(pid_file_for "$service")"
  log_file="$(log_file_for "$service")"

  if is_service_running "$service"; then
    info "$service is already running (pid $(read_pid "$service"))."
    return 0
  fi

  cmd="$(backend_command)"
  if [ "$service" = "frontend" ]; then
    cmd="$(frontend_command)"
  fi

  nohup bash -lc "$cmd" >>"$log_file" 2>&1 &
  local pid=$!
  printf '%s\n' "$pid" > "$pid_file"
  info "Started $service (pid=$pid)."
  return 0
}

check_service_health() {
  local service="$1"
  local url
  url="$(service_url "$service")"

  if curl -fsS --max-time 2 "$url" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

wait_for_health() {
  local service="$1"
  local timeout="$OML_HEALTH_TIMEOUT_SECONDS"
  local waited=0

  if [ "${OML_SKIP_HEALTH:-0}" = "1" ]; then
    return 0
  fi

  while [ "$waited" -lt "$timeout" ]; do
    if ! is_service_running "$service"; then
      return 1
    fi
    if check_service_health "$service"; then
      return 0
    fi
    sleep 1
    waited=$((waited + 1))
  done

  return 1
}

stop_service() {
  local service="$1"
  local pid

  if ! pid="$(read_pid "$service")"; then
    info "$service is not running."
    return 0
  fi

  if ! is_pid_running "$pid"; then
    cleanup_pid "$service"
    info "$service pid file was stale and has been cleaned."
    return 0
  fi

  if ! pid_matches_service "$pid" "$service"; then
    error "Refusing to stop $service: pid $pid does not match expected signature."
    return 4
  fi

  kill "$pid" >/dev/null 2>&1 || true
  local waited=0
  while is_pid_running "$pid" && [ "$waited" -lt 10 ]; do
    sleep 1
    waited=$((waited + 1))
  done

  if is_pid_running "$pid"; then
    kill -9 "$pid" >/dev/null 2>&1 || true
  fi

  cleanup_pid "$service"
  info "Stopped $service."
  return 0
}

cmd_help() {
  cat <<'HELP'
Usage: ./oml <command> [options]

Commands:
  help                          Show command help
  version                       Print CLI, backend, frontend, and git versions
  start [all|backend|frontend]  Start services in background (default: all)
  stop [all|backend|frontend]   Stop services (default: all)
  restart [all|backend|frontend] Restart services (default: all)
  status                        Show runtime status and health
  logs [all|backend|frontend] [--follow] [--lines N]
                                Show logs (default target: all, default lines: 50)
  ports                         Show effective host/port URLs
  update                        Safe local dependency sync (no git history mutation)
  doctor                        Validate local prerequisites and runtime readiness

Runtime state:
  .oml/run/*.pid               Managed process IDs
  .oml/log/*.log               Service logs
  .oml/config.env              Optional overrides

Examples:
  ./oml start
  ./oml restart backend
  ./oml logs backend --follow
  ./oml update
HELP
}

cmd_version() {
  local backend_version
  local frontend_version
  local git_sha

  backend_version="$(grep -Eo 'version="[^"]+"' "$REPO_ROOT/backend/app.py" | head -n 1 | sed -E 's/version="([^"]+)"/\1/' || true)"
  if [ -z "$backend_version" ]; then
    backend_version="unknown"
  fi

  frontend_version="$(grep -Eo '"version"[[:space:]]*:[[:space:]]*"[^"]+"' "$REPO_ROOT/frontend/package.json" | head -n 1 | sed -E 's/.*"([^"]+)"$/\1/' || true)"
  if [ -z "$frontend_version" ]; then
    frontend_version="unknown"
  fi

  git_sha="$(git -C "$REPO_ROOT" rev-parse --short HEAD 2>/dev/null || true)"
  if [ -z "$git_sha" ]; then
    git_sha="unknown"
  fi

  printf 'oml: %s\n' "$OML_CLI_VERSION"
  printf 'backend_api: %s\n' "$backend_version"
  printf 'frontend: %s\n' "$frontend_version"
  printf 'git_sha: %s\n' "$git_sha"
}

cmd_start() {
  local target="${1:-all}"
  local started_backend=0
  local started_frontend=0

  assert_target "$target" || return 1

  if [ "$target" = "all" ] || [ "$target" = "backend" ]; then
    require_bin uv || return 2
    require_bin curl || return 2
  fi
  if [ "$target" = "all" ] || [ "$target" = "frontend" ]; then
    require_bin npm || return 2
    require_bin curl || return 2
  fi

  if [ "$target" = "all" ] || [ "$target" = "backend" ]; then
    if ! is_service_running backend; then
      if ! start_service backend; then
        return 4
      fi
      started_backend=1
    else
      info "backend already running."
    fi
    if ! wait_for_health backend; then
      error "backend failed to become healthy."
      if [ "$started_backend" -eq 1 ]; then
        stop_service backend >/dev/null 2>&1 || true
      fi
      return 3
    fi
  fi

  if [ "$target" = "all" ] || [ "$target" = "frontend" ]; then
    if ! is_service_running frontend; then
      if ! start_service frontend; then
        if [ "$target" = "all" ] && [ "$started_backend" -eq 1 ]; then
          stop_service backend >/dev/null 2>&1 || true
        fi
        return 4
      fi
      started_frontend=1
    else
      info "frontend already running."
    fi
    if ! wait_for_health frontend; then
      error "frontend failed to become healthy."
      if [ "$started_frontend" -eq 1 ]; then
        stop_service frontend >/dev/null 2>&1 || true
      fi
      if [ "$target" = "all" ] && [ "$started_backend" -eq 1 ]; then
        stop_service backend >/dev/null 2>&1 || true
      fi
      return 3
    fi
  fi

  info "Start command completed."
  return 0
}

cmd_stop() {
  local target="${1:-all}"
  local rc=0

  assert_target "$target" || return 1

  if [ "$target" = "all" ] || [ "$target" = "frontend" ]; then
    if ! stop_service frontend; then
      rc=$?
    fi
  fi
  if [ "$target" = "all" ] || [ "$target" = "backend" ]; then
    if ! stop_service backend; then
      rc=$?
    fi
  fi

  return "$rc"
}

cmd_restart() {
  local target="${1:-all}"
  cmd_stop "$target" || true
  cmd_start "$target"
}

print_service_status() {
  local service="$1"
  local pid
  local health="down"
  local url
  local port

  url="$(service_url "$service")"
  port="$(service_port "$service")"

  if is_service_running "$service"; then
    pid="$(read_pid "$service")"
    if check_service_health "$service"; then
      health="ok"
    else
      health="degraded"
    fi
    printf '%-8s running  pid=%s  health=%s  url=%s\n' "$service" "$pid" "$health" "$url"
    return
  fi

  if is_port_in_use "$port"; then
    printf '%-8s stopped  port=%s in use by another process\n' "$service" "$port"
    return
  fi

  printf '%-8s stopped  url=%s\n' "$service" "$url"
}

cmd_status() {
  print_service_status backend
  print_service_status frontend
}

show_logs_for_service() {
  local service="$1"
  local lines="$2"
  local follow="$3"
  local log_file

  log_file="$(log_file_for "$service")"
  if [ ! -f "$log_file" ]; then
    warn "No log file for $service yet: $log_file"
    return 0
  fi

  if [ "$follow" -eq 1 ]; then
    tail -n "$lines" -f "$log_file"
    return 0
  fi

  printf '== %s (%s) ==\n' "$service" "$log_file"
  tail -n "$lines" "$log_file"
}

cmd_logs() {
  local target="all"
  local lines=50
  local follow=0

  while [ "$#" -gt 0 ]; do
    case "$1" in
      all|backend|frontend)
        target="$1"
        ;;
      --follow|-f)
        follow=1
        ;;
      --lines)
        shift
        if [ "$#" -eq 0 ]; then
          error "--lines requires a value"
          return 1
        fi
        lines="$1"
        ;;
      --lines=*)
        lines="${1#*=}"
        ;;
      *)
        error "Unknown logs option: $1"
        return 1
        ;;
    esac
    shift
  done

  if ! is_integer "$lines"; then
    error "--lines must be an integer"
    return 1
  fi

  if [ "$target" = "all" ]; then
    if [ "$follow" -eq 1 ]; then
      local backend_log
      local frontend_log
      backend_log="$(log_file_for backend)"
      frontend_log="$(log_file_for frontend)"
      touch "$backend_log" "$frontend_log"
      tail -n "$lines" -f "$backend_log" "$frontend_log"
      return 0
    fi
    show_logs_for_service backend "$lines" 0
    echo
    show_logs_for_service frontend "$lines" 0
    return 0
  fi

  show_logs_for_service "$target" "$lines" "$follow"
}

cmd_ports() {
  printf 'backend_url: http://%s:%s/api/health\n' "$OML_BACKEND_HOST" "$OML_BACKEND_PORT"
  printf 'frontend_url: http://%s:%s\n' "$OML_FRONTEND_HOST" "$OML_FRONTEND_PORT"
}

cmd_update() {
  require_bin uv || return 2
  require_bin npm || return 2

  info "Syncing backend dependencies..."
  (
    cd "$REPO_ROOT/backend"
    if [ ! -x ".venv/bin/python" ]; then
      uv venv .venv
    fi
    uv pip install --python .venv/bin/python -r requirements.txt
    if [ -f "requirements-dev.txt" ]; then
      uv pip install --python .venv/bin/python -r requirements-dev.txt
    fi
  ) || return 5

  info "Syncing frontend dependencies..."
  (
    cd "$REPO_ROOT/frontend"
    if [ -f "package-lock.json" ]; then
      npm ci
    else
      npm install
    fi
  ) || return 5

  info "Dependency sync complete."
  info "No git pull/rebase/reset executed."
  git -C "$REPO_ROOT" status --short || true
}

cmd_doctor() {
  local critical=0
  local owner
  local backend_pid
  local frontend_pid

  printf 'Doctor checks:\n'

  for bin in bash uv node npm curl; do
    if command -v "$bin" >/dev/null 2>&1; then
      printf '  [ok]   binary %s\n' "$bin"
    else
      printf '  [fail] binary %s missing\n' "$bin"
      critical=1
    fi
  done

  if [ -f "$REPO_ROOT/backend/.env" ]; then
    printf '  [ok]   backend/.env present\n'
  else
    printf '  [fail] backend/.env missing\n'
    critical=1
  fi

  if is_service_running backend; then
    backend_pid="$(read_pid backend)"
    if check_service_health backend; then
      printf '  [ok]   backend running (pid=%s) and healthy\n' "$backend_pid"
    else
      printf '  [warn] backend running (pid=%s) but health check failed\n' "$backend_pid"
    fi
  else
    if is_port_in_use "$OML_BACKEND_PORT"; then
      owner="$(port_owner_pid "$OML_BACKEND_PORT")"
      if [ -n "$owner" ]; then
        printf '  [fail] backend port %s in use by pid %s\n' "$OML_BACKEND_PORT" "$owner"
      else
        printf '  [fail] backend port %s in use\n' "$OML_BACKEND_PORT"
      fi
      critical=1
    else
      printf '  [ok]   backend port %s available\n' "$OML_BACKEND_PORT"
    fi
  fi

  if is_service_running frontend; then
    frontend_pid="$(read_pid frontend)"
    if check_service_health frontend; then
      printf '  [ok]   frontend running (pid=%s) and reachable\n' "$frontend_pid"
    else
      printf '  [warn] frontend running (pid=%s) but HTTP check failed\n' "$frontend_pid"
    fi
  else
    if is_port_in_use "$OML_FRONTEND_PORT"; then
      owner="$(port_owner_pid "$OML_FRONTEND_PORT")"
      if [ -n "$owner" ]; then
        printf '  [fail] frontend port %s in use by pid %s\n' "$OML_FRONTEND_PORT" "$owner"
      else
        printf '  [fail] frontend port %s in use\n' "$OML_FRONTEND_PORT"
      fi
      critical=1
    else
      printf '  [ok]   frontend port %s available\n' "$OML_FRONTEND_PORT"
    fi
  fi

  if [ "$critical" -ne 0 ]; then
    error "Doctor found critical issues."
    return 6
  fi

  info "Doctor passed."
  return 0
}

main() {
  load_config_env

  local cmd="${1:-help}"
  if [ "$#" -gt 0 ]; then
    shift
  fi

  case "$cmd" in
    help|-h|--help)
      cmd_help "$@"
      ;;
    version)
      cmd_version "$@"
      ;;
    start)
      cmd_start "$@"
      ;;
    stop)
      cmd_stop "$@"
      ;;
    restart)
      cmd_restart "$@"
      ;;
    status)
      cmd_status "$@"
      ;;
    logs)
      cmd_logs "$@"
      ;;
    ports)
      cmd_ports "$@"
      ;;
    update)
      cmd_update "$@"
      ;;
    doctor)
      cmd_doctor "$@"
      ;;
    *)
      error "Unknown command: $cmd"
      cmd_help
      return 1
      ;;
  esac
}

main "$@"
