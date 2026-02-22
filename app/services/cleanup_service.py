"""
Cleanup service — deletes expired job files from R2 and/or local disk.
Runs as a background asyncio task (scheduled every hour).

Strategy:
- New jobs (R2 enabled): delete objects under jobs/{job_id}/
- Old jobs (local fallback): delete the outputs/{job_id}/ directory
- Both are attempted so mixed-state deployments clean up correctly.
"""
import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select

from app.saas_layer.core.config import settings
from app.saas_layer.db.base import AsyncSessionLocal
from app.saas_layer.db.models import Job
from app.services import r2_service

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("outputs")


async def cleanup_old_files() -> dict:
    """
    Find jobs whose expires_at has passed, delete their files (R2 + local),
    and mark the job status as 'expired'.
    Returns a summary dict with counts.
    """
    now = datetime.now(timezone.utc)
    deleted = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                select(Job).where(
                    Job.expires_at <= now,
                    Job.status == "completed",
                )
            )
            expired_jobs = result.scalars().all()

            for job in expired_jobs:
                try:
                    # Delete from R2 (new jobs)
                    if settings.r2_enabled:
                        count = await r2_service.delete_prefix(f"jobs/{job.job_id}/")
                        if count:
                            logger.info("R2: deleted %d objects for job %s", count, job.job_id)

                    # Delete from local filesystem (old jobs / fallback)
                    job_dir = OUTPUT_DIR / job.job_id
                    if job_dir.exists():
                        shutil.rmtree(job_dir)
                        logger.info("Local: deleted output dir for job %s", job.job_id)

                    job.status = "expired"
                    deleted += 1

                except Exception as exc:
                    logger.error("Failed to delete job %s: %s", job.job_id, exc)
                    errors += 1

            await db.commit()

        except Exception as exc:
            logger.error("Cleanup task DB error: %s", exc)
            await db.rollback()

    summary = {"deleted": deleted, "errors": errors, "checked_at": now.isoformat()}
    if deleted or errors:
        logger.info("Cleanup run: %d expired, %d errors", deleted, errors)
    return summary


async def run_cleanup_loop(interval_seconds: int = 3600) -> None:
    """
    Infinite loop that calls cleanup_old_files() every interval_seconds.
    Designed to be launched as an asyncio background task.
    """
    logger.info("Cleanup loop started (interval=%ds)", interval_seconds)
    while True:
        try:
            await cleanup_old_files()
        except Exception as exc:
            logger.error("Unhandled error in cleanup loop: %s", exc)
        await asyncio.sleep(interval_seconds)
