"""
Cleanup service — deletes job output files older than 24 hours.
Runs as a background asyncio task (scheduled every hour).
"""
import asyncio
import logging
import shutil
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.db.base import AsyncSessionLocal
from app.saas_layer.db.models import Job

logger = logging.getLogger(__name__)

OUTPUT_DIR = Path("outputs")


async def cleanup_old_files() -> dict:
    """
    Find jobs whose expires_at has passed, delete their output files,
    and mark the job status as 'expired'.
    Returns a summary dict with counts.
    """
    now = datetime.now(timezone.utc)
    deleted = 0
    errors = 0

    async with AsyncSessionLocal() as db:
        try:
            # Find expired jobs that still have status 'completed'
            result = await db.execute(
                select(Job).where(
                    Job.expires_at <= now,
                    Job.status == "completed",
                )
            )
            expired_jobs = result.scalars().all()

            for job in expired_jobs:
                job_dir = OUTPUT_DIR / job.job_id
                try:
                    if job_dir.exists():
                        shutil.rmtree(job_dir)
                        logger.info("Deleted output dir for expired job %s", job.job_id)
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
