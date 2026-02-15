from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
from app.routes import video

# Create necessary directories
Path("uploads").mkdir(exist_ok=True)
Path("outputs").mkdir(exist_ok=True)

# Create the FastAPI application
app = FastAPI(
    title="Video Batch Cutter API",
    description="API for splitting videos into equal-length segments",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# Add CORS middleware (allows requests from browsers)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include the video router
app.include_router(
    video.router,
    prefix="/api/v1",
    tags=["video"]
)

@app.get("/")
async def root():
    """Root endpoint - API information"""
    return {
        "message": "Video Batch Cutter API",
        "version": "1.0.0",
        "status": "running",
        "docs": "/docs",
        "endpoints": {
            "split_video": "POST /api/v1/split",
            "download_segment": "GET /api/v1/download/{job_id}/{filename}",
            "get_job_info": "GET /api/v1/job/{job_id}",
            "delete_job": "DELETE /api/v1/job/{job_id}"
        }
    }

@app.get("/health")
async def health():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "api": "operational"
    }