from fastapi import FastAPI
from .db.base import engine, Base
import logging

logger = logging.getLogger(__name__)

async def init_db():
    """
    Initialize database tables
    
    This creates all tables defined in your models.
    Think of it like creating folders in a filing cabinet.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("✅ Database tables created successfully")

async def register_saas_layer(app: FastAPI):
    """
    Register SaaS layer with FastAPI app
    
    This is the MAIN ENTRYPOINT for integrating the SaaS layer
    into your FastAPI application.
    
    Think of it like plugging in a module - one function call
    and everything is wired up.
    
    Usage in main.py:
        from app.saas_layer import register_saas_layer
        
        app = FastAPI()
        
        @app.on_event("startup")
        async def startup():
            await register_saas_layer(app)
    """
    logger.info("🚀 Registering SaaS layer...")
    
    # Step 1: Initialize database tables
    await init_db()
    
    # TODO in later steps:
    # Step 2: Register auth routes (Google OAuth, email login)
    # Step 3: Register API key routes
    # Step 4: Register subscription routes
    # Step 5: Register admin routes
    # Step 6: Register middleware (rate limiting, auth checking)
    
    logger.info("✅ SaaS layer registered successfully")