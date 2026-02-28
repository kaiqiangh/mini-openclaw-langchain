# `oml` CLI Guide

`oml` is a repo-local command (`./oml`) for running and operating Mini-OpenClaw without global installation.

## Requirements

- `bash`
- `uv`
- `node` + `npm`
- `curl`

## Quick Start

```bash
./oml help
./oml start
./oml status
./oml logs --follow
./oml stop
```

## Commands

### `./oml help`

Print command help and usage examples.

### `./oml version`

Prints:

- `oml`: CLI version
- `backend_api`: version parsed from `backend/app.py`
- `frontend`: version from `frontend/package.json`
- `git_sha`: current short commit SHA

### `./oml start [all|backend|frontend]`

Starts services in detached mode.

Defaults:

- target: `all`
- backend URL: `http://127.0.0.1:8002`
- frontend URL: `http://127.0.0.1:3000`

Behavior:

- idempotent if service already running
- writes PID files to `.oml/run/*.pid`
- writes logs to `.oml/log/*.log`
- health-checks services before returning success

### `./oml stop [all|backend|frontend]`

Stops managed services using PID files.

Behavior:

- graceful SIGTERM first, SIGKILL fallback
- idempotent when service is not running
- refuses to kill PID when command signature does not match expected service

### `./oml restart [all|backend|frontend]`

Equivalent to `stop` then `start` for target scope.

### `./oml status`

Prints service-level status with:

- `running/stopped`
- `pid` (when running)
- health state (`ok`, `degraded`, `down`)
- service URL

### `./oml logs [all|backend|frontend] [--follow] [--lines N]`

Shows logs from `.oml/log`.

Options:

- `--follow` / `-f`: tail continuously
- `--lines N`: number of lines to show (default `50`)

### `./oml ports`

Prints effective URL/ports used by CLI runtime config.

### `./oml update`

Performs **safe local sync only**:

- backend: creates `.venv` if missing, installs `requirements.txt` and optional `requirements-dev.txt`
- frontend: runs `npm ci` (or `npm install` if no lockfile)

Safety guarantee:

- does **not** run `git pull`, `git rebase`, `git reset`, or any git history mutation

### `./oml doctor`

Runs local diagnostics:

- required binaries present (`bash`, `uv`, `node`, `npm`, `curl`)
- `backend/.env` exists
- runtime port conflicts on backend/frontend ports
- health checks when services are already running

Exit code `6` indicates critical failures.

## Runtime State and Configuration

State root (default):

- `.oml/run/`
- `.oml/log/`

Optional config file:

- `.oml/config.env`

Supported keys:

```bash
OML_BACKEND_HOST=127.0.0.1
OML_BACKEND_PORT=8002
OML_FRONTEND_HOST=127.0.0.1
OML_FRONTEND_PORT=3000
OML_HEALTH_TIMEOUT_SECONDS=30
```

Environment variables override values from `.oml/config.env`.

## Exit Codes

- `0`: success
- `1`: invalid command or argument
- `2`: missing prerequisite binary
- `3`: service health/start timeout
- `4`: unsafe stop or start/runtime failure
- `5`: update failure
- `6`: doctor critical failure

## Troubleshooting

### `start` fails with backend health timeout

- Confirm secrets/config in `backend/.env`
- Inspect `.oml/log/backend.log`

### `start` fails with frontend timeout

- Confirm dependencies in `frontend/node_modules`
- Inspect `.oml/log/frontend.log`

### `stop` refuses to kill PID

A PID mismatch means the PID file does not represent an expected managed process. Remove stale PID files and retry:

```bash
rm -f .oml/run/*.pid
./oml status
```

## Manual Acceptance Checklist

- `./oml help` renders expected command table
- `./oml version` prints all four version fields
- `./oml start` starts backend+frontend and passes health checks
- `./oml status` reports both as running
- `./oml logs backend --lines 20` prints backend logs
- `./oml restart frontend` restarts frontend only
- `./oml stop` cleanly stops both services
