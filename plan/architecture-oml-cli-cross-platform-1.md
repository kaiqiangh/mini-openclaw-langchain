---
goal: OML CLI environment, routing, and native Windows support implementation plan
version: 1.0
date_created: 2026-03-05
last_updated: 2026-03-05
owner: Codex
status: Planned
tags: [architecture, infrastructure, feature, cli, windows, frontend, backend]
---

# Introduction

![Status: Planned](https://img.shields.io/badge/status-Planned-blue)

This plan defines the exact implementation steps required to make the `oml` CLI deterministic for proxy env handling, make frontend API routing work in both CLI and manual development modes, and add native Windows PowerShell support without changing the product's local-first operating model.

## 1. Requirements & Constraints

- **REQ-001**: Preserve backend support for `APP_ENABLE_FRONTEND_PROXY` and `APP_FRONTEND_PROXY_URL` because they are consumed by `backend/app.py`.
- **REQ-002**: Remove hardcoded proxy env assignment from `scripts/oml/cli.sh` backend startup logic.
- **REQ-003**: Add CLI-owned proxy configuration with deterministic precedence using `.oml/config.env` and process env.
- **REQ-004**: Keep frontend API calls relative by default in `frontend/src/lib/api.ts`.
- **REQ-005**: Make manual development mode work with backend on `127.0.0.1:8000` and frontend on `127.0.0.1:3000` without requiring `NEXT_PUBLIC_API_BASE_URL`.
- **REQ-006**: Add native Windows PowerShell CLI support with parity for `help`, `version`, `start`, `stop`, `restart`, `status`, `logs`, `ports`, `update`, and `doctor`.
- **SEC-001**: Preserve current admin-token and backend proxy behavior without widening the public runtime surface.
- **CON-001**: Do not add Redis, WSL, container, or other new infrastructure dependencies.
- **CON-002**: Keep the repo-local command model and `.oml/` runtime state model.
- **GUD-001**: Keep documentation and `.env.example` consistent with actual runtime behavior.
- **PAT-001**: Prefer shared config semantics across bash and PowerShell, even if implementation differs by platform.

## 2. Implementation Steps

### Implementation Phase 1

- GOAL-001: Make bash CLI proxy handling explicit and deterministic.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-001 | Update `scripts/oml/cli.sh` config loading to resolve `OML_ENABLE_FRONTEND_PROXY` and `OML_FRONTEND_PROXY_URL` with explicit precedence from process env, `.oml/config.env`, and defaults. |  |  |
| TASK-002 | Refactor `backend_command()` in `scripts/oml/cli.sh` to stop hardcoding `APP_ENABLE_FRONTEND_PROXY='true'` and instead inject resolved proxy env values only when CLI configuration requires them. |  |  |
| TASK-003 | Update `cmd_ports`, `cmd_help`, and `scripts/oml/oml.md` to document effective proxy behavior and the new CLI-owned proxy config keys. |  |  |

### Implementation Phase 2

- GOAL-002: Make manual frontend development use relative API paths through a Next dev proxy.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-004 | Add dev rewrites in `frontend/next.config.js` so `/api/v1/:path*` proxies to `http://127.0.0.1:8000/api/v1/:path*` during `next dev`. |  |  |
| TASK-005 | Review and update `frontend/src/lib/api.ts`, `frontend/README.md`, and root `README.md` so relative API routing remains the default and `NEXT_PUBLIC_API_BASE_URL` is documented as optional override only. |  |  |
| TASK-006 | Update `backend/.env.example` and root/backend docs to clarify when backend proxy mode is enabled by CLI and when manual dev relies on the Next dev proxy instead. |  |  |

### Implementation Phase 3

- GOAL-003: Add native Windows PowerShell CLI support with command parity.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-007 | Add `oml.ps1` as the repo-root Windows entrypoint that dispatches to `scripts/oml/cli.ps1`. |  |  |
| TASK-008 | Implement `scripts/oml/cli.ps1` with native Windows support for config loading, PID/log file management, `Start-Process` detached startup, health checks, and safe stop behavior for backend and frontend. |  |  |
| TASK-009 | Ensure backend startup in `scripts/oml/cli.ps1` uses `.venv\\Scripts\\python.exe` and native Windows path handling, and ensure frontend startup uses native `npm exec -- next dev`. |  |  |

### Implementation Phase 4

- GOAL-004: Validate behavior and close documentation gaps.

| Task | Description | Completed | Date |
|------|-------------|-----------|------|
| TASK-010 | Add or update tests for CLI-related config behavior where practical, and add frontend coverage for dev-proxy expectations if testable in the existing setup. |  |  |
| TASK-011 | Run manual validation for `./oml start`, manual backend/frontend startup, and PowerShell command parity, then record the verified outcomes in docs. |  |  |
| TASK-012 | Update `scripts/oml/oml.md`, `README.md`, `frontend/README.md`, and `backend/README.md` so developer startup guidance is clear and deterministic across macOS, Linux, and Windows. |  |  |

## 3. Alternatives

- **ALT-001**: Use only `NEXT_PUBLIC_API_BASE_URL` for manual development. Rejected because it requires per-developer env setup and keeps routing behavior inconsistent across startup modes.
- **ALT-002**: Remove backend frontend-proxy mode from `./oml start`. Rejected because it breaks the current single-origin local operator experience.
- **ALT-003**: Create separate config formats for bash and PowerShell. Rejected because it increases maintenance burden and makes cross-platform docs harder to keep consistent.

## 4. Dependencies

- **DEP-001**: `backend/app.py` frontend proxy behavior must remain unchanged in semantics even if CLI env wiring changes.
- **DEP-002**: `frontend/next.config.js` must support dev rewrites without affecting production build behavior.
- **DEP-003**: Windows PowerShell support depends on native availability of `node`, `npm`, and either `uv` or the project virtualenv interpreter.
- **DEP-004**: Documentation changes depend on the final CLI config contract and startup semantics.

## 5. Files

- **FILE-001**: `scripts/oml/cli.sh` - bash CLI proxy config resolution and backend command refactor.
- **FILE-002**: `oml` - repo-root bash entrypoint, only if dispatch behavior or docs need minor adjustment.
- **FILE-003**: `frontend/next.config.js` - Next dev proxy rewrites.
- **FILE-004**: `frontend/src/lib/api.ts` - confirm relative API strategy and optional override behavior remain correct.
- **FILE-005**: `backend/.env.example` - clarify proxy and manual-dev guidance.
- **FILE-006**: `README.md` - root developer workflow documentation.
- **FILE-007**: `frontend/README.md` - frontend development and proxy behavior.
- **FILE-008**: `backend/README.md` - backend proxy and manual startup clarification.
- **FILE-009**: `scripts/oml/oml.md` - CLI guide update.
- **FILE-010**: `oml.ps1` - Windows entrypoint.
- **FILE-011**: `scripts/oml/cli.ps1` - Windows PowerShell implementation.

## 6. Testing

- **TEST-001**: Verify `./oml start` still starts backend and frontend successfully with backend proxy mode enabled by default.
- **TEST-002**: Verify manual startup works with backend on `127.0.0.1:8000` and frontend on `127.0.0.1:3000`, and `/api/v1/*` requests reach backend through the Next dev proxy.
- **TEST-003**: Verify CLI env precedence for proxy keys by testing process env, `.oml/config.env`, and default fallback behavior.
- **TEST-004**: Verify PowerShell `start`, `stop`, `restart`, `status`, and `logs` on native Windows.
- **TEST-005**: Verify docs and examples reference the correct ports, proxy modes, and config variables.

## 7. Risks & Assumptions

- **RISK-001**: Windows process signature validation may be less exact than POSIX process inspection and may require a pragmatic matching rule.
- **RISK-002**: Having both backend proxy mode and Next dev proxy mode may create confusion unless docs are explicit and concise.
- **RISK-003**: Frontend dev rewrites must not interfere with production behavior or static build output.
- **ASSUMPTION-001**: Native Windows users will have `node` and `npm` installed and will create the backend virtualenv under `backend\.venv`.
- **ASSUMPTION-002**: Reusing `.oml/config.env` across bash and PowerShell is acceptable and simpler than introducing a second config format.

## 8. Related Specifications / Further Reading

- `docs/plans/2026-03-05-oml-cli-design.md`
- `scripts/oml/oml.md`
- `README.md`
- `frontend/README.md`
- `backend/.env.example`
