import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from .config import settings
from .db import create_tables, init_engine, get_session_factory
from .deps import init_login_rate_limiter, init_session_store, get_session_store
from .metrics import active_sessions, http_requests_total
from .models import User, UserSettings
from .routers import auth, caldav_accounts, calendars, events, ops, settings as settings_router

_PKG = Path(__file__).parent


def _static_version() -> str:
    """Hash of static assets, used to cache-bust /static includes on rebuild."""
    import hashlib

    h = hashlib.sha256()
    static_dir = _PKG / "static"
    paths = [static_dir / "app.js", static_dir / "app.css"]
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
async def lifespan(app: FastAPI):
    init_engine(settings.database_url)
    init_session_store(settings.session_idle_timeout)
    init_login_rate_limiter(
        settings.login_rate_limit_attempts,
        settings.login_rate_limit_window_seconds,
    )
    await create_tables()
    yield


app = FastAPI(title="WebCalDav", lifespan=lifespan)

templates = Jinja2Templates(directory=str(_PKG / "templates"))
app.mount("/static", StaticFiles(directory=str(_PKG / "static")), name="static")

app.include_router(auth.router)
app.include_router(caldav_accounts.router)
app.include_router(calendars.router)
app.include_router(events.router)
app.include_router(settings_router.router)
app.include_router(ops.router)


_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@app.middleware("http")
async def csrf_header_check(request: Request, call_next):
    # CSRF defense-in-depth on top of SameSite=Lax: cross-site HTML forms
    # cannot set custom headers, so requiring one blocks forged requests.
    if (
        request.method in _MUTATING_METHODS
        and request.headers.get("x-requested-with") != "fetch"
    ):
        return JSONResponse({"detail": "Missing CSRF header"}, status_code=403)
    return await call_next(request)


@app.middleware("http")
async def metrics_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    duration = time.perf_counter() - start
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
        except Exception:
            logger.warning("root_session_lookup_failed", exc_info=True)

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
            "static_v": STATIC_VERSION,
        },
    )
