from datetime import datetime, timedelta, timezone
import re
import tempfile
import time
from typing import Optional

from fastapi import APIRouter, Depends, Form, Request, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.auth.dependencies import get_current_active_user
from app.saas_layer.core.config import settings
from app.saas_layer.db.base import get_db
from app.saas_layer.db.models import Job, User
from app.saas_layer.middleware.rate_limit import check_split_rate_limit
from app.saas_layer.usage.service import check_usage_limit, record_usage
from app.services.ffmpeg_service import FFmpegService
from app.services import r2_service
from app.models.schemas import SplitResponse, SegmentInfo
from pathlib import Path
import uuid
import shutil
import subprocess
import zipfile
import io

JOB_EXPIRY_HOURS = 1  # Files deleted from R2 after 1 hour

# Create router
router = APIRouter()

# Directories (kept for local fallback — old jobs and non-R2 deployments)
UPLOAD_DIR = Path("uploads")
OUTPUT_DIR = Path("outputs")

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

    # Step 1: Validate file extension
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

    # Step 3: Save uploaded file locally (needed by FFmpeg)
    input_path = UPLOAD_DIR / f"{job_id}_{file.filename}"
    try:
        with open(input_path, "wb") as f:
            content = await file.read()
            f.write(content)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save uploaded file: {str(e)}")

    file_size_mb = len(content) / (1024 * 1024)

    # Step 4: Create local output directory for FFmpeg
    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(exist_ok=True)

    try:
        # Step 5: Get video duration
        total_duration = FFmpegService.get_duration(str(input_path))

        # Step 5b: Enforce monthly plan limit
        await check_usage_limit(current_user, total_duration, db)

        # Step 6: Split the video
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

        # Step 7: Upload segments to R2 (if configured), then build response
        segment_infos = []
        for seg in segments:
            duration = FFmpegService.get_duration(str(seg))
            size_bytes = seg.stat().st_size

            if settings.r2_enabled:
                r2_key = f"jobs/{job_id}/{seg.name}"
                await r2_service.upload_file(str(seg), r2_key)
                seg.unlink()  # Remove local copy after R2 upload

            segment_infos.append(SegmentInfo(
                filename=seg.name,
                duration=duration,
                size_bytes=size_bytes,
                download_url=f"/api/v1/download/{job_id}/{seg.name}",
            ))

        # Remove empty local output dir when using R2
        if settings.r2_enabled:
            try:
                job_output_dir.rmdir()
            except OSError:
                pass

        # Step 8: Clean up uploaded input file
        input_path.unlink(missing_ok=True)

        # Step 9: Persist Job record
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
            aspect_ratio=aspect_ratio if aspect_ratio and aspect_ratio != "custom" else (
                f"{custom_width}x{custom_height}" if custom_width and custom_height else None
            ),
            crop_position=crop_position if aspect_ratio else None,
            status="completed",
            completed_at=now,
            expires_at=now + timedelta(hours=JOB_EXPIRY_HOURS),
        )
        db.add(db_job)

        # Step 10: Record usage
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

        return SplitResponse(
            job_id=job_id,
            status="completed",
            segments_count=len(segments),
            segments=segment_infos,
            original_filename=file.filename,
            total_duration=total_duration,
        )

    except HTTPException:
        input_path.unlink(missing_ok=True)
        shutil.rmtree(job_output_dir, ignore_errors=True)
        raise

    except subprocess.CalledProcessError as e:
        input_path.unlink(missing_ok=True)
        shutil.rmtree(job_output_dir, ignore_errors=True)
        raise HTTPException(
            status_code=500,
            detail=f"Video processing failed. Error: {e.stderr if hasattr(e, 'stderr') else str(e)}"
        )

    except Exception as e:
        input_path.unlink(missing_ok=True)
        shutil.rmtree(job_output_dir, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")


_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')
_SEGMENT_FILE_RE = re.compile(r'^segment_\d+\.mp4$')


def _validate_job_id(job_id: str) -> None:
    """Raises 400 if job_id is not a valid UUID."""
    if not _UUID_RE.match(job_id):
        raise HTTPException(status_code=400, detail="Invalid job ID format")


def _validate_filename(filename: str) -> None:
    """Raises 400 if filename is not a safe segment filename."""
    if not _SEGMENT_FILE_RE.match(filename):
        raise HTTPException(status_code=400, detail="Invalid filename format")


@router.get("/download/{job_id}/{filename}")
async def download_segment(job_id: str, filename: str):
    """
    Download a specific video segment.
    Redirects to a presigned R2 URL when available; falls back to local file.
    """
    _validate_job_id(job_id)
    _validate_filename(filename)

    # Try R2 first (new jobs)
    if settings.r2_enabled:
        r2_key = f"jobs/{job_id}/{filename}"
        if await r2_service.object_exists(r2_key):
            url = await r2_service.generate_presigned_url(r2_key, expires_in=3600)
            return RedirectResponse(url=url, status_code=302)

    # Fall back to local filesystem (old jobs / R2 not configured)
    file_path = OUTPUT_DIR / job_id / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found. It may have expired.")

    return FileResponse(path=file_path, media_type="video/mp4", filename=filename)


@router.get("/download-all/{job_id}")
async def download_all_segments(job_id: str):
    """
    Download all segments as a ZIP file (uncompressed for speed).
    Streams segments from R2 when available; falls back to local files.
    """
    _validate_job_id(job_id)

    zip_buffer = io.BytesIO()

    # Try R2 first (new jobs)
    if settings.r2_enabled:
        prefix = f"jobs/{job_id}/"
        keys = await r2_service.list_keys(prefix)
        segment_keys = sorted([k for k in keys if _SEGMENT_FILE_RE.match(k.split("/")[-1])])

        if segment_keys:
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
                for key in segment_keys:
                    data = await r2_service.download_to_memory(key)
                    zf.writestr(key.split("/")[-1], data)
            zip_buffer.seek(0)
            return Response(
                content=zip_buffer.getvalue(),
                media_type="application/zip",
                headers={"Content-Disposition": f"attachment; filename=segments_{job_id}.zip"},
            )

    # Fall back to local filesystem (old jobs / R2 not configured)
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found or already expired.")

    segments = sorted(job_dir.glob("segment_*.mp4"))
    if not segments:
        raise HTTPException(status_code=404, detail="No segments found for this job.")

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_STORED) as zf:
        for segment in segments:
            zf.write(segment, segment.name)

    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=segments_{job_id}.zip"},
    )


