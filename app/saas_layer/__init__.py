import logging

from fastapi import FastAPI

from app.saas_layer.core.redis_client import close_redis
from app.saas_layer.db.base import Base, engine

logger = logging.getLogger(__name__)


async def register_saas_layer(app: FastAPI) -> None:
    """
    Register the entire SaaS layer with the FastAPI application.
    Called from app.on_event("startup").

    - Ensures all DB tables exist (idempotent — already created by Alembic)
    - Mounts all SaaS routers: auth, api-keys, billing, webhooks, admin
    """
    logger.info("Registering SaaS layer...")

    # Verify DB tables exist (no-op if Alembic already ran migrations).
    # Non-fatal: if DB is unreachable at startup, log a warning and continue.
    # Individual requests will still fail with a DB error until it recovers.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        logger.info("Database tables verified")
    except Exception as exc:
        logger.warning(
            "Database not reachable at startup (%s) — "
            "ensure PostgreSQL is running before making requests",
            exc.__class__.__name__,
        )

    # Import routers here (deferred) to avoid circular imports at module load time
    from app.saas_layer.auth.router import router as auth_router
    from app.saas_layer.apikeys.router import router as apikeys_router
    from app.saas_layer.billing.router import router as billing_router
    from app.saas_layer.billing.webhooks import router as webhooks_router
    from app.saas_layer.admin.router import router as admin_router

    app.include_router(auth_router)
    app.include_router(apikeys_router)
    app.include_router(billing_router)
    app.include_router(webhooks_router)
    app.include_router(admin_router)

    logger.info("SaaS layer registered — routes: auth, api-keys, billing, webhooks, admin")


async def shutdown_saas_layer() -> None:
    """Close background connections. Called from app.on_event('shutdown')."""
    await close_redis()
    logger.info("SaaS layer shut down")
