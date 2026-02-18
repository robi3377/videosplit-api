from dotenv import load_dotenv

# Load .env FIRST — before any module that reads os.getenv at import time
load_dotenv()

import asyncio
import logging
import shutil
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from sqlalchemy import text as _sa_text

from app.routes import video
from app.saas_layer import register_saas_layer, shutdown_saas_layer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

logger = logging.getLogger(__name__)

# Ensure required directories exist
Path("uploads").mkdir(exist_ok=True)
Path("outputs").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)
Path("static/errors").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB + SaaS routers + background tasks. Shutdown: close connections."""
    await register_saas_layer(app)

    # Start background cleanup loop (deletes job files older than 24h)
    from app.services.cleanup_service import run_cleanup_loop
    cleanup_task = asyncio.create_task(run_cleanup_loop(interval_seconds=3600))

    yield

    cleanup_task.cancel()
    try:
        await cleanup_task
    except asyncio.CancelledError:
        pass

    await shutdown_saas_layer()


# ---------------------------------------------------------------------------
# FastAPI application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="VideoSplit SaaS API",
    description="Split videos into segments — with authentication, plans, and billing",
    version="2.0.0",
    lifespan=lifespan,
    docs_url=None,      # Custom docs page in /static/documentation.html
    redoc_url=None,
    openapi_url=None,
)

from app.saas_layer.core.config import settings as _settings

# CORS — restrict to the configured base URL; allow localhost for local dev
_cors_origins = [_settings.APP_BASE_URL]
if "localhost" not in _settings.APP_BASE_URL and "127.0.0.1" not in _settings.APP_BASE_URL:
    _cors_origins += ["http://localhost:8000", "http://127.0.0.1:8000"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

# Static frontend
app.mount("/static", StaticFiles(directory="static"), name="static")

# Video processing API (now auth-protected via dependencies in video.py)
app.include_router(video.router, prefix="/api/v1", tags=["video"])


# ---------------------------------------------------------------------------
# Utility routes (unchanged)
# ---------------------------------------------------------------------------

@app.get("/")
async def root():
    """Redirect to the frontend."""
    return RedirectResponse(url="/static/index.html")


@app.get("/documentation")
async def documentation():
    """Custom API documentation page."""
    return RedirectResponse(url="/static/documentation.html")


@app.get("/api")
async def api_info():
    """API information and endpoint overview."""
    return {
        "message": "VideoSplit SaaS API",
        "version": "2.0.0",
        "status": "running",
        "documentation": "/documentation",
        "frontend": "/static/index.html",
        "endpoints": {
            "split_video": "POST /api/v1/split  (auth required)",
            "download_segment": "GET /api/v1/download/{job_id}/{filename}",
            "download_all": "GET /api/v1/download-all/{job_id}",
            "get_job_info": "GET /api/v1/job/{job_id}",
            "delete_job": "DELETE /api/v1/job/{job_id}",
            "register": "POST /auth/register",
            "login": "POST /auth/login",
            "profile": "GET /auth/me",
            "api_keys": "GET /api-keys",
            "billing_status": "GET /billing/status",
            "admin_metrics": "GET /admin/metrics",
        },
    }


@app.get("/health")
async def health():
    """Enhanced health check — checks DB, Redis, and disk."""
    from app.saas_layer.core.redis_client import get_redis
    from app.saas_layer.db.base import engine

    now = datetime.now(timezone.utc)

    # DB
    db_status = "connected"
    try:
        async with engine.connect() as conn:
            await conn.execute(_sa_text("SELECT 1"))
    except Exception as exc:
        db_status = f"error: {exc.__class__.__name__}"

    # Redis
    redis_status = "disconnected"
    try:
        redis = await get_redis()
        if redis:
            await redis.ping()
            redis_status = "connected"
    except Exception:
        pass

    # Disk
    disk = shutil.disk_usage(".")
    disk_free_pct = round((disk.free / disk.total) * 100, 1)

    overall = "healthy" if db_status == "connected" and disk_free_pct > 5 else "degraded"

    return {
        "status": overall,
        "timestamp": now.isoformat(),
        "database": db_status,
        "redis": redis_status,
        "disk_free_pct": disk_free_pct,
        "api": "operational",
    }


# ---------------------------------------------------------------------------
# Custom exception handlers (serve JSON for API, error page for browser)
# ---------------------------------------------------------------------------

def _wants_html(request: Request) -> bool:
    accept = request.headers.get("accept", "")
    return "text/html" in accept and "application/json" not in accept


def _error_page_response(code: int):
    from fastapi.responses import FileResponse
    page = Path(f"static/errors/{code}.html")
    if page.exists():
        return FileResponse(page, status_code=code)
    return JSONResponse({"detail": f"HTTP {code}"}, status_code=code)


@app.exception_handler(401)
async def handler_401(request: Request, exc):
    if _wants_html(request):
        return _error_page_response(401)
    return JSONResponse({"detail": getattr(exc, "detail", "Unauthorized")}, status_code=401)


@app.exception_handler(402)
async def handler_402(request: Request, exc):
    if _wants_html(request):
        return _error_page_response(402)
    return JSONResponse({"detail": getattr(exc, "detail", "Payment Required")}, status_code=402)


@app.exception_handler(404)
async def handler_404(request: Request, exc):
    if _wants_html(request):
        return _error_page_response(404)
    return JSONResponse({"detail": getattr(exc, "detail", "Not Found")}, status_code=404)


@app.exception_handler(429)
async def handler_429(request: Request, exc):
    if _wants_html(request):
        return _error_page_response(429)
    return JSONResponse({"detail": getattr(exc, "detail", "Too Many Requests")}, status_code=429)


@app.exception_handler(500)
async def handler_500(request: Request, exc):
    logger.error("Unhandled 500 on %s: %s", request.url, exc)
    if _wants_html(request):
        return _error_page_response(500)
    return JSONResponse({"detail": "Internal server error"}, status_code=500)
