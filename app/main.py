from dotenv import load_dotenv

# Load .env FIRST — before any module that reads os.getenv at import time
load_dotenv()

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.routes import video
from app.saas_layer import register_saas_layer, shutdown_saas_layer

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)

# Ensure required directories exist
Path("uploads").mkdir(exist_ok=True)
Path("outputs").mkdir(exist_ok=True)
Path("static").mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Lifespan (replaces deprecated on_event)
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialise DB + SaaS routers. Shutdown: close connections."""
    await register_saas_layer(app)
    yield
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

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # Tighten to your domain in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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
    """Health check endpoint."""
    return {"status": "healthy", "api": "operational"}