@router.delete("/job/{job_id}")
async def delete_job(job_id: str):
    """Delete a job and all its segments (R2 + local)."""
    _validate_job_id(job_id)

    deleted = False

    # Delete from R2 if configured
    if settings.r2_enabled:
        count = await r2_service.delete_prefix(f"jobs/{job_id}/")
        if count > 0:
            deleted = True

    # Delete from local filesystem (old jobs / fallback)
    job_dir = OUTPUT_DIR / job_id
    if job_dir.exists():
        shutil.rmtree(job_dir)
        deleted = True

    if not deleted:
        raise HTTPException(status_code=404, detail="Job not found or already deleted.")

    return {"message": "Job deleted successfully", "job_id": job_id}


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
    """Get information about a job and its segments."""
    _validate_job_id(job_id)

    # Try R2 first
    if settings.r2_enabled:
        prefix = f"jobs/{job_id}/"
        keys = await r2_service.list_keys(prefix)
        segment_keys = sorted([k for k in keys if _SEGMENT_FILE_RE.match(k.split("/")[-1])])
        if segment_keys:
            return {
                "job_id": job_id,
                "status": "completed",
                "segments_count": len(segment_keys),
                "segments": [
                    {"filename": k.split("/")[-1], "download_url": f"/api/v1/download/{job_id}/{k.split('/')[-1]}"}
                    for k in segment_keys
                ],
            }

    # Fall back to local
    job_dir = OUTPUT_DIR / job_id
    if not job_dir.exists():
        raise HTTPException(status_code=404, detail="Job not found.")

    segments = sorted(job_dir.glob("segment_*.mp4"))
    return {
        "job_id": job_id,
        "status": "completed",
        "segments_count": len(segments),
        "segments": [
            {"filename": seg.name, "size_bytes": seg.stat().st_size, "download_url": f"/api/v1/download/{job_id}/{seg.name}"}
            for seg in segments
        ],
    }


