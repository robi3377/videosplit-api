from fastapi import APIRouter, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse
from app.services.ffmpeg_service import FFmpegService  # Changed!
from app.models.schemas import SplitResponse, SegmentInfo, ErrorResponse  # Changed!
from pathlib import Path
import uuid
import shutil
import subprocess
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
    file: UploadFile = File(...),
    segment_duration: int = Query(default=60, ge=1, le=3600)
):
    """
    Split a video into equal-length segments
    
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
```
    """
    
    # Step 1: Validate file type
    if not file.content_type or not file.content_type.startswith('video/'):
        raise HTTPException(
            status_code=400,
            detail="File must be a video. Supported formats: mp4, mov, avi, mkv, etc."
        )
    
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
    
    # Step 4: Create output directory for this job
    job_output_dir = OUTPUT_DIR / job_id
    job_output_dir.mkdir(exist_ok=True)
    
    try:
        # Step 5: Get original video duration
        total_duration = FFmpegService.get_duration(str(input_path))
        
        # Step 6: Split the video
        segments = FFmpegService.split_video(
            str(input_path),
            job_output_dir,
            segment_duration
        )
        
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
        
        # Step 9: Return response
        return SplitResponse(
            job_id=job_id,
            status="completed",
            segments_count=len(segments),
            segments=segment_infos,
            original_filename=file.filename,
            total_duration=total_duration
        )
        
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
    
    job_dir = OUTPUT_DIR / job_id
    
    # Check if job exists
    if not job_dir.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Job not found. Job ID may be incorrect."
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