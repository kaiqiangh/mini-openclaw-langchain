# Contributing

Thanks for contributing to Mini-OpenClaw.

## Before you start

- Use a focused branch for each change.
- Keep changes scoped and documented.
- If you change runtime behavior, templates, Docker assets, or auth/security settings, update the relevant docs in the same PR.

## Local setup

### Option A: repo CLI

```bash
./oml start
```

### Option B: manual local setup

Backend:

```bash
cd backend
uv venv .venv
uv pip install --python .venv/bin/python -r requirements.txt
cp .env.example .env
uv run --python .venv/bin/python uvicorn app:app --host 127.0.0.1 --port 8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev
```

### Option C: Docker

```bash
cp .env.example .env
docker compose --profile prod up --build -d
```

Production-like Docker serves the app at `http://localhost:8080` through Nginx.
For live reload, use:

```bash
docker compose --profile dev up --build -d
```

That exposes the frontend at `http://localhost:3000` and the backend at `http://localhost:8000`.

## Workflow

1. Create a branch from the latest mainline state.
2. Make the smallest coherent change that solves the problem.
3. Add or update tests when behavior changes.
4. Update docs when commands, env vars, templates, Docker assets, or public behavior change.
5. Run the relevant checks before opening a PR.

## Required checks

Backend:

```bash
cd backend
./.venv/bin/pytest -q
```

Frontend:

```bash
cd frontend
npm run test:run
npm run build
```

Docker changes:

```bash
docker compose --profile prod config
docker compose --profile dev config
```

## Pull request expectations

- Explain what changed and why.
- Call out any config, env var, or deployment impact.
- Mention any follow-up work that was intentionally left out.
- Include screenshots only when UI behavior changed.
- Keep unrelated cleanup out of the PR.

## Documentation rules

Update these files when applicable:

- `README.md`: operator setup, runtime behavior, Docker usage
- `AGENTS.md`: repo-specific guidance for coding agents
- `backend/agent_templates/README.md`: template structure, loading, or catalog changes

## Coding standards

- Match existing Python and TypeScript style in the touched files.
- Prefer clear names and simple control flow over abstraction-heavy changes.
- Avoid direct mutation when a copy/update pattern is clearer.
- Validate new config or request payload shapes through the existing schema/parsing layers.

## Security

- Keep secrets in environment variables only.
- Do not commit `.env` files or sample secrets.
- Preserve auth, sandbox, and network-hardening defaults unless the change explicitly requires otherwise.
- Document any security-relevant behavior changes in the PR description.
