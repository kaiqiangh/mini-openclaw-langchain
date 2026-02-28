#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
OML="$ROOT_DIR/oml"

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

output_help="$($OML help)"
assert_contains "$output_help" "Usage: ./oml <command>"
assert_contains "$output_help" "start [all|backend|frontend]"

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
PATH="/usr/bin:/bin" bash "$ROOT_DIR/scripts/oml/cli.sh" doctor >/tmp/oml-doctor-missing-bin.out 2>&1
missing_rc=$?
set -e
if [ "$missing_rc" -ne 6 ]; then
  fail "doctor with missing binaries should exit 6, got $missing_rc"
fi
if ! grep -q "binary uv missing" /tmp/oml-doctor-missing-bin.out; then
  fail "doctor missing-bin output not found"
fi

rm -f /tmp/oml-invalid.out /tmp/oml-doctor-missing-bin.out

echo "[cli-smoke] PASS"
