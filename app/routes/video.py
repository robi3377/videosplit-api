from datetime import datetime, timedelta, timezone
import re
import time

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.auth.dependencies import get_current_active_user
from app.saas_layer.db.base import get_db
from app.saas_layer.db.models import Job, User
from app.saas_layer.middleware.rate_limit import check_split_rate_limit
from app.saas_layer.usage.service import check_usage_limit, record_usage
from app.services.ffmpeg_service import FFmpegService
from app.models.schemas import SplitResponse, SegmentInfo, ErrorResponse
from pathlib import Path
import uuid
import shutil
import subprocess
import zipfile
import io

JOB_EXPIRY_HOURS = 24

# Create router
router = APIRouter()

# Directories
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")

# Ensure directories exist
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)


@router.post("/split", response_model=SplitResponse)
async def split_video(
    request: Request,
    file: UploadFile = File(...),
    segment_duration: int = Query(default=60, ge=1, le=3600),
    aspect_ratio: str = Form(default=None),
    crop_position: str = Form(default="center"),
    custom_width: int = Form(default=None),
    custom_height: int = Form(default=None),
    current_user: User = Depends(check_split_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """
    Split a video into equal-length segments.
    Requires authentication (JWT Bearer token or API key).

    **Parameters:**
    - **file**: Video file to upload (mp4, mov, avi, etc.)
    - **segment_duration**: Duration of each segment in seconds (default: 60, min: 1, max: 3600)

    **Returns:**
    - Job ID
    - List of segments with download URLs
    - Original video info

    **Example:**
```
    POST /api/v1/split?segment_duration=30
    Authorization: Bearer <token>
```
    """

    # Step 1: Validate file extension (MIME type is unreliable — let FFmpeg do real validation)
    ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: mp4, mov, avi, mkv"
        )

    # Validate crop params
    VALID_ASPECT_RATIOS = {"16:9", "4:3", "1:1", "9:16", "21:9", "custom"}
    VALID_POSITIONS = {"center", "top", "bottom", "left", "right"}
    if aspect_ratio and aspect_ratio not in VALID_ASPECT_RATIOS:
        raise HTTPException(status_code=400, detail=f"Invalid aspect_ratio '{aspect_ratio}'")
    if crop_position not in VALID_POSITIONS:
        raise HTTPException(status_code=400, detail=f"Invalid crop_position '{crop_position}'")
    if aspect_ratio == "custom" and (not custom_width or not custom_height):
        raise HTTPException(status_code=400, detail="Custom aspect ratio requires width and height")

    # Step 2: Generate unique job ID
    job_id = str(uuid.uuid4())

    # Step 3: Save uploaded file
    input_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
    try:
        with open(input_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save uploaded file: {str(e)}"
        )

    file_size_mb = len(content) / (1024 * 1024)

    # Step 4: Create output directory for this job
    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(exist_ok=True)

    try:
        # Step 5: Get original video duration
        total_duration = FFmpegService.get_duration(str(input_path))

        # Step 5b: Enforce monthly plan usage limit (raises 402 if exceeded)
        await check_usage_limit(current_user, total_duration, db)

        # Step 6: Split the video (track time for usage log)
        processing_start = time.time()
        segments = FFmpegService.split_video(
            str(input_path),
            job_output_dir,
            segment_duration,
            aspect_ratio=aspect_ratio,
            crop_position=crop_position,
            custom_width=custom_width,
            custom_height=custom_height,
        )
        processing_time = time.time() - processing_start

        # Step 7: Prepare segment information
        segment_infos = []
        for seg in segments:
            segment_infos.append(SegmentInfo(
                filename=seg.name,
                duration=FFmpegService.get_duration(str(seg)),
                size_bytes=seg.stat().st_size,
                download_url=f"/api/v1/download/{job_id}/{seg.name}"
            ))

        # Step 8: Clean up input file (save space)
        input_path.unlink()

        # Step 9: Persist Job record in the database
        auth_header = request.headers.get("authorization", "")
        source = "api" if auth_header.startswith("vs_live_") else "web"

        now = datetime.now(timezone.utc)
        db_job = Job(
            job_id=job_id,
            user_id=current_user.id,
            original_filename=file.filename,
            segment_duration=segment_duration,
            segments_count=len(segments),
            total_duration=total_duration,
            aspect_ratio=aspect_ratio if aspect_ratio and aspect_ratio != "custom" else (f"{custom_width}x{custom_height}" if custom_width and custom_height else None),
            crop_position=crop_position if aspect_ratio else None,
            status="completed",
            completed_at=now,
            expires_at=now + timedelta(hours=JOB_EXPIRY_HOURS),
        )
        db.add(db_job)

        # Step 10: Record usage (updates monthly_minutes_used + creates UsageLog)
        await record_usage(
            user=current_user,
            job_id=job_id,
            video_duration_seconds=total_duration,
            video_size_mb=file_size_mb,
            segments_count=len(segments),
            processing_time_seconds=processing_time,
            source=source,
            api_key_id=None,
            db=db,
        )

        # Step 11: Return response
        return SplitResponse(
            job_id=job_id,
            status="completed",
            segments_count=len(segments),
            segments=segment_infos,
            original_filename=file.filename,
            total_duration=total_duration
        )

    except HTTPException:
        # Pass through HTTPExceptions (402 plan limit, 429 rate limit, etc.)
        input_path.unlink(missing_ok=True)
        shutil.rmtree(job_output_dir, ignore_errors=True)
        raise

    except subprocess.CalledProcessError as e:
        # Clean up on FFmpeg error
        input_path.unlink(missing_ok=True)
        shutil.rmtree(job_output_dir, ignore_errors=True)

        raise HTTPException(
            status_code=500,
            detail=f"Video processing failed. Error: {e.stderr if hasattr(e, 'stderr') else str(e)}"
        )

    except Exception as e:
        # Clean up on any other error
        input_path.unlink(missing_ok=True)
        shutil.rmtree(job_output_dir, ignore_errors=True)

        raise HTTPException(
            status_code=500,
            detail=f"Unexpected error: {str(e)}"
        )


_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_SEGMENT_FILE_RE = re.compile(r'^segment_\d+\.mp4$')


def _validate_job_id(job_id: str) -> None:
    """Raises 400 if job_id is not a valid UUID (prevents path traversal)."""
    if not _UUID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")


def _validate_filename(filename: str) -> None:
    """Raises 400 if filename is not a safe segment filename (prevents path traversal)."""
    if not _SEGMENT_FILE_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename format")


@router.get("/download/{job_id}/{filename}")
async def download_segment(job_id: str, filename: str):
    """
    Download a specific video segment

    **Parameters:**
    - **job_id**: The job ID returned from /split
    - **filename**: Name of the segment file (e.g., segment_000.mp4)

    **Returns:**
    - The video file

    **Example:**
```
    GET /api/v1/download/abc-123-def/segment_000.mp4
```
    """
    _validate_job_id(job_id)
    _validate_filename(filename)

    file_path = OUTPUT_DIR / job_id / filename

    # Check if file exists
    if not file_path.exists():
        raise HTTPException(
            status_code=404,
            detail=f"File not found. Job ID or filename may be incorrect."
        )
    
    # Return the file
    return FileResponse(
        path=file_path,
        media_type="video/mp4",
        filename=filename
    )


@router.get("/download-all/{job_id}")
async def download_all_segments(job_id: str):
    """
    Download all segments as a ZIP file (fast - no compression)
    
    **Parameters:**
    - **job_id**: The job ID
    
    **Returns:**
    - ZIP file containing all segments (uncompressed for speed)
    
    **Example:**
```
    GET /api/v1/download-all/abc-123-def
```
    
    **Note:** Uses ZIP_STORED (no compression) for 10x faster downloads.
    Video files are already compressed, so this doesn't increase size significantly.
    """
    _validate_job_id(job_id)
    job_dir = OUTPUT_DIR / job_id
    
    # Check if job exists
    if not job_dir.exists():
        raise HTTPException(
            status_code=404,
            detail="Job not found"
        )
    
    # Get all segments
    segments = sorted(job_dir.glob("segment_*.mp4"))
    
    if not segments:
        raise HTTPException(
            status_code=404,
            detail="No segments found for this job"
        )
    
    # Create ZIP file in memory WITHOUT compression (faster!)
    zip_buffer = io.BytesIO()
    
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_STORED) as zip_file:
        for segment in segments:
            # Add each segment to ZIP with its filename
            zip_file.write(segment, segment.name)
    
    # Prepare ZIP for download
    zip_buffer.seek(0)
    
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f"attachment; filename=segments_{job_id}.zip"
        }
    )


