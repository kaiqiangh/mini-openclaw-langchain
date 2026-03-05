from __future__ import annotations

import asyncio
import hmac
import os
import time
import uuid
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.types import ASGIApp
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from api import (
    agents,
    chat,
    compress,
    config_api,
    files,
    scheduler_api,
    sessions,
    tokens,
    usage,
)
from api.errors import ApiError, error_payload
from config import load_config, validate_required_secrets
from control import LocalCoordinator, build_local_coordinator
from graph.agent import AgentManager
from scheduler.cron import CronScheduler
from scheduler.heartbeat import HeartbeatScheduler
from utils.redaction import redact_text

BASE_DIR = Path(__file__).resolve().parent

agent_manager = AgentManager()
heartbeat_scheduler: HeartbeatScheduler | None = None
cron_scheduler: CronScheduler | None = None
local_coordinator: LocalCoordinator = build_local_coordinator(BASE_DIR)
_TRUTHY = {"1", "true", "yes", "on"}
_PROXY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    return raw in _TRUTHY


def _frontend_proxy_url() -> str:
    return (os.getenv("APP_FRONTEND_PROXY_URL", "") or "").strip().rstrip("/")


def _forward_frontend_request(
    outbound: UrlRequest,
) -> tuple[int, bytes, dict[str, str]]:
    try:
        with urlopen(outbound, timeout=30) as upstream:
            payload = upstream.read()
            headers = {
                key: value
                for key, value in upstream.headers.items()
                if key.lower() not in _PROXY_HOP_HEADERS
            }
            return upstream.status, payload, headers
    except HTTPError as exc:
        payload = exc.read() if hasattr(exc, "read") else b""
        headers = {
            key: value
            for key, value in getattr(exc, "headers", {}).items()
            if key.lower() not in _PROXY_HOP_HEADERS
        }
        return int(exc.code), payload, headers


def _request_id(request: Request) -> str:
    value = getattr(getattr(request, "state", None), "request_id", "")
    value = str(value).strip()
    return value or "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, coordinator: LocalCoordinator) -> None:
        super().__init__(app)
        self._coordinator = coordinator
        self._limits: list[tuple[str, int, int]] = [
            ("/chat", 60, 60),
            ("/tokens/", 120, 60),
            ("/files", 120, 60),
        ]

    def _resolve_limit(self, path: str) -> tuple[int, int] | None:
        if not path.startswith("/api/v1/agents/"):
            return None
        for prefix, limit, window_sec in self._limits:
            if prefix == "/chat" and path.endswith(prefix):
                return limit, window_sec
            if prefix == "/files" and (path.endswith("/files") or "/files/" in path):
                return limit, window_sec
            if prefix == "/tokens/" and prefix in path:
                return limit, window_sec
        return None

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        limit_conf = self._resolve_limit(request.url.path)
        if limit_conf is not None:
            limit, window_sec = limit_conf
            client = request.client.host if request.client else "unknown"
            bucket_key = f"{client}:{request.url.path}"
            decision = self._coordinator.check_rate_limit(
                bucket_key, limit=limit, window_seconds=window_sec
            )
            if not decision.allowed:
                return JSONResponse(
                    status_code=429,
                    content=error_payload(
                        code="rate_limit_exceeded",
                        message="Rate limit exceeded. Try again later.",
                        details={"limit": limit, "window_seconds": window_sec},
                        request_id=_request_id(request),
                    ),
                    headers={"Retry-After": str(decision.retry_after_seconds)},
                )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-site")
        return response


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        incoming = request.headers.get("X-Request-Id", "").strip()
        request_id = incoming or str(uuid.uuid4())
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers.setdefault("X-Request-Id", request_id)
        return response


class AdminAuthMiddleware(BaseHTTPMiddleware):
    _EXEMPT_PATHS = {"/api/v1/health", "/api/v1/ready"}

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        path = request.url.path
        if not path.startswith("/api/v1"):
            return await call_next(request)
        if request.method.upper() == "OPTIONS" or path in self._EXEMPT_PATHS:
            return await call_next(request)

        configured = (os.getenv("APP_ADMIN_TOKEN", "") or "").strip()
        if not configured:
            return JSONResponse(
                status_code=503,
                content=error_payload(
                    code="auth_not_configured",
                    message="APP_ADMIN_TOKEN is not configured",
                    request_id=_request_id(request),
                ),
            )

        authorization = (request.headers.get("Authorization", "") or "").strip()
        token = ""
        if authorization:
            scheme, sep, token_value = authorization.partition(" ")
            if sep:
                if scheme.lower() == "bearer":
                    token = token_value.strip()
            else:
                # Local compatibility: allow raw token in Authorization header.
                token = authorization
        if not token:
            token = (request.headers.get("X-Admin-Token", "") or "").strip()
        if not token:
            token = (request.cookies.get("app_admin_token", "") or "").strip()
        if not token or not hmac.compare_digest(token, configured):
            return JSONResponse(
                status_code=401,
                content=error_payload(
                    code="unauthorized",
                    message="Missing or invalid admin token",
                    request_id=_request_id(request),
                ),
            )

        return await call_next(request)


def _parse_csv_env(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name, "")
    if not raw.strip():
        return default
    items = [item.strip() for item in raw.split(",")]
    return [item for item in items if item]


