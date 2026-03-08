# AGENTS.md

Guidance for coding agents that modify this repository.

## Project overview

Mini-OpenClaw is a local-first multi-agent workspace with:

- a FastAPI backend in `backend/`
- a Next.js frontend in `frontend/`
- a repo-local CLI in `./oml` and `./oml.ps1`
- per-agent workspaces under `backend/workspaces/<agent_id>/`

The backend owns runtime config, tool policy, scheduler behavior, template loading, and persistence. The frontend owns the operator UI and API client behavior.

## Repository map

- `backend/app.py`: FastAPI entrypoint, middleware, health/readiness, optional frontend proxy
- `backend/config.py`: runtime schema, config parsing, LLM profile/default loading
- `backend/config.json`: canonical repo-level runtime and provider config
- `backend/agent_templates/`: shipped template presets
- `backend/tests/backend/`: backend unit and API coverage
- `frontend/src/app/`: Next.js routes
- `frontend/src/lib/api.ts`: typed frontend API wrappers
- `frontend/src/components/`: UI components
- `docker-compose.yml`: Docker entrypoint for `prod` and `dev` profiles
- `docker/nginx/default.conf`: public edge routing for the production-like Docker profile

## Core commands

### Local

```bash
./oml start
./oml stop
./oml status
```

### Backend

```bash
cd backend
./.venv/bin/pytest -q
```

### Frontend

```bash
cd frontend
npm run test:run
npm run build
```

### Docker

```bash
cp .env.example .env
docker compose --profile prod up --build
docker compose --profile dev up --build
```

## Change boundaries

- Do not treat root `AGENTS.md` as a runtime prompt file. It is contributor guidance only.
- Do not confuse root docs with generated workspace files under `backend/workspaces/.../workspace/`.
- Keep `backend/config.json` as the source of truth for repo-level runtime defaults and provider configuration.
- Keep agent templates limited to `runtime_config` patches. Do not place secrets, `llm_profiles`, `llm_defaults`, or `agent_llm_overrides` in template files.
- Preserve current `./oml` local workflows when adding Docker or docs changes.

## Coding rules

- Prefer small, explicit changes over broad refactors.
- Keep Python and TypeScript changes consistent with existing file style.
- Favor self-explanatory names and straightforward control flow.
- Add comments only when they explain non-obvious intent.
- Update docs when behavior, commands, env vars, or file layout changes.

## Testing expectations

- Backend changes: run `cd backend && ./.venv/bin/pytest -q`.
- Frontend changes: run `cd frontend && npm run test:run && npm run build`.
- Docker changes: validate `docker compose --profile prod config` and `docker compose --profile dev config` when Docker is available.
- Template changes: ensure shipped templates still parse through the strict runtime config loader.

## Security considerations

- Never hardcode secrets or tokens in code, templates, Dockerfiles, or docs.
- Keep `APP_ADMIN_TOKEN` and provider API keys in runtime environment variables only.
- Preserve non-root container execution and minimal runtime images where Docker files already enforce it.
- Do not weaken terminal sandbox defaults or private-network blocking without a documented reason.
- Respect cookie/auth behavior:
  frontend browser auth relies on the `app_admin_token` cookie and same-origin API access.

## Documentation expectations

When relevant, update:

- `README.md` for operator-facing setup or runtime changes
- `CONTRIBUTING.md` for contributor workflow changes
- `backend/agent_templates/README.md` for template catalog or authoring-rule changes
