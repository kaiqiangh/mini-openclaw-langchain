#!/usr/bin/env bash
set -euo pipefail

OML_CLI_VERSION="0.1.0"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

STATE_DIR="${OML_STATE_DIR:-$REPO_ROOT/.oml}"
RUN_DIR="$STATE_DIR/run"
LOG_DIR="$STATE_DIR/log"
CONFIG_ENV="$STATE_DIR/config.env"

OML_BACKEND_HOST="${OML_BACKEND_HOST-}"
OML_BACKEND_PORT="${OML_BACKEND_PORT-}"
OML_FRONTEND_HOST="${OML_FRONTEND_HOST-}"
OML_FRONTEND_PORT="${OML_FRONTEND_PORT-}"
OML_HEALTH_TIMEOUT_SECONDS="${OML_HEALTH_TIMEOUT_SECONDS-}"
OML_ENABLE_FRONTEND_PROXY="${OML_ENABLE_FRONTEND_PROXY-}"
OML_FRONTEND_PROXY_URL="${OML_FRONTEND_PROXY_URL-}"

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

normalize_proxy_mode() {
  local raw="${1:-}"
  local normalized
  normalized="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    1|true|yes|on)
      printf '%s' "true"
      ;;
    0|false|no|off)
      printf '%s' "false"
      ;;
    inherit)
      printf '%s' "inherit"
      ;;
    *)
      return 1
      ;;
  esac
}

load_config_env() {
  local env_backend_host="${OML_BACKEND_HOST-}"
  local env_backend_port="${OML_BACKEND_PORT-}"
  local env_frontend_host="${OML_FRONTEND_HOST-}"
  local env_frontend_port="${OML_FRONTEND_PORT-}"
  local env_health_timeout="${OML_HEALTH_TIMEOUT_SECONDS-}"
  local env_enable_frontend_proxy="${OML_ENABLE_FRONTEND_PROXY-}"
  local env_frontend_proxy_url="${OML_FRONTEND_PROXY_URL-}"
  local env_backend_cmd="${OML_BACKEND_CMD-}"
  local env_frontend_cmd="${OML_FRONTEND_CMD-}"

  OML_BACKEND_HOST="127.0.0.1"
  OML_BACKEND_PORT="8000"
  OML_FRONTEND_HOST="127.0.0.1"
  OML_FRONTEND_PORT="3000"
  OML_HEALTH_TIMEOUT_SECONDS="30"
  OML_ENABLE_FRONTEND_PROXY="true"
  OML_FRONTEND_PROXY_URL=""

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
  if [ -n "$env_enable_frontend_proxy" ]; then
    OML_ENABLE_FRONTEND_PROXY="$env_enable_frontend_proxy"
  fi
  if [ -n "$env_frontend_proxy_url" ]; then
    OML_FRONTEND_PROXY_URL="$env_frontend_proxy_url"
  fi
  if [ -n "$env_backend_cmd" ]; then
    OML_BACKEND_CMD="$env_backend_cmd"
  fi
  if [ -n "$env_frontend_cmd" ]; then
    OML_FRONTEND_CMD="$env_frontend_cmd"
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

  if ! OML_ENABLE_FRONTEND_PROXY="$(normalize_proxy_mode "$OML_ENABLE_FRONTEND_PROXY")"; then
    error "OML_ENABLE_FRONTEND_PROXY must be true, false, or inherit"
    exit 1
  fi

  if [ -z "$OML_FRONTEND_PROXY_URL" ]; then
    OML_FRONTEND_PROXY_URL="http://$OML_FRONTEND_HOST:$OML_FRONTEND_PORT"
  fi

  export OML_BACKEND_HOST OML_BACKEND_PORT OML_FRONTEND_HOST OML_FRONTEND_PORT OML_HEALTH_TIMEOUT_SECONDS OML_ENABLE_FRONTEND_PROXY OML_FRONTEND_PROXY_URL
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
    printf 'http://%s:%s/api/v1/health' "$host" "$port"
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

validate_agent_id() {
  [[ "$1" =~ ^[A-Za-z0-9_-]{1,64}$ ]]
}

onboard_python_spec() {
  if [ -n "${OML_ONBOARD_PYTHON:-}" ]; then
    printf '%s' "$OML_ONBOARD_PYTHON"
    return
  fi
  if [ -x "$REPO_ROOT/backend/.venv/bin/python" ]; then
    printf '%s' "$REPO_ROOT/backend/.venv/bin/python"
    return
  fi
  if command -v python3 >/dev/null 2>&1; then
    printf '%s' "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    printf '%s' "python"
    return
  fi
  printf '%s' "3"
}

run_onboard_helper() {
  local python_spec
  python_spec="$(onboard_python_spec)"
  uv run --python "$python_spec" "$REPO_ROOT/cli/oml/onboard_helper.py" "$@"
}

contains_line() {
  local haystack="$1"
  local needle="$2"
  local line
  while IFS= read -r line; do
    if [ "$line" = "$needle" ]; then
      return 0
    fi
  done <<< "$haystack"
  return 1
}

lines_to_csv() {
  local lines="$1"
  local rendered=""
  local line
  while IFS= read -r line; do
    if [ -z "$line" ]; then
      continue
    fi
    if [ -n "$rendered" ]; then
      rendered="$rendered, "
    fi
    rendered="$rendered$line"
  done <<< "$lines"
  printf '%s' "$rendered"
}

normalize_on_off_flag() {
  local raw="${1:-}"
  local normalized
  normalized="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    on|off)
      printf '%s' "$normalized"
      ;;
    *)
      return 1
      ;;
  esac
}

