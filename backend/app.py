from __future__ import annotations

import os
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Deque

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from api import agents, chat, compress, config_api, files, sessions, tokens, usage
from api.errors import ApiError, error_payload
from config import load_config, validate_required_secrets
from graph.agent import AgentManager
from scheduler.cron import CronScheduler
from scheduler.heartbeat import HeartbeatScheduler
from tools.skills_scanner import scan_skills
from utils.redaction import redact_text

BASE_DIR = Path(__file__).resolve().parent

agent_manager = AgentManager()
heartbeat_scheduler: HeartbeatScheduler | None = None
cron_scheduler: CronScheduler | None = None


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI) -> None:
        super().__init__(app)
        self._buckets: dict[str, Deque[float]] = defaultdict(deque)
        self._limits: list[tuple[str, int, int]] = [
            ("/api/chat", 60, 60),
            ("/api/tokens", 120, 60),
            ("/api/files", 120, 60),
        ]

    def _resolve_limit(self, path: str) -> tuple[int, int] | None:
        for prefix, limit, window_sec in self._limits:
            if path.startswith(prefix):
                return limit, window_sec
        return None

    async def dispatch(self, request: Request, call_next):
        limit_conf = self._resolve_limit(request.url.path)
        if limit_conf is not None:
            limit, window_sec = limit_conf
            now = time.time()
            client = request.client.host if request.client else "unknown"
            bucket_key = f"{client}:{request.url.path}"
            bucket = self._buckets[bucket_key]

            while bucket and now - bucket[0] > window_sec:
                bucket.popleft()

            if len(bucket) >= limit:
                return JSONResponse(
                    status_code=429,
                    content=error_payload(
                        code="rate_limit_exceeded",
                        message="Rate limit exceeded. Try again later.",
                        details={"limit": limit, "window_seconds": window_sec},
                    ),
                    headers={"Retry-After": "60"},
                )

            bucket.append(now)

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        return response


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


@asynccontextmanager
async def lifespan(_: FastAPI):
    global heartbeat_scheduler, cron_scheduler
    scan_skills(BASE_DIR)
    loaded = load_config(BASE_DIR)
    missing_secrets = validate_required_secrets(loaded.secrets)
    if missing_secrets:
        joined = ", ".join(missing_secrets)
        raise RuntimeError(f"Missing required secrets: {joined}")

    agent_manager.initialize(BASE_DIR)
    if agent_manager.memory_indexer is not None:
        agent_manager.memory_indexer.rebuild_index()

    if agent_manager.session_manager is None or agent_manager.memory_indexer is None:
        raise RuntimeError("AgentManager dependencies not initialized")

    chat.set_agent_manager(agent_manager)
    sessions.set_agent_manager(agent_manager)
    files.set_dependencies(BASE_DIR, agent_manager)
    tokens.set_dependencies(BASE_DIR, agent_manager)
    compress.set_agent_manager(agent_manager)
    config_api.set_base_dir(BASE_DIR)
    usage.set_agent_manager(agent_manager)
    agents.set_agent_manager(agent_manager)

    default_runtime = agent_manager.get_runtime("default")

    heartbeat_scheduler = HeartbeatScheduler(
        base_dir=default_runtime.root_dir,
        config=loaded.runtime.heartbeat,
        agent_manager=agent_manager,
        session_manager=default_runtime.session_manager,
    )
    cron_scheduler = CronScheduler(
        base_dir=default_runtime.root_dir,
        config=loaded.runtime.cron,
        agent_manager=agent_manager,
        session_manager=default_runtime.session_manager,
    )
    heartbeat_scheduler.start()
    cron_scheduler.start()

    try:
        yield
    finally:
        if heartbeat_scheduler is not None:
            await heartbeat_scheduler.stop()
            heartbeat_scheduler = None
        if cron_scheduler is not None:
            await cron_scheduler.stop()
            cron_scheduler = None


app = FastAPI(title="Mini-OpenClaw API", version="0.1.0", lifespan=lifespan)
trusted_hosts = _parse_csv_env("APP_TRUSTED_HOSTS", ["localhost", "127.0.0.1", "*.localhost"])
allowed_origins = _parse_csv_env(
    "APP_ALLOWED_ORIGINS",
    ["http://localhost:3000", "http://127.0.0.1:3000"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware)


@app.exception_handler(ApiError)
async def api_error_handler(_: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(code=exc.code, message=exc.message, details=exc.details),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [
        {
            "field": ".".join(str(part) for part in err.get("loc", []) if part != "body"),
            "message": err.get("msg", "Invalid value"),
            "code": err.get("type", "validation_error"),
        }
        for err in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=error_payload(
            code="validation_error",
            message="Request validation failed",
            details={"items": details},
        ),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_payload(
            code="internal_error",
            message="Internal server error",
            details={"exception": redact_text(str(exc))},
        ),
    )


app.include_router(chat.router, prefix="/api")
app.include_router(sessions.router, prefix="/api")
app.include_router(files.router, prefix="/api")
app.include_router(tokens.router, prefix="/api")
app.include_router(compress.router, prefix="/api")
app.include_router(config_api.router, prefix="/api")
app.include_router(usage.router, prefix="/api")
app.include_router(agents.router, prefix="/api")


@app.get("/api/health")
async def health() -> dict[str, str]:
    _ = load_config(BASE_DIR)
    return {"status": "ok"}