@router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """
    Delete a job and all its segments
    
    **Parameters:**
    - **job_id**: The job ID to delete
    
    **Returns:**
    - Success message
    
    **Example:**
```
    DELETE /api/v1/job/abc-123-def
```
    
    **Note:** This permanently deletes all video segments for this job.
    """
    _validate_job_id(job_id)
    job_dir = OUTPUT_DIR / job_id

    # Check if job exists
    if not job_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Job not found. Job ID may be incorrect or already deleted."
        )
    
    # Delete the directory and all files
    try:
        shutil.rmtree(job_dir)
        return {
            "message": "Job deleted successfully",
            "job_id": job_id
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete job: {str(e)}"
        )


@router.get("/jobs/recent")
async def get_recent_jobs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
    status_filter: str = Query(default=None, alias="status"),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=10, ge=1, le=50),
):
    """Return the authenticated user's recent jobs with pagination and optional status filter."""
    from sqlalchemy import func as sqlfunc

    query = select(Job).where(Job.user_id == current_user.id)
    if status_filter and status_filter in ("completed", "failed", "expired", "processing"):
        query = query.where(Job.status == status_filter)

    count_result = await db.execute(select(sqlfunc.count()).select_from(query.subquery()))
    total = count_result.scalar_one()

    offset = (page - 1) * per_page
    query = query.order_by(Job.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    jobs = result.scalars().all()

    now = datetime.now(timezone.utc)
    job_list = []
    for j in jobs:
        expires_at = j.expires_at
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        hours_left = None
        if expires_at and j.status == "completed":
            delta = expires_at - now
            hours_left = max(0, int(delta.total_seconds() / 3600))

        job_list.append({
            "id": j.id,
            "job_id": j.job_id,
            "original_filename": j.original_filename,
            "status": j.status,
            "total_duration": j.total_duration,
            "total_duration_minutes": round(j.total_duration / 60, 2),
            "segments_count": j.segments_count,
            "segment_duration": j.segment_duration,
            "aspect_ratio": j.aspect_ratio,
            "crop_position": j.crop_position,
            "created_at": j.created_at.isoformat() if j.created_at else None,
            "completed_at": j.completed_at.isoformat() if j.completed_at else None,
            "expires_at": expires_at.isoformat() if expires_at else None,
            "hours_until_expiry": hours_left,
            "error_message": j.error_message,
            "download_all_url": f"/api/v1/download-all/{j.job_id}" if j.status == "completed" else None,
        })

    return {"total": total, "page": page, "per_page": per_page, "jobs": job_list}


@router.get("/job/{job_id}")
async def get_job_info(job_id: str):
    """
    Get information about a job
    
    **Parameters:**
    - **job_id**: The job ID to check
    
    **Returns:**
    - Job status and segment list
    
    **Example:**
```
    GET /api/v1/job/abc-123-def
```
    """
    _validate_job_id(job_id)
    job_dir = OUTPUT_DIR / job_id

    # Check if job exists
    if not job_dir.exists():
        raise HTTPException(
            status_code=404,
            detail="Job not found. Job ID may be incorrect."
        )
    
    # Get all segments
    segments = sorted(job_dir.glob("segment_*.mp4"))
    
    # Build segment info
    segment_infos = []
    for seg in segments:
        segment_infos.append({
            "filename": seg.name,
            "size_bytes": seg.stat().st_size,
            "download_url": f"/api/v1/download/{job_id}/{seg.name}"
        })
    
    return {
        "job_id": job_id,
        "status": "completed",
        "segments_count": len(segments),
        "segments": segment_infos
    }