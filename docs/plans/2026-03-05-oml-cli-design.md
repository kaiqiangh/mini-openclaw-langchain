# OML CLI Review and Cross-Platform Design

Date: 2026-03-05
Status: Approved design
Scope: `oml` CLI environment handling, frontend/backend connectivity, and Windows PowerShell support

## 1. Context

The repository currently provides a bash-only CLI through:

- `./oml`
- `scripts/oml/cli.sh`

The CLI starts the backend with frontend proxy mode forced on by injecting:

- `APP_ENABLE_FRONTEND_PROXY='true'`
- `APP_FRONTEND_PROXY_URL='http://<frontend-host>:<frontend-port>'`

The repository also supports manual local development with:

- backend on `127.0.0.1:8000`
- frontend on `127.0.0.1:3000`

The frontend API client uses relative paths by default, which means manual frontend development currently needs a proxy or explicit API-base override to reach the backend correctly.

## 2. Observed Implementation Facts

### Backend proxy envs are real and used

`backend/app.py` consumes:

- `APP_ENABLE_FRONTEND_PROXY`
- `APP_FRONTEND_PROXY_URL`

The backend uses these to decide whether it should proxy non-API routes to the frontend dev server.

### Backend `.env` is loaded but not allowed to override explicit process env

`backend/config.py` calls `load_dotenv(..., override=False)`, which means any env vars injected by the CLI take precedence over `backend/.env`.

### Frontend currently has no dev proxy

`frontend/src/lib/api.ts` uses relative paths by default unless `NEXT_PUBLIC_API_BASE_URL` is set.

`frontend/next.config.js` currently has no rewrites or proxy behavior.

### Windows support does not exist

There is no PowerShell CLI or Windows-native entrypoint in the repo today.

## 3. Design Goals

- Keep `./oml start` working as a single-origin local operator mode
- Make proxy behavior explicit and configurable instead of hidden inside a hardcoded command string
- Make manual development work without changing frontend API code
- Add native Windows PowerShell CLI support with command parity
- Avoid adding new infrastructure or heavyweight packaging

## 4. Chosen Approach

The approved approach is:

1. Keep backend frontend-proxy support as a first-class feature
2. Remove hardcoded proxy env assignment from bash CLI startup logic
3. Add CLI-owned proxy config keys with explicit precedence
4. Add a Next dev proxy for manual frontend development
5. Add native PowerShell CLI support for Windows

This preserves the current product ergonomics while eliminating hidden env overrides and manual-dev routing ambiguity.

## 5. Design

### 5.1 Environment Ownership and Precedence

Keep:

- `APP_ENABLE_FRONTEND_PROXY`
- `APP_FRONTEND_PROXY_URL`

Do not remove these variables. They are required by the backend.

Add CLI-level settings:

- `OML_ENABLE_FRONTEND_PROXY`
- `OML_FRONTEND_PROXY_URL`

Precedence model:

1. explicit process env
2. `.oml/config.env`
3. CLI defaults
4. backend `.env` when CLI does not supply proxy envs

Default CLI behavior:

- `./oml start all` enables backend frontend-proxy mode
- `./oml start backend` enables backend frontend-proxy mode
- CLI computes `OML_FRONTEND_PROXY_URL` from frontend host and port unless explicitly overridden

This keeps backend standalone behavior intact while making CLI behavior configurable and visible.

### 5.2 Frontend and Backend Connectivity

Keep frontend API calls relative by default.

For `./oml start`:

- browser origin stays on `127.0.0.1:8000`
- backend proxies frontend pages
- API requests remain same-origin at `/api/v1/*`

For manual development:

- browser origin stays on `127.0.0.1:3000`
- add Next dev rewrites in `frontend/next.config.js`
- rewrite `/api/v1/:path*` to `http://127.0.0.1:8000/api/v1/:path*`

Keep `NEXT_PUBLIC_API_BASE_URL` only as an advanced override, not as the default developer path.

### 5.3 Bash CLI

Refactor `scripts/oml/cli.sh` so that:

- proxy env handling is loaded from config instead of hardcoded into `backend_command`
- resolved backend startup env is deterministic and documented
- existing command surface remains unchanged:
  - `help`
  - `version`
  - `start`
  - `stop`
  - `restart`
  - `status`
  - `logs`
  - `ports`
  - `update`
  - `doctor`

### 5.4 PowerShell CLI

Add:

- `oml.ps1`
- `scripts/oml/cli.ps1`

Windows execution must be native:

- backend via `.venv\Scripts\python.exe`
- frontend via native `npm`

Command parity target:

- `start`
- `stop`
- `restart`
- `status`
- `logs`
- `ports`
- `update`
- `doctor`
- `version`
- `help`

Windows implementation model:

- `Start-Process` for detached services
- PID files in `.oml/run`
- logs in `.oml/log`
- health checks using PowerShell HTTP requests
- process validation before stop

### 5.5 Documentation and Env Files

Update:

- `backend/.env.example`
- `README.md`
- `frontend/README.md`
- `backend/README.md`
- `scripts/oml/oml.md`

Documentation must clearly distinguish:

- CLI single-origin mode
- manual frontend dev proxy mode
- optional explicit API-base override
- Windows PowerShell usage

## 6. Alternatives Considered

### Alternative A: frontend env override only

Rejected because it forces developers to manage `NEXT_PUBLIC_API_BASE_URL` manually and creates different mental models for CLI mode and manual dev mode.

### Alternative B: remove backend proxy entirely

Rejected because it would remove the current single-origin `./oml start` experience and make the local operator workflow worse.

### Alternative C: separate Windows config format

Rejected because it creates unnecessary duplication. A shared `.oml/config.env` file is sufficient if PowerShell parses simple `KEY=value` entries.

## 7. Testing Expectations

The design implies the following validation targets:

- `./oml start` still works with backend frontend-proxy mode
- manual dev with backend `8000` and frontend `3000` works without frontend code changes
- bash CLI respects proxy env precedence
- PowerShell CLI supports native Windows backend and frontend startup
- docs and examples align with the implemented behavior

## 8. Risks and Boundaries

Risks:

- process matching on Windows will not be identical to POSIX process checks
- maintaining command parity across bash and PowerShell can drift if behavior is not documented clearly
- supporting both backend proxy mode and Next dev proxy mode introduces two transport paths that must stay consistent

Boundaries:

- no new infrastructure dependency
- no removal of backend proxy support
- no shift away from relative frontend API paths
- no WSL dependency for Windows users

## 9. Next Step

The next step after this approved design is to create a concrete implementation plan that enumerates the exact file-level changes and validation steps.
