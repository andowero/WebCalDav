import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from starlette.middleware.base import RequestResponseEndpoint

from .config import settings
from .db import create_tables, init_engine, get_session_factory
from .deps import init_login_rate_limiter, init_session_store, get_session_store
from .i18n import load_catalog, resolve_language
from .metrics import http_requests_total
from .models import User, UserSettings
from .routers import (
    api_tokens,
    auth,
    caldav_accounts,
    calendars,
    events,
    journals,
    ops,
    settings as settings_router,
    tasks,
)

_PKG = Path(__file__).parent


def _static_version() -> str:
    """Hash of static assets, used to cache-bust /static includes on rebuild."""
    import hashlib

    h = hashlib.sha256()
    static_dir = _PKG / "static"
    paths = [static_dir / "app.js", static_dir / "app.css", static_dir / "sw.js"]
    paths += sorted((static_dir / "vendor").glob("*.js"))
    for p in paths:
        if p.exists():
            h.update(p.read_bytes())
    return h.hexdigest()[:12]


STATIC_VERSION = _static_version()

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        getattr(logging, settings.log_level.upper(), logging.INFO)
    ),
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.JSONRenderer(),
    ],
)

logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    init_engine(settings.database_url)
    init_session_store(settings.session_idle_timeout)
    init_login_rate_limiter(
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_window_seconds,
    )
    await create_tables()
    if settings.mcp_server_enabled:
        # The MCP app is mounted as a sub-app, so its lifespan is not run by the
        # parent; start the Streamable-HTTP session manager here instead.
        from .mcp_server import mcp

        async with mcp.session_manager.run():
            yield
    else:
        yield


app = FastAPI(title="WebCalDav", lifespan=lifespan)

templates = Jinja2Templates(directory=str(_PKG / "templates"))
app.mount("/static", StaticFiles(directory=str(_PKG / "static")), name="static")

app.include_router(auth.router)
app.include_router(caldav_accounts.router)
app.include_router(calendars.router)
app.include_router(events.router)
app.include_router(tasks.router)
app.include_router(journals.router)
app.include_router(settings_router.router)
app.include_router(api_tokens.router)
app.include_router(ops.router)


_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def csrf_header_check(request: Request, call_next: RequestResponseEndpoint) -> Response:
    # CSRF defense-in-depth on top of SameSite=Lax: cross-site HTML forms
    # cannot set custom headers, so requiring one blocks forged requests. The
    # MCP endpoint uses bearer-token auth (no ambient cookie), so it is not
    # subject to CSRF and its clients don't send the header — exempt it.
    if (
        request.method in _MUTATING_METHODS
        and not request.url.path.startswith("/mcp")
        and request.headers.get("x-requested-with") != "fetch"
    ):
        return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    route = request.url.path
    http_requests_total.labels(route=route, method=request.method, status=str(response.status_code)).inc()
    return response


@app.get("/", response_class=HTMLResponse)
async def root(request: Request) -> HTMLResponse:
    session_id = request.cookies.get("session_id")
    state = "anonymous"
    user_email = None
    user_settings_tz = "UTC"
    user_settings_fdow = 1
    user_settings_timefmt = "24h"
    user_settings_datefmt = "YYYY-MM-DD"
    user_settings_default_view = "dayGridMonth"
    user_settings_auto_logout_enabled = True
    user_settings_auto_logout_timeout = 3600
    user_settings_notifications_enabled = False
    user_settings_completed_task_display = "hidden"
    user_settings_undated_task_display = "agenda"
    user_settings_theme = "system"
    user_settings_language = "autodetect"
    user_settings_double_click_to_create_events = False

    if session_id:
        try:
            store = get_session_store()
            entry = store.get(session_id)
            if entry:
                state = "restricted" if entry.restricted else "authenticated"
                async with get_session_factory()() as db:
                    user = (
                        await db.execute(select(User).where(User.id == entry.user_id))
                    ).scalar_one_or_none()
                    if user:
                        user_email = user.email
                    s = (
                        await db.execute(
                            select(UserSettings).where(UserSettings.user_id == entry.user_id)
                        )
                    ).scalar_one_or_none()
                    if s:
                        user_settings_tz = s.timezone
                        user_settings_fdow = s.first_day_of_week
                        user_settings_timefmt = s.time_format
                        user_settings_datefmt = s.date_format
                        user_settings_default_view = s.default_view
                        user_settings_auto_logout_enabled = s.auto_logout_enabled
                        user_settings_auto_logout_timeout = s.auto_logout_timeout_seconds
                        user_settings_notifications_enabled = s.notifications_enabled
                        user_settings_completed_task_display = s.completed_task_display
                        user_settings_undated_task_display = s.undated_task_display
                        user_settings_theme = s.theme
                        user_settings_language = s.language
                        user_settings_double_click_to_create_events = (
                            s.double_click_to_create_events
                        )
        except Exception:
            logger.warning("root_session_lookup_failed", exc_info=True)

    lang = resolve_language(
        user_settings_language, request.headers.get("accept-language")
    )
    catalog = load_catalog(lang)

    return templates.TemplateResponse(
        request,
        "index.html",
        context={
            "state": state,
            "user_email": user_email,
            "tz": user_settings_tz,
            "fdow": user_settings_fdow,
            "timefmt": user_settings_timefmt,
            "datefmt": user_settings_datefmt,
            "default_view": user_settings_default_view,
            "auto_logout_enabled": user_settings_auto_logout_enabled,
            "auto_logout_timeout": user_settings_auto_logout_timeout,
            "notifications_enabled": user_settings_notifications_enabled,
            "completed_task_display": user_settings_completed_task_display,
            "undated_task_display": user_settings_undated_task_display,
            "theme": user_settings_theme,
            "language": user_settings_language,
            "double_click_to_create_events": user_settings_double_click_to_create_events,
            "mcp_enabled": settings.mcp_server_enabled,
            "lang": lang,
            "i18n": catalog,
            "notification_horizon_days": settings.notification_horizon_days,
            "notification_lookback_days": settings.notification_lookback_days,
            "static_v": STATIC_VERSION,
        },
    )


if settings.mcp_server_enabled:
    from starlette.routing import Mount

    from .mcp_server import build_mcp_app

    # Mounted at the root (not "/mcp") so the inner app's own "/mcp" route is
    # reached with the path unstripped — avoids the trailing-slash 307 redirect
    # that "/mcp" -> "/mcp/" would otherwise cause. Appended LAST (after every
    # router, the /static mount, and the "/" route are registered) so it is a
    # pure fallback: real routes match first, only /mcp falls through to it.
    app.router.routes.append(Mount("/", app=build_mcp_app()))