normalize_true_false_flag() {
  local raw="${1:-}"
  local normalized
  normalized="$(printf '%s' "$raw" | tr '[:upper:]' '[:lower:]')"
  case "$normalized" in
    true|false)
      printf '%s' "$normalized"
      ;;
    on)
      printf '%s' "true"
      ;;
    off)
      printf '%s' "false"
      ;;
    *)
      return 1
      ;;
  esac
}

csv_to_lines() {
  local raw="$1"
  if [ -z "$raw" ]; then
    return 0
  fi
  printf '%s' "$raw" | tr ',' '\n' | sed 's/^[[:space:]]*//; s/[[:space:]]*$//' | awk 'NF'
}

join_csv() {
  local joined=""
  local item
  for item in "$@"; do
    if [ -z "$item" ]; then
      continue
    fi
    if [ -n "$joined" ]; then
      joined="$joined,"
    fi
    joined="$joined$item"
  done
  printf '%s' "$joined"
}

prompt_with_default() {
  local prompt="$1"
  local default_value="${2:-}"
  local answer

  if [ -n "$default_value" ]; then
    printf '%s [%s]: ' "$prompt" "$default_value" >&2
  else
    printf '%s: ' "$prompt" >&2
  fi
  IFS= read -r answer || return 1
  if [ -z "$answer" ]; then
    printf '%s' "$default_value"
    return 0
  fi
  printf '%s' "$answer"
}

prompt_on_off_value() {
  local prompt="$1"
  local default_value="$2"
  local answer
  while :; do
    answer="$(prompt_with_default "$prompt" "$default_value")" || return 1
    if answer="$(normalize_on_off_flag "$answer")"; then
      printf '%s' "$answer"
      return 0
    fi
    error "Expected on or off."
  done
}

load_onboard_prompt_defaults() {
  local agent_id="$1"
  local template_name="$2"
  local mode="$3"
  local output
  local key
  local value

  ONBOARD_PROMPT_LLM_DEFAULT=""
  ONBOARD_PROMPT_LLM_FALLBACKS=""
  ONBOARD_PROMPT_RAG_MODE="false"
  ONBOARD_PROMPT_CHAT_TOOLS=""
  ONBOARD_PROMPT_HEARTBEAT_TOOLS=""
  ONBOARD_PROMPT_CRON_TOOLS=""
  ONBOARD_PROMPT_MAX_STEPS=""
  ONBOARD_PROMPT_TIMEOUT_SECONDS=""
  ONBOARD_PROMPT_HEARTBEAT_ENABLED="false"
  ONBOARD_PROMPT_CRON_ENABLED="true"
  ONBOARD_PROMPT_TERMINAL_SANDBOX_MODE="hybrid_auto"
  ONBOARD_PROMPT_TERMINAL_POLICY_MODE="auto"

  if ! output="$(run_onboard_helper prompt-defaults --agent "$agent_id" --template "$template_name" --mode "$mode")"; then
    return 4
  fi

  while IFS='=' read -r key value; do
    case "$key" in
      llm_default)
        ONBOARD_PROMPT_LLM_DEFAULT="$value"
        ;;
      llm_fallbacks)
        ONBOARD_PROMPT_LLM_FALLBACKS="$value"
        ;;
      rag_mode)
        ONBOARD_PROMPT_RAG_MODE="$value"
        ;;
      chat_tools)
        ONBOARD_PROMPT_CHAT_TOOLS="$value"
        ;;
      heartbeat_tools)
        ONBOARD_PROMPT_HEARTBEAT_TOOLS="$value"
        ;;
      cron_tools)
        ONBOARD_PROMPT_CRON_TOOLS="$value"
        ;;
      max_steps)
        ONBOARD_PROMPT_MAX_STEPS="$value"
        ;;
      timeout_seconds)
        ONBOARD_PROMPT_TIMEOUT_SECONDS="$value"
        ;;
      heartbeat_enabled)
        ONBOARD_PROMPT_HEARTBEAT_ENABLED="$value"
        ;;
      cron_enabled)
        ONBOARD_PROMPT_CRON_ENABLED="$value"
        ;;
      terminal_sandbox_mode)
        ONBOARD_PROMPT_TERMINAL_SANDBOX_MODE="$value"
        ;;
      terminal_policy_mode)
        ONBOARD_PROMPT_TERMINAL_POLICY_MODE="$value"
        ;;
    esac
  done <<< "$output"
}