async def _proxy_to_frontend(request: Request) -> Response:
    proxy_base = _frontend_proxy_url()
    if not proxy_base:
        raise ApiError(
            status_code=503,
            code="frontend_proxy_not_configured",
            message="Frontend proxy URL is not configured",
        )

    target = f"{proxy_base}{request.url.path}"
    if request.url.query:
        target = f"{target}?{request.url.query}"

    body = await request.body()
    headers: dict[str, str] = {}
    for key, value in request.headers.items():
        normalized = key.lower()
        if normalized in _PROXY_HOP_HEADERS or normalized in {"host", "content-length"}:
            continue
        headers[key] = value

    outbound = UrlRequest(
        target,
        data=body if body else None,
        headers=headers,
        method=request.method.upper(),
    )

    try:
        status_code, payload, response_headers = await asyncio.to_thread(
            _forward_frontend_request, outbound
        )
        return Response(
            content=payload,
            status_code=status_code,
            headers=response_headers,
        )
    except URLError as exc:
        raise ApiError(
            status_code=502,
            code="frontend_proxy_unavailable",
            message=f"Frontend proxy request failed: {exc.reason}",
        ) from exc


@asynccontextmanager
async def lifespan(_: FastAPI):
    global heartbeat_scheduler, cron_scheduler
    config_api.apply_persisted_tracing_state(BASE_DIR)
    loaded = load_config(BASE_DIR)
    missing_secrets = validate_required_secrets(loaded)
    if missing_secrets:
        joined = ", ".join(missing_secrets)
        raise RuntimeError(f"Missing required secrets: {joined}")

    agent_manager.initialize(BASE_DIR)
    if agent_manager.session_manager is None or agent_manager.memory_indexer is None:
        raise RuntimeError("AgentManager dependencies not initialized")

    chat.set_agent_manager(agent_manager)
    chat.set_coordinator(local_coordinator)
    sessions.set_agent_manager(agent_manager)
    files.set_dependencies(BASE_DIR, agent_manager)
    tokens.set_dependencies(BASE_DIR, agent_manager)
    compress.set_agent_manager(agent_manager)
    config_api.set_dependencies(BASE_DIR, agent_manager)
    usage.set_agent_manager(agent_manager)
    agents.set_agent_manager(agent_manager)

    default_runtime = agent_manager.get_runtime("default")
    if agent_manager.memory_indexer is not None:
        agent_manager.memory_indexer.rebuild_index(
            settings=default_runtime.runtime_config.retrieval.memory
        )

    heartbeat_scheduler = HeartbeatScheduler(
        base_dir=default_runtime.root_dir,
        config=loaded.runtime.heartbeat,
        agent_manager=agent_manager,
        session_manager=default_runtime.session_manager,
        agent_id="default",
    )
    cron_scheduler = CronScheduler(
        base_dir=default_runtime.root_dir,
        config=loaded.runtime.cron,
        agent_manager=agent_manager,
        session_manager=default_runtime.session_manager,
        agent_id="default",
    )
    scheduler_api.set_dependencies(
        BASE_DIR,
        agent_manager,
        default_heartbeat_scheduler=heartbeat_scheduler,
        default_cron_scheduler=cron_scheduler,
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
trusted_hosts = _parse_csv_env(
    "APP_TRUSTED_HOSTS", ["localhost", "127.0.0.1", "*.localhost"]
)
allowed_origins = _parse_csv_env(
    "APP_ALLOWED_ORIGINS",
    ["http://localhost:3000", "http://127.0.0.1:3000"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=trusted_hosts)
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)
app.add_middleware(RequestIdMiddleware)
app.add_middleware(AdminAuthMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(RateLimitMiddleware, coordinator=local_coordinator)


@app.exception_handler(ApiError)
async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content=error_payload(
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=_request_id(request),
        ),
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    details = [
        {
            "field": ".".join(
                str(part) for part in err.get("loc", []) if part != "body"
            ),
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
            request_id=_request_id(request),
        ),
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=500,
        content=error_payload(
            code="internal_error",
            message="Internal server error",
            details={"exception": redact_text(str(exc))},
            request_id=_request_id(request),
        ),
    )


app.include_router(chat.router, prefix="/api/v1")
app.include_router(sessions.router, prefix="/api/v1")
app.include_router(files.router, prefix="/api/v1")
app.include_router(tokens.router, prefix="/api/v1")
app.include_router(compress.router, prefix="/api/v1")
app.include_router(config_api.router, prefix="/api/v1")
app.include_router(usage.router, prefix="/api/v1")
app.include_router(agents.router, prefix="/api/v1")
app.include_router(scheduler_api.router, prefix="/api/v1")


@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    _ = load_config(BASE_DIR)
    return {"status": "ok"}


@app.get("/api/v1/ready")
async def ready() -> dict[str, str]:
    _ = load_config(BASE_DIR)
    if agent_manager.session_manager is None:
        raise ApiError(
            status_code=503,
            code="not_ready",
            message="Agent manager is not ready",
        )
    return {"status": "ready"}


if _env_bool("APP_ENABLE_FRONTEND_PROXY", default=False):

    @app.api_route(
        "/{full_path:path}",
        methods=["GET", "HEAD", "OPTIONS", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def frontend_proxy_route(full_path: str, request: Request) -> Response:
        _ = full_path
        if request.url.path.startswith("/api/v1"):
            raise ApiError(status_code=404, code="not_found", message="Not found")
        response = await _proxy_to_frontend(request)
        configured = (os.getenv("APP_ADMIN_TOKEN", "") or "").strip()
        existing = (request.cookies.get("app_admin_token", "") or "").strip()
        if configured and (
            not existing or not hmac.compare_digest(existing, configured)
        ):
            response.set_cookie(
                key="app_admin_token",
                value=configured,
                httponly=True,
                samesite="lax",
                secure=False,
                path="/",
                max_age=60 * 60 * 12,
            )
        return response
