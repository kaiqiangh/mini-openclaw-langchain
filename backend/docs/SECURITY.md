# Security Model

## Authentication

All `/api/v1/*` routes require `APP_ADMIN_TOKEN`, except `/health`, `/ready`, and
`/setup/status`. `/setup/configure` is also public only until the first admin
token has been configured.

Accepted forms:
- `Authorization: Bearer <token>`
- `Authorization: <token>` (raw, local compatibility)
- `X-Admin-Token` header
- `app_admin_token` cookie

## Known Limitations

### Python REPL (`python_repl`)

The Python REPL runs in a child process with restricted `__builtins__`, but this is
**not a true sandbox**. Python's introspection capabilities (`__class__.__bases__`,
`__subclasses__()`, frame objects) make pure-Python sandboxing impossible.

**Mitigations:**
- Runs in `multiprocessing.Process` (OS-level process isolation)
- 30-second timeout (SIGTERM + SIGKILL)
- Output truncated to 5000 chars

**What it CANNOT prevent:**
- Network access from the child process
- Filesystem reads (except by OS permissions)
- CPU/memory exhaustion within the timeout window

**For untrusted code execution, use Docker/gVisor with resource limits.**

### Terminal (`terminal`)

Terminal commands run under `sandbox-exec` (macOS) or `bwrap` (Linux) when available.
When no sandbox backend is detected and `require_sandbox=false`, commands run unsandboxed.

**Defense layers:**
1. Sandbox (OS-level filesystem/network isolation)
2. Command prefix denylist (blocks `rm`, `sudo`, `sh`, etc.)
3. Shell syntax blocking (blocks `|`, `&&`, `;`, `$()`, backticks)
4. Network command blocking (blocks `curl`, `wget`, `ssh`, etc.)
5. Fragment denylist (blocks `rm -rf /`, fork bombs)
6. Environment variable sanitization (strips `*KEY*`, `*TOKEN*`, `*SECRET*`, etc.)

### URL Fetch (`fetch_url`)

- Blocks private/loopback/link-local IP addresses
- DNS resolution failure → blocked (fail-closed)
- Redirect chain validated at each hop
- Max 2MB response body, max 3 redirects
- 15-second timeout

## Rate Limiting

Per-path rate limits:
- `/chat`: 60 req/min
- `/tokens/`: 120 req/min
- `/files`: 120 req/min

Global rate limit: 300 req/min across all API endpoints.

Backend: `InMemoryCoordinator` (default) or `SQLiteCoordinator` (`CONTROL_BACKEND=sqlite`).

## CORS

Allowed origins (configurable via `APP_ALLOWED_ORIGINS`):
- `http://localhost:3000`
- `http://127.0.0.1:3000`

Allowed headers are explicitly listed (not wildcard):
- `Authorization`
- `Content-Type`
- `X-Request-Id`
- `X-Admin-Token`
- `Accept`

## Security Headers

Applied to all responses:
- `X-Content-Type-Options: nosniff`
- `X-Frame-Options: DENY`
- `Referrer-Policy: no-referrer`
- `Permissions-Policy: camera=(), microphone=(), geolocation=()`
- `Cross-Origin-Resource-Policy: same-site`