# ---------------------------------------------------------------------------
# Direct-to-R2 Upload (bypasses Cloudflare 100 MB proxy limit)
# ---------------------------------------------------------------------------

class InitUploadRequest(BaseModel):
    filename: str = Field(..., description="Original filename including extension")


class InitUploadResponse(BaseModel):
    job_id: str
    upload_url: str  # Presigned PUT URL — browser sends file directly here
    r2_key: str      # Key where the file will live in R2


class ProcessUploadRequest(BaseModel):
    job_id: str
    segment_duration: int = Field(default=60, ge=1, le=3600)
    aspect_ratio: Optional[str] = None
    crop_position: str = "center"
    custom_width: Optional[int] = None
    custom_height: Optional[int] = None


@router.post("/upload/init", response_model=InitUploadResponse)
async def init_upload(
    body: InitUploadRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 1 of the direct-upload flow.
    Returns a presigned R2 PUT URL so the browser can upload directly to R2,
    bypassing Cloudflare and our server (no 100 MB proxy limit).

    After the browser finishes uploading, call /upload/process with the job_id.
    """
    if not settings.r2_enabled:
        raise HTTPException(
            status_code=503,
            detail="Direct upload requires R2 storage to be configured",
        )

    ALLOWED_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv"}
    suffix = Path(body.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: mp4, mov, avi, mkv",
        )

    job_id = str(uuid.uuid4())
    r2_key = f"uploads/{job_id}/original{suffix}"

    # Generate 1-hour presigned PUT URL
    upload_url = await r2_service.generate_presigned_put_url(r2_key, expires_in=3600)

    # Create a minimal job record so the process endpoint can verify ownership
    now = datetime.now(timezone.utc)
    db_job = Job(
        job_id=job_id,
        user_id=current_user.id,
        original_filename=body.filename,
        segment_duration=0,   # filled in by /upload/process
        segments_count=0,     # filled in by /upload/process
        total_duration=0.0,   # filled in by /upload/process
        status="uploading",
        expires_at=now + timedelta(hours=1),  # upload window
    )
    db.add(db_job)
    await db.commit()

    return InitUploadResponse(job_id=job_id, upload_url=upload_url, r2_key=r2_key)


@router.post("/upload/process", response_model=SplitResponse)
async def process_uploaded_video(
    body: ProcessUploadRequest,
    request: Request,
    current_user: User = Depends(check_split_rate_limit),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2 of the direct-upload flow.
    Downloads the file from R2, splits it with FFmpeg, uploads segments back to R2,
    and returns segment download URLs.
    The video file never passes through our server — only FFmpeg processing does.
    """
    if not settings.r2_enabled:
        raise HTTPException(status_code=503, detail="R2 storage not configured")

    # Validate crop params
    VALID_ASPECT_RATIOS = {"16:9", "4:3", "1:1", "9:16", "21:9", "custom"}
    VALID_POSITIONS = {"center", "top", "bottom", "left", "right"}
    if body.aspect_ratio and body.aspect_ratio not in VALID_ASPECT_RATIOS:
        raise HTTPException(status_code=400, detail=f"Invalid aspect_ratio '{body.aspect_ratio}'")
    if body.crop_position not in VALID_POSITIONS:
        raise HTTPException(status_code=400, detail=f"Invalid crop_position '{body.crop_position}'")
    if body.aspect_ratio == "custom" and (not body.custom_width or not body.custom_height):
        raise HTTPException(status_code=400, detail="Custom aspect ratio requires width and height")

    # Verify job ownership and status
    result = await db.execute(
        select(Job).where(Job.job_id == body.job_id, Job.user_id == current_user.id)
    )
    db_job = result.scalar_one_or_none()
    if not db_job:
        raise HTTPException(status_code=404, detail="Job not found or access denied")
    if db_job.status != "uploading":
        raise HTTPException(status_code=409, detail="Job has already been processed")

    # Locate the uploaded file in R2
    suffix = Path(db_job.original_filename).suffix.lower()
    r2_input_key = f"uploads/{body.job_id}/original{suffix}"

    if not await r2_service.object_exists(r2_input_key):
        raise HTTPException(
            status_code=404,
            detail="Uploaded file not found in storage. The upload may have failed or expired.",
        )

    # Mark as processing so duplicate calls are rejected
    db_job.status = "processing"
    await db.commit()

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        input_path = tmp_path / f"original{suffix}"
        job_output_dir = tmp_path / "output"
        job_output_dir.mkdir()

        try:
            # Download from R2 to local temp (streaming, memory-efficient)
            await r2_service.download_to_file(r2_input_key, str(input_path))

            file_size_mb = input_path.stat().st_size / (1024 * 1024)
            total_duration = FFmpegService.get_duration(str(input_path))

            # Enforce monthly plan limit
            await check_usage_limit(current_user, total_duration, db)

            # Process with FFmpeg
            processing_start = time.time()
            segments = FFmpegService.split_video(
                str(input_path),
                job_output_dir,
                body.segment_duration,
                aspect_ratio=body.aspect_ratio,
                crop_position=body.crop_position,
                custom_width=body.custom_width,
                custom_height=body.custom_height,
            )
            processing_time = time.time() - processing_start

            # Upload segments to R2
            segment_infos = []
            for seg in segments:
                duration = FFmpegService.get_duration(str(seg))
                size_bytes = seg.stat().st_size
                r2_seg_key = f"jobs/{body.job_id}/{seg.name}"
                await r2_service.upload_file(str(seg), r2_seg_key)
                segment_infos.append(SegmentInfo(
                    filename=seg.name,
                    duration=duration,
                    size_bytes=size_bytes,
                    download_url=f"/api/v1/download/{body.job_id}/{seg.name}",
                ))

            # Remove the raw upload from R2 (segments are now stored)
            await r2_service.delete_prefix(f"uploads/{body.job_id}/")

            # Update job record
            auth_header = request.headers.get("authorization", "")
            source = "api" if auth_header.startswith("vs_live_") else "web"
            now = datetime.now(timezone.utc)

            db_job.segment_duration = body.segment_duration
            db_job.segments_count = len(segments)
            db_job.total_duration = total_duration
            db_job.aspect_ratio = (
                body.aspect_ratio if body.aspect_ratio and body.aspect_ratio != "custom"
                else (f"{body.custom_width}x{body.custom_height}" if body.custom_width and body.custom_height else None)
            )
            db_job.crop_position = body.crop_position if body.aspect_ratio else None
            db_job.status = "completed"
            db_job.completed_at = now
            db_job.expires_at = now + timedelta(hours=JOB_EXPIRY_HOURS)

            await record_usage(
                user=current_user,
                job_id=body.job_id,
                video_duration_seconds=total_duration,
                video_size_mb=file_size_mb,
                segments_count=len(segments),
                processing_time_seconds=processing_time,
                source=source,
                api_key_id=None,
                db=db,
            )

            return SplitResponse(
                job_id=body.job_id,
                status="completed",
                segments_count=len(segments),
                segments=segment_infos,
                original_filename=db_job.original_filename,
                total_duration=total_duration,
            )

        except HTTPException:
            db_job.status = "failed"
            await db.commit()
            raise

        except subprocess.CalledProcessError as e:
            db_job.status = "failed"
            db_job.error_message = e.stderr[:500] if hasattr(e, "stderr") and e.stderr else str(e)
            await db.commit()
            raise HTTPException(
                status_code=500,
                detail=f"Video processing failed: {db_job.error_message}",
            )

        except Exception as e:
            db_job.status = "failed"
            db_job.error_message = str(e)[:500]
            await db.commit()
            raise HTTPException(status_code=500, detail=f"Unexpected error: {str(e)}")
