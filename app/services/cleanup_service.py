"""
Cleanup service — deletes expired job files from R2 and removes DB records.
Runs as a background asyncio task every 30 minutes.

Strategy per expired job:
  1. Delete all R2 objects under jobs/{job_id}/  (best effort — log but continue on error)
  2. Delete the job row from the database        (own commit per job)

Jobs are identified by expires_at < NOW() regardless of status.
"""
import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select, delete

from app.saas_layer.db.base import AsyncSessionLocal
from app.saas_layer.db.models import Job
from app.services import r2_service

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 600  # 10 minutes


# ─────────────────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────────────────

async def _get_expired_job_ids(now: datetime) -> list[str]:
    """Return job_ids of all jobs whose expires_at has passed (any status)."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(Job.job_id).where(
                Job.expires_at != None,   # noqa: E711 — SQLAlchemy requires != None
                Job.expires_at < now,
            )
        )
        return list(result.scalars().all())


async def _delete_r2_files(job_id: str) -> int:
    """
    Delete all R2 objects under jobs/{job_id}/.
    Returns the number of objects deleted (0 on error or nothing found).
    Errors are logged but never raised — R2 failure must not block DB cleanup.
    """
    prefix = f"jobs/{job_id}/"
    try:
        count = await r2_service.delete_prefix(prefix)
        if count:
            logger.info("  [%s] R2: deleted %d file(s) under %s", job_id, count, prefix)
        else:
            logger.warning("  [%s] R2: no files found under %s", job_id, prefix)
        return count
    except Exception as exc:
        logger.error("  [%s] R2: deletion failed — %s", job_id, exc, exc_info=True)
        return 0


async def _delete_db_record(job_id: str) -> bool:
    """
    Delete the job row from the database.
    Uses its own session + commit so one job never blocks another.
    Returns True on success, False on error.
    """
    async with AsyncSessionLocal() as db:
        try:
            result = await db.execute(
                delete(Job).where(Job.job_id == job_id)
            )
            await db.commit()
            if result.rowcount:
                logger.info("  [%s] DB: record deleted", job_id)
            else:
                logger.warning("  [%s] DB: record not found (already deleted?)", job_id)
            return True
        except Exception as exc:
            await db.rollback()
            logger.error("  [%s] DB: deletion failed — %s", job_id, exc, exc_info=True)
            return False


# ─────────────────────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────────────────────

async def cleanup_expired_jobs() -> dict:
    """
    Main cleanup pass: find all expired jobs, delete their R2 files, then
    delete the DB records. Returns a summary dict.
    """
    now = datetime.now(timezone.utc)
    jobs_processed = 0
    total_files_deleted = 0
    errors = 0

    # ── 1. Discover expired jobs ──────────────────────────────────────────────
    try:
        job_ids = await _get_expired_job_ids(now)
    except Exception as exc:
        logger.error("Cleanup: failed to query expired jobs — %s", exc, exc_info=True)
        return {"jobs_processed": 0, "total_files_deleted": 0, "errors": 1}

    if not job_ids:
        logger.debug("Cleanup: no expired jobs found at %s", now.isoformat())
        return {"jobs_processed": 0, "total_files_deleted": 0, "errors": 0}

    logger.info("Cleanup: found %d expired job(s) to process", len(job_ids))

    # ── 2. Process each job individually ─────────────────────────────────────
    for job_id in job_ids:
        logger.info("Cleanup: processing job %s", job_id)
        job_ok = True

        # Step A — R2 (best effort; failure still allows DB cleanup)
        r2_count = await _delete_r2_files(job_id)
        total_files_deleted += r2_count

        # Step B — DB record
        db_ok = await _delete_db_record(job_id)
        if not db_ok:
            job_ok = False

        if job_ok:
            jobs_processed += 1
        else:
            errors += 1

    # ── 3. Summary ────────────────────────────────────────────────────────────
    logger.info(
        "Cleanup run: %d job(s) processed, %d file(s) deleted from R2, %d error(s)",
        jobs_processed,
        total_files_deleted,
        errors,
    )
    return {
        "jobs_processed": jobs_processed,
        "total_files_deleted": total_files_deleted,
        "errors": errors,
        "checked_at": now.isoformat(),
    }


async def run_cleanup_loop(interval_seconds: int = _INTERVAL_SECONDS) -> None:
    """
    Infinite loop that runs cleanup_expired_jobs() every interval_seconds.
    Launched as an asyncio background task from main.py lifespan.
    """
    logger.info("Cleanup loop started (interval=%ds / %.0f min)", interval_seconds, interval_seconds / 60)
    while True:
        try:
            await cleanup_expired_jobs()
        except Exception as exc:
            # Should never reach here because cleanup_expired_jobs() handles its own
            # exceptions, but guard against any unexpected failure.
            logger.error("Cleanup: unhandled error in loop — %s", exc, exc_info=True)
        await asyncio.sleep(interval_seconds)