cmd_onboard() {
  local interactive=1
  local force=0
  local advanced_requested=0
  local agent_id=""
  local template_name=""
  local existing_mode=""
  local llm_default=""
  local llm_default_set=0
  local fallback_mode="inherit"
  local fallback_values=()
  local fallback_value=""
  local rag_mode=""
  local tool_preset=""
  local chat_tools_mode="inherit"
  local chat_tools_value=""
  local heartbeat_tools_mode="inherit"
  local heartbeat_tools_value=""
  local cron_tools_mode="inherit"
  local cron_tools_value=""
  local max_steps=""
  local timeout_seconds=""
  local terminal_sandbox_mode=""
  local terminal_policy_mode=""
  local heartbeat_enabled=""
  local cron_enabled=""
  local raw_templates=""
  local raw_routes=""
  local raw_tools=""
  local templates_display=""
  local routes_display=""
  local tools_display=""
  local arg_value
  local helper_output=""
  local helper_key
  local helper_value
  local summary_created="false"
  local summary_config_path=""
  local summary_llm_default=""
  local summary_llm_fallbacks=""
  local summary_rag_mode=""
  local default_prompt=""

  require_bin uv || return 2

  if [ ! -t 0 ] || [ ! -t 1 ]; then
    interactive=0
  fi

  while [ "$#" -gt 0 ]; do
    case "$1" in
      --agent)
        shift
        if [ "$#" -eq 0 ]; then
          error "--agent requires a value"
          return 1
        fi
        agent_id="$1"
        ;;
      --agent=*)
        agent_id="${1#*=}"
        ;;
      --template)
        shift
        if [ "$#" -eq 0 ]; then
          error "--template requires a value"
          return 1
        fi
        template_name="$1"
        ;;
      --template=*)
        template_name="${1#*=}"
        ;;
      --llm-default)
        shift
        if [ "$#" -eq 0 ]; then
          error "--llm-default requires a value"
          return 1
        fi
        llm_default="$1"
        llm_default_set=1
        ;;
      --llm-default=*)
        llm_default="${1#*=}"
        llm_default_set=1
        ;;
      --fallback)
        shift
        if [ "$#" -eq 0 ]; then
          error "--fallback requires a value"
          return 1
        fi
        fallback_value="$1"
        if [ "$(printf '%s' "$fallback_value" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
          if [ "${#fallback_values[@]}" -gt 0 ]; then
            error "--fallback none cannot be combined with other fallback routes"
            return 1
          fi
          fallback_mode="clear"
        else
          if [ "$fallback_mode" = "clear" ]; then
            error "--fallback none cannot be combined with other fallback routes"
            return 1
          fi
          fallback_mode="replace"
          fallback_values+=("$fallback_value")
        fi
        ;;
      --fallback=*)
        fallback_value="${1#*=}"
        if [ "$(printf '%s' "$fallback_value" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
          if [ "${#fallback_values[@]}" -gt 0 ]; then
            error "--fallback none cannot be combined with other fallback routes"
            return 1
          fi
          fallback_mode="clear"
        else
          if [ "$fallback_mode" = "clear" ]; then
            error "--fallback none cannot be combined with other fallback routes"
            return 1
          fi
          fallback_mode="replace"
          fallback_values+=("$fallback_value")
        fi
        ;;
      --rag-mode)
        shift
        if [ "$#" -eq 0 ]; then
          error "--rag-mode requires on or off"
          return 1
        fi
        if ! rag_mode="$(normalize_on_off_flag "$1")"; then
          error "--rag-mode must be on or off"
          return 1
        fi
        ;;
      --rag-mode=*)
        if ! rag_mode="$(normalize_on_off_flag "${1#*=}")"; then
          error "--rag-mode must be on or off"
          return 1
        fi
        ;;
      --tool-preset)
        shift
        if [ "$#" -eq 0 ]; then
          error "--tool-preset requires safe, balanced, or builder"
          return 1
        fi
        tool_preset="$1"
        ;;
      --tool-preset=*)
        tool_preset="${1#*=}"
        ;;
      --advanced)
        advanced_requested=1
        ;;
      --chat-tools)
        shift
        if [ "$#" -eq 0 ]; then
          error "--chat-tools requires a CSV value or none"
          return 1
        fi
        chat_tools_value="$1"
        advanced_requested=1
        ;;
      --chat-tools=*)
        chat_tools_value="${1#*=}"
        advanced_requested=1
        ;;
      --heartbeat-tools)
        shift
        if [ "$#" -eq 0 ]; then
          error "--heartbeat-tools requires a CSV value or none"
          return 1
        fi
        heartbeat_tools_value="$1"
        advanced_requested=1
        ;;
      --heartbeat-tools=*)
        heartbeat_tools_value="${1#*=}"
        advanced_requested=1
        ;;
      --cron-tools)
        shift
        if [ "$#" -eq 0 ]; then
          error "--cron-tools requires a CSV value or none"
          return 1
        fi
        cron_tools_value="$1"
        advanced_requested=1
        ;;
      --cron-tools=*)
        cron_tools_value="${1#*=}"
        advanced_requested=1
        ;;
      --max-steps)
        shift
        if [ "$#" -eq 0 ]; then
          error "--max-steps requires an integer"
          return 1
        fi
        max_steps="$1"
        advanced_requested=1
        ;;
      --max-steps=*)
        max_steps="${1#*=}"
        advanced_requested=1
        ;;
      --timeout-seconds)
        shift
        if [ "$#" -eq 0 ]; then
          error "--timeout-seconds requires an integer"
          return 1
        fi
        timeout_seconds="$1"
        advanced_requested=1
        ;;
      --timeout-seconds=*)
        timeout_seconds="${1#*=}"
        advanced_requested=1
        ;;
      --terminal-sandbox-mode)
        shift
        if [ "$#" -eq 0 ]; then
          error "--terminal-sandbox-mode requires a value"
          return 1
        fi
        terminal_sandbox_mode="$1"
        advanced_requested=1
        ;;
      --terminal-sandbox-mode=*)
        terminal_sandbox_mode="${1#*=}"
        advanced_requested=1
        ;;
      --terminal-policy-mode)
        shift
        if [ "$#" -eq 0 ]; then
          error "--terminal-policy-mode requires a value"
          return 1
        fi
        terminal_policy_mode="$1"
        advanced_requested=1
        ;;
      --terminal-policy-mode=*)
        terminal_policy_mode="${1#*=}"
        advanced_requested=1
        ;;
      --heartbeat)
        shift
        if [ "$#" -eq 0 ]; then
          error "--heartbeat requires on or off"
          return 1
        fi
        if ! heartbeat_enabled="$(normalize_on_off_flag "$1")"; then
          error "--heartbeat must be on or off"
          return 1
        fi
        advanced_requested=1
        ;;
      --heartbeat=*)
        if ! heartbeat_enabled="$(normalize_on_off_flag "${1#*=}")"; then
          error "--heartbeat must be on or off"
          return 1
        fi
        advanced_requested=1
        ;;
      --cron)
        shift
        if [ "$#" -eq 0 ]; then
          error "--cron requires on or off"
          return 1
        fi
        if ! cron_enabled="$(normalize_on_off_flag "$1")"; then
          error "--cron must be on or off"
          return 1
        fi
        advanced_requested=1
        ;;
      --cron=*)
        if ! cron_enabled="$(normalize_on_off_flag "${1#*=}")"; then
          error "--cron must be on or off"
          return 1
        fi
        advanced_requested=1
        ;;
      --non-interactive)
        interactive=0
        ;;
      --force)
        force=1
        ;;
      *)
        error "Unknown onboard option: $1"
        return 1
        ;;
    esac
    shift
  done

  if [ -n "$max_steps" ] && ! is_integer "$max_steps"; then
    error "--max-steps must be an integer"
    return 1
  fi
  if [ -n "$timeout_seconds" ] && ! is_integer "$timeout_seconds"; then
    error "--timeout-seconds must be an integer"
    return 1
  fi

  if [ -n "$tool_preset" ]; then
    case "$tool_preset" in
      safe|balanced|builder)
        ;;
      *)
        error "--tool-preset must be safe, balanced, or builder"
        return 1
        ;;
    esac
  fi
  if [ -n "$terminal_sandbox_mode" ]; then
    case "$terminal_sandbox_mode" in
      hybrid_auto|darwin_sandbox|linux_bwrap|unsafe_none)
        ;;
      *)
        error "--terminal-sandbox-mode must be hybrid_auto, darwin_sandbox, linux_bwrap, or unsafe_none"
        return 1
        ;;
    esac
  fi
  if [ -n "$terminal_policy_mode" ]; then
    case "$terminal_policy_mode" in
      auto|allowlist|denylist)
        ;;
      *)
        error "--terminal-policy-mode must be auto, allowlist, or denylist"
        return 1
        ;;
    esac
  fi

  if ! raw_templates="$(run_onboard_helper list-templates)"; then
    return 4
  fi
  if ! raw_routes="$(run_onboard_helper list-llm-routes)"; then
    return 4
  fi
  if ! raw_tools="$(run_onboard_helper list-tools)"; then
    return 4
  fi

  templates_display="$(lines_to_csv "$raw_templates")"
  routes_display="$(lines_to_csv "$raw_routes")"
  tools_display="$(lines_to_csv "$raw_tools")"

  if [ -z "$agent_id" ]; then
    if [ "$interactive" -eq 0 ]; then
      error "--agent is required in non-interactive mode"
      return 1
    fi
    while :; do
      agent_id="$(prompt_with_default "Agent ID" "$agent_id")" || return 1
      if validate_agent_id "$agent_id"; then
        break
      fi
      error "agent_id must match [A-Za-z0-9_-]{1,64}"
    done
  elif ! validate_agent_id "$agent_id"; then
    error "agent_id must match [A-Za-z0-9_-]{1,64}"
    return 1
  fi

  if [ -n "$template_name" ] && [ "$template_name" != "none" ] && ! contains_line "$raw_templates" "$template_name"; then
    error "Unknown template: $template_name"
    return 1
  fi

  if [ "$llm_default_set" -eq 1 ] && ! contains_line "$raw_routes" "$llm_default"; then
    error "Unknown LLM route: $llm_default"
    return 1
  fi

  if [ "$fallback_mode" = "replace" ]; then
    for fallback_value in "${fallback_values[@]}"; do
      if ! contains_line "$raw_routes" "$fallback_value"; then
        error "Unknown LLM route: $fallback_value"
        return 1
      fi
    done
  fi

  for arg_value in "$chat_tools_value" "$heartbeat_tools_value" "$cron_tools_value"; do
    if [ -z "$arg_value" ] || [ "$(printf '%s' "$arg_value" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
      continue
    fi
    while IFS= read -r helper_value; do
      if [ -z "$helper_value" ]; then
        continue
      fi
      if ! contains_line "$raw_tools" "$helper_value"; then
        error "Unknown tool name: $helper_value"
        return 1
      fi
    done <<< "$(csv_to_lines "$arg_value")"
  done

  if [ -d "$REPO_ROOT/backend/workspaces/$agent_id" ]; then
    if [ "$interactive" -eq 0 ]; then
      if [ "$force" -ne 1 ]; then
        error "Agent already exists: $agent_id. Re-run with --force to reset from defaults or a template."
        return 1
      fi
      existing_mode="reset"
    elif [ "$force" -eq 1 ]; then
      existing_mode="reset"
    else
      while :; do
        arg_value="$(prompt_with_default "Agent exists. Choose mode: edit|reset|cancel" "edit")" || return 1
        case "$arg_value" in
          edit|reset)
            existing_mode="$arg_value"
            break
            ;;
          cancel)
            info "Onboarding cancelled."
            return 0
            ;;
          *)
            error "Expected edit, reset, or cancel."
            ;;
        esac
      done
    fi
  else
    existing_mode="create"
  fi

  if [ "$existing_mode" = "edit" ]; then
    if [ -n "$template_name" ] && [ "$template_name" != "none" ]; then
      warn "Ignoring template for edit mode; existing config is used as the base."
    fi
    template_name="none"
  elif [ -z "$template_name" ]; then
    if [ "$interactive" -eq 1 ]; then
      if [ -n "$templates_display" ]; then
        info "Templates available: none, $templates_display"
      else
        info "No templates available; repo defaults will be used."
      fi
      while :; do
        template_name="$(prompt_with_default "Base template (none for repo defaults)" "none")" || return 1
        if [ "$template_name" = "none" ] || contains_line "$raw_templates" "$template_name"; then
          break
        fi
        error "Unknown template: $template_name"
      done
    else
      template_name="none"
    fi
  fi

  if ! load_onboard_prompt_defaults "$agent_id" "$template_name" "$existing_mode"; then
    return 4
  fi

  if [ "$interactive" -eq 1 ]; then
    if [ -n "$routes_display" ]; then
      info "LLM routes: $routes_display"
    fi
    if [ "$llm_default_set" -eq 0 ]; then
      while :; do
        default_prompt="$(prompt_with_default "Default LLM route" "$ONBOARD_PROMPT_LLM_DEFAULT")" || return 1
        if [ -n "$default_prompt" ] && contains_line "$raw_routes" "$default_prompt"; then
          llm_default="$default_prompt"
          llm_default_set=1
          break
        fi
        error "Choose one of the available LLM routes."
      done
    fi

    if [ "$fallback_mode" = "inherit" ]; then
      default_prompt="$(prompt_with_default "Fallback LLM routes CSV (blank keeps current, none clears)" "$ONBOARD_PROMPT_LLM_FALLBACKS")" || return 1
      if [ -n "$default_prompt" ]; then
        if [ "$(printf '%s' "$default_prompt" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
          fallback_mode="clear"
          fallback_values=()
        else
          fallback_mode="replace"
          fallback_values=()
          while IFS= read -r helper_value; do
            if [ -z "$helper_value" ]; then
              continue
            fi
            if ! contains_line "$raw_routes" "$helper_value"; then
              error "Unknown LLM route: $helper_value"
              return 1
            fi
            fallback_values+=("$helper_value")
          done <<< "$(csv_to_lines "$default_prompt")"
        fi
      fi
    fi

    if [ -z "$rag_mode" ]; then
      if [ "$ONBOARD_PROMPT_RAG_MODE" = "true" ]; then
        rag_mode="on"
      else
        rag_mode="off"
      fi
      rag_mode="$(prompt_on_off_value "Enable RAG (on/off)" "$rag_mode")" || return 1
    fi

    if [ -z "$tool_preset" ]; then
      while :; do
        tool_preset="$(prompt_with_default "Tool preset: safe|balanced|builder" "balanced")" || return 1
        case "$tool_preset" in
          safe|balanced|builder)
            break
            ;;
          *)
            error "Expected safe, balanced, or builder."
            ;;
        esac
      done
    fi

    if [ "$advanced_requested" -eq 0 ]; then
      arg_value="$(prompt_with_default "Open advanced settings? yes|no" "no")" || return 1
      case "$(printf '%s' "$arg_value" | tr '[:upper:]' '[:lower:]')" in
        y|yes)
          advanced_requested=1
          ;;
      esac
    fi

    if [ "$advanced_requested" -eq 1 ]; then
      if [ -z "$max_steps" ]; then
        max_steps="$(prompt_with_default "Max steps" "$ONBOARD_PROMPT_MAX_STEPS")" || return 1
      fi
      if [ -z "$timeout_seconds" ]; then
        timeout_seconds="$(prompt_with_default "LLM timeout seconds" "$ONBOARD_PROMPT_TIMEOUT_SECONDS")" || return 1
      fi
      if [ -z "$heartbeat_enabled" ]; then
        if [ "$ONBOARD_PROMPT_HEARTBEAT_ENABLED" = "true" ]; then
          heartbeat_enabled="on"
        else
          heartbeat_enabled="off"
        fi
        heartbeat_enabled="$(prompt_on_off_value "Enable heartbeat (on/off)" "$heartbeat_enabled")" || return 1
      fi
      if [ -z "$cron_enabled" ]; then
        if [ "$ONBOARD_PROMPT_CRON_ENABLED" = "true" ]; then
          cron_enabled="on"
        else
          cron_enabled="off"
        fi
        cron_enabled="$(prompt_on_off_value "Enable cron (on/off)" "$cron_enabled")" || return 1
      fi
      if [ -z "$terminal_sandbox_mode" ]; then
        terminal_sandbox_mode="$(prompt_with_default "Terminal sandbox mode" "$ONBOARD_PROMPT_TERMINAL_SANDBOX_MODE")" || return 1
      fi
      if [ -z "$terminal_policy_mode" ]; then
        terminal_policy_mode="$(prompt_with_default "Terminal policy mode" "$ONBOARD_PROMPT_TERMINAL_POLICY_MODE")" || return 1
      fi

      arg_value="$(prompt_with_default "Override enabled tool lists? yes|no" "no")" || return 1
      case "$(printf '%s' "$arg_value" | tr '[:upper:]' '[:lower:]')" in
        y|yes)
          info "Available tools: $tools_display"
          if [ -z "$chat_tools_value" ]; then
            chat_tools_value="$(prompt_with_default "Chat tools CSV (blank keeps current, none clears)" "$ONBOARD_PROMPT_CHAT_TOOLS")" || return 1
          fi
          if [ -z "$heartbeat_tools_value" ]; then
            heartbeat_tools_value="$(prompt_with_default "Heartbeat tools CSV (blank keeps current, none clears)" "$ONBOARD_PROMPT_HEARTBEAT_TOOLS")" || return 1
          fi
          if [ -z "$cron_tools_value" ]; then
            cron_tools_value="$(prompt_with_default "Cron tools CSV (blank keeps current, none clears)" "$ONBOARD_PROMPT_CRON_TOOLS")" || return 1
          fi
          ;;
      esac
    fi
  fi

  if [ -n "$chat_tools_value" ]; then
    if [ "$(printf '%s' "$chat_tools_value" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
      chat_tools_mode="clear"
    else
      chat_tools_mode="replace"
    fi
  fi
  if [ -n "$heartbeat_tools_value" ]; then
    if [ "$(printf '%s' "$heartbeat_tools_value" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
      heartbeat_tools_mode="clear"
    else
      heartbeat_tools_mode="replace"
    fi
  fi
  if [ -n "$cron_tools_value" ]; then
    if [ "$(printf '%s' "$cron_tools_value" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
      cron_tools_mode="clear"
    else
      cron_tools_mode="replace"
    fi
  fi

  if [ -n "$max_steps" ] && ! is_integer "$max_steps"; then
    error "Max steps must be an integer."
    return 1
  fi
  if [ -n "$timeout_seconds" ] && ! is_integer "$timeout_seconds"; then
    error "LLM timeout seconds must be an integer."
    return 1
  fi
  if [ -n "$terminal_sandbox_mode" ]; then
    case "$terminal_sandbox_mode" in
      hybrid_auto|darwin_sandbox|linux_bwrap|unsafe_none)
        ;;
      *)
        error "Terminal sandbox mode is invalid."
        return 1
        ;;
    esac
  fi
  if [ -n "$terminal_policy_mode" ]; then
    case "$terminal_policy_mode" in
      auto|allowlist|denylist)
        ;;
      *)
        error "Terminal policy mode is invalid."
        return 1
        ;;
    esac
  fi

  for arg_value in "$chat_tools_value" "$heartbeat_tools_value" "$cron_tools_value"; do
    if [ -z "$arg_value" ] || [ "$(printf '%s' "$arg_value" | tr '[:upper:]' '[:lower:]')" = "none" ]; then
      continue
    fi
    while IFS= read -r helper_value; do
      if [ -z "$helper_value" ]; then
        continue
      fi
      if ! contains_line "$raw_tools" "$helper_value"; then
        error "Unknown tool name: $helper_value"
        return 1
      fi
    done <<< "$(csv_to_lines "$arg_value")"
  done

  if [ "$interactive" -eq 1 ]; then
    printf '[oml] Onboarding summary:\n' >&2
    printf '  agent_id: %s\n' "$agent_id" >&2
    printf '  mode: %s\n' "$existing_mode" >&2
    printf '  template: %s\n' "${template_name:-none}" >&2
    printf '  llm_default: %s\n' "$llm_default" >&2
    if [ "$fallback_mode" = "replace" ]; then
      printf '  llm_fallbacks: %s\n' "$(join_csv "${fallback_values[@]}")" >&2
    elif [ "$fallback_mode" = "clear" ]; then
      printf '  llm_fallbacks: none\n' >&2
    else
      printf '  llm_fallbacks: inherited\n' >&2
    fi
    printf '  rag_mode: %s\n' "$rag_mode" >&2
    printf '  tool_preset: %s\n' "$tool_preset" >&2
    arg_value="$(prompt_with_default "Write config now? yes|no" "yes")" || return 1
    case "$(printf '%s' "$arg_value" | tr '[:upper:]' '[:lower:]')" in
      n|no)
        info "Onboarding cancelled."
        return 0
        ;;
    esac
  fi

  local helper_args=(
    apply
    --agent "$agent_id"
    --mode "$existing_mode"
    --template "${template_name:-none}"
    --tool-preset "${tool_preset:-balanced}"
  )

  if [ "$llm_default_set" -eq 1 ]; then
    helper_args+=(--llm-default "$llm_default")
  fi
  if [ "$fallback_mode" = "clear" ]; then
    helper_args+=(--clear-fallbacks)
  elif [ "$fallback_mode" = "replace" ]; then
    helper_args+=(--fallbacks "$(join_csv "${fallback_values[@]}")")
  fi
  if [ -n "$rag_mode" ]; then
    helper_args+=(--rag-mode "$(normalize_true_false_flag "$rag_mode")")
  fi
  if [ -n "$chat_tools_value" ]; then
    helper_args+=(--chat-tools "$chat_tools_value" --chat-tools-mode "$chat_tools_mode")
  fi
  if [ -n "$heartbeat_tools_value" ]; then
    helper_args+=(--heartbeat-tools "$heartbeat_tools_value" --heartbeat-tools-mode "$heartbeat_tools_mode")
  fi
  if [ -n "$cron_tools_value" ]; then
    helper_args+=(--cron-tools "$cron_tools_value" --cron-tools-mode "$cron_tools_mode")
  fi
  if [ -n "$max_steps" ]; then
    helper_args+=(--max-steps "$max_steps")
  fi
  if [ -n "$timeout_seconds" ]; then
    helper_args+=(--timeout-seconds "$timeout_seconds")
  fi
  if [ -n "$terminal_sandbox_mode" ]; then
    helper_args+=(--terminal-sandbox-mode "$terminal_sandbox_mode")
  fi
  if [ -n "$terminal_policy_mode" ]; then
    helper_args+=(--terminal-policy-mode "$terminal_policy_mode")
  fi
  if [ -n "$heartbeat_enabled" ]; then
    helper_args+=(--heartbeat "$heartbeat_enabled")
  fi
  if [ -n "$cron_enabled" ]; then
    helper_args+=(--cron "$cron_enabled")
  fi

  if ! helper_output="$(run_onboard_helper "${helper_args[@]}")"; then
    return 4
  fi

  while IFS='=' read -r helper_key helper_value; do
    case "$helper_key" in
      agent_id)
        agent_id="$helper_value"
        ;;
      config_path)
        summary_config_path="$helper_value"
        ;;
      created)
        summary_created="$helper_value"
        ;;
      llm_default)
        summary_llm_default="$helper_value"
        ;;
      llm_fallbacks)
        summary_llm_fallbacks="$helper_value"
        ;;
      rag_mode)
        summary_rag_mode="$helper_value"
        ;;
    esac
  done <<< "$helper_output"

  if [ "$summary_created" = "true" ]; then
    info "Created agent workspace: $agent_id"
  else
    info "Updated agent workspace: $agent_id"
  fi
  info "Agent config: $summary_config_path"
  info "LLM default: $summary_llm_default"
  if [ -n "$summary_llm_fallbacks" ]; then
    info "LLM fallbacks: $summary_llm_fallbacks"
  else
    info "LLM fallbacks: none"
  fi
  info "RAG mode: $summary_rag_mode"
  info "Next steps: ./oml start  &&  ./oml status"
  return 0
}

backend_command() {
  local proxy_prefix=""
  if [ -n "${OML_BACKEND_CMD:-}" ]; then
    printf '%s' "$OML_BACKEND_CMD"
    return
  fi

  case "$OML_ENABLE_FRONTEND_PROXY" in
    true)
      proxy_prefix="APP_ENABLE_FRONTEND_PROXY='true' APP_FRONTEND_PROXY_URL='$OML_FRONTEND_PROXY_URL' "
      ;;
    false)
      proxy_prefix="APP_ENABLE_FRONTEND_PROXY='false' "
      ;;
    inherit)
      proxy_prefix=""
      ;;
  esac

  printf '%s' "cd '$REPO_ROOT/backend' && ${proxy_prefix}exec uv run --python .venv/bin/python uvicorn app:app --host '$OML_BACKEND_HOST' --port '$OML_BACKEND_PORT'"
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
  onboard [options]             Create or reconfigure an agent config (Bash only)
  logs [all|backend|frontend] [--follow] [--lines N]
                                Show logs (default target: all, default lines: 50)
  ports                         Show effective host/port URLs
  update                        Safe local dependency sync (no git history mutation)
  doctor                        Validate local prerequisites and runtime readiness

Runtime state:
  .oml/run/*.pid               Managed process IDs
  .oml/log/*.log               Service logs
  .oml/config.env              Optional overrides

Proxy defaults:
  OML_ENABLE_FRONTEND_PROXY=true
  OML_FRONTEND_PROXY_URL=http://127.0.0.1:3000
  OML_ENABLE_FRONTEND_PROXY=inherit lets backend/.env control APP_ENABLE_FRONTEND_PROXY

Examples:
  ./oml start
  ./oml onboard --agent alpha
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
  local manual_dev_proxy_target="${NEXT_DEV_API_PROXY_URL:-http://127.0.0.1:8000}"
  printf 'backend_health_url: http://%s:%s/api/v1/health\n' "$OML_BACKEND_HOST" "$OML_BACKEND_PORT"
  printf 'frontend_dev_url: http://%s:%s\n' "$OML_FRONTEND_HOST" "$OML_FRONTEND_PORT"
  printf 'manual_dev_api_proxy_url: %s/api/v1\n' "${manual_dev_proxy_target%/}"
  printf 'backend_frontend_proxy_mode: %s\n' "$OML_ENABLE_FRONTEND_PROXY"
  if [ "$OML_ENABLE_FRONTEND_PROXY" = "inherit" ]; then
    printf 'backend_frontend_proxy_url: inherited from backend env\n'
    return
  fi
  printf 'backend_frontend_proxy_url: %s\n' "$OML_FRONTEND_PROXY_URL"
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
    if [ -f "requirements-pdf.txt" ]; then
      uv pip install --python .venv/bin/python -r requirements-pdf.txt
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

  if [ "$OML_ENABLE_FRONTEND_PROXY" = "inherit" ]; then
    printf '  [ok]   frontend proxy mode inherited from backend env\n'
  else
    printf '  [ok]   frontend proxy mode %s (%s)\n' "$OML_ENABLE_FRONTEND_PROXY" "$OML_FRONTEND_PROXY_URL"
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
    onboard)
      cmd_onboard "$@"
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
