#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"

fail() {
  echo "[cli-smoke] FAIL: $*" >&2
  exit 1
}

assert_contains() {
  local haystack="$1"
  local needle="$2"
  if [[ "$haystack" != *"$needle"* ]]; then
    fail "expected output to contain: $needle"
  fi
}

assert_file_contains() {
  local path="$1"
  local needle="$2"
  if ! grep -q "$needle" "$path"; then
    fail "expected $path to contain: $needle"
  fi
}

create_fixture() {
  local tmpdir
  tmpdir="$(mktemp -d)"
  mkdir -p \
    "$tmpdir/cli/oml" \
    "$tmpdir/backend/agent_templates" \
    "$tmpdir/backend/workspaces" \
    "$tmpdir/frontend"
  cp "$ROOT_DIR/oml" "$tmpdir/oml"
  cp "$ROOT_DIR/cli/oml/cli.sh" "$tmpdir/cli/oml/cli.sh"
  cp "$ROOT_DIR/cli/oml/onboard_helper.py" "$tmpdir/cli/oml/onboard_helper.py"
  cp "$ROOT_DIR/backend/config.py" "$tmpdir/backend/config.py"
  cp "$ROOT_DIR/backend/config.json" "$tmpdir/backend/config.json"
  cp "$ROOT_DIR/backend/app.py" "$tmpdir/backend/app.py"
  cp "$ROOT_DIR/frontend/package.json" "$tmpdir/frontend/package.json"
  cp "$ROOT_DIR"/backend/agent_templates/*.json "$tmpdir/backend/agent_templates/"
  : > "$tmpdir/backend/.env"
  chmod +x "$tmpdir/oml" "$tmpdir/cli/oml/cli.sh"
  printf '%s' "$tmpdir"
}

TMP_REPO="$(create_fixture)"
OML="$TMP_REPO/oml"

cleanup() {
  rm -rf "$TMP_REPO"
  rm -f \
    /tmp/oml-invalid.out \
    /tmp/oml-doctor-missing-bin.out \
    /tmp/oml-onboard-missing-agent.out \
    /tmp/oml-onboard-existing.out \
    /tmp/oml-onboard-invalid-llm.out \
    /tmp/oml-onboard-invalid-agent.out \
    /tmp/oml-onboard-invalid-template.out \
    /tmp/oml-onboard-invalid-tool.out
}
trap cleanup EXIT

output_help="$($OML help)"
assert_contains "$output_help" "Usage: ./oml <command>"
assert_contains "$output_help" "onboard [options]"

output_version="$($OML version)"
assert_contains "$output_version" "oml:"
assert_contains "$output_version" "backend_api:"
assert_contains "$output_version" "frontend:"
assert_contains "$output_version" "git_sha:"

set +e
$OML does-not-exist >/tmp/oml-invalid.out 2>&1
invalid_rc=$?
set -e
if [ "$invalid_rc" -eq 0 ]; then
  fail "invalid command unexpectedly succeeded"
fi
if ! grep -q "Unknown command" /tmp/oml-invalid.out; then
  fail "invalid command output missing expected message"
fi

set +e
PATH="/usr/bin:/bin" bash "$TMP_REPO/cli/oml/cli.sh" doctor >/tmp/oml-doctor-missing-bin.out 2>&1
missing_rc=$?
set -e
if [ "$missing_rc" -ne 6 ]; then
  fail "doctor with missing binaries should exit 6, got $missing_rc"
fi
if ! grep -q "binary uv missing" /tmp/oml-doctor-missing-bin.out; then
  fail "doctor missing-bin output not found"
fi

set +e
$OML onboard --non-interactive >/tmp/oml-onboard-missing-agent.out 2>&1
missing_agent_rc=$?
set -e
if [ "$missing_agent_rc" -eq 0 ]; then
  fail "onboard without --agent unexpectedly succeeded"
fi
if ! grep -q -- "--agent is required" /tmp/oml-onboard-missing-agent.out; then
  fail "onboard missing-agent output not found"
fi

PATH="/usr/bin:/bin" "$OML" onboard --non-interactive --agent alpha --llm-default deepseek.chat --fallback openai.gpt_4o_mini --rag-mode on --tool-preset builder >/dev/null

alpha_config="$TMP_REPO/backend/workspaces/alpha/config.json"
if [ ! -f "$alpha_config" ]; then
  fail "onboard did not create agent config"
fi
assert_file_contains "$alpha_config" '"default": "deepseek.chat"'
assert_file_contains "$alpha_config" '"command_policy_mode": "denylist"'
assert_file_contains "$alpha_config" '"apply_patch"'
assert_file_contains "$alpha_config" '"rag_mode": true'

set +e
$OML onboard --non-interactive --agent alpha --tool-preset safe >/tmp/oml-onboard-existing.out 2>&1
existing_rc=$?
set -e
if [ "$existing_rc" -eq 0 ]; then
  fail "onboard existing agent without --force unexpectedly succeeded"
fi
if ! grep -q "Agent already exists" /tmp/oml-onboard-existing.out; then
  fail "onboard existing-agent output not found"
fi

before_invalid_llm="$(cat "$alpha_config")"
set +e
$OML onboard --non-interactive --force --agent alpha --llm-default not-a-route >/tmp/oml-onboard-invalid-llm.out 2>&1
invalid_llm_rc=$?
set -e
if [ "$invalid_llm_rc" -eq 0 ]; then
  fail "onboard invalid llm unexpectedly succeeded"
fi
if ! grep -q "Unknown LLM route" /tmp/oml-onboard-invalid-llm.out; then
  fail "onboard invalid-llm output not found"
fi
after_invalid_llm="$(cat "$alpha_config")"
if [ "$before_invalid_llm" != "$after_invalid_llm" ]; then
  fail "invalid llm route should not modify existing config"
fi

$OML onboard --non-interactive --force --agent alpha --llm-default deepseek.chat --fallback none --rag-mode off --tool-preset safe --chat-tools none >/dev/null

assert_file_contains "$alpha_config" '"rag_mode": false'
if grep -q '"apply_patch"' "$alpha_config"; then
  fail "safe reset should remove apply_patch from agent config"
fi

set +e
$OML onboard --non-interactive --agent "bad id" >/tmp/oml-onboard-invalid-agent.out 2>&1
invalid_agent_rc=$?
set -e
if [ "$invalid_agent_rc" -eq 0 ]; then
  fail "onboard invalid agent id unexpectedly succeeded"
fi
if ! grep -q "agent_id must match" /tmp/oml-onboard-invalid-agent.out; then
  fail "onboard invalid-agent output not found"
fi

set +e
$OML onboard --non-interactive --agent beta --template missing-template >/tmp/oml-onboard-invalid-template.out 2>&1
invalid_template_rc=$?
set -e
if [ "$invalid_template_rc" -eq 0 ]; then
  fail "onboard invalid template unexpectedly succeeded"
fi
if ! grep -q "Unknown template" /tmp/oml-onboard-invalid-template.out; then
  fail "onboard invalid-template output not found"
fi

set +e
$OML onboard --non-interactive --agent beta --chat-tools terminal,not_a_tool >/tmp/oml-onboard-invalid-tool.out 2>&1
invalid_tool_rc=$?
set -e
if [ "$invalid_tool_rc" -eq 0 ]; then
  fail "onboard invalid tool unexpectedly succeeded"
fi
if ! grep -q "Unknown tool name" /tmp/oml-onboard-invalid-tool.out; then
  fail "onboard invalid-tool output not found"
fi

echo "[cli-smoke] PASS"
