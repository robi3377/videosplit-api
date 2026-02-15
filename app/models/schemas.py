from pydantic import BaseModel, Field
from typing import List, Optional


class SplitRequest(BaseModel):
    """Request model for video splitting (query parameters)"""
    segment_duration: int = Field(
        default=60,
        ge=1,
        le=3600,
        description="Duration of each segment in seconds (1-3600)"
    )


class SegmentInfo(BaseModel):
    """Information about a single video segment"""
    filename: str = Field(description="Name of the segment file")
    duration: float = Field(description="Duration in seconds")
    size_bytes: int = Field(description="File size in bytes")
    download_url: str = Field(description="URL to download this segment")


class SplitResponse(BaseModel):
    """Response after successfully splitting a video"""
    job_id: str = Field(description="Unique identifier for this job")
    status: str = Field(description="Job status (completed, failed, etc.)")
    segments_count: int = Field(description="Total number of segments created")
    segments: List[SegmentInfo] = Field(description="List of all segments")
    original_filename: str = Field(description="Name of the original uploaded file")
    total_duration: float = Field(description="Total duration of original video in seconds")


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str = Field(description="Error message")
    detail: Optional[str] = Field(default=None, description="Additional error details")


class JobStatus(BaseModel):
    """Status of a processing job"""
    job_id: str
    status: str
    message: Optional[str] = None