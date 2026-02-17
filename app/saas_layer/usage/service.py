import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.auth.service import reset_monthly_usage_if_needed
from app.saas_layer.db.models import PlanTier, UsageLog, User

logger = logging.getLogger(__name__)

# -1 sentinel means unlimited; stored as high int in DB
_UNLIMITED = 999999


async def check_usage_limit(
    user: User,
    video_duration_seconds: float,
    db: AsyncSession,
) -> None:
    """
    Raise HTTP 402 if the user has exceeded their monthly plan limit.
    Also performs a lazy monthly usage reset before checking.
    """
    # Reset usage counter if we're in a new month
    user = await reset_monthly_usage_if_needed(user, db)

    # PRO and ENTERPRISE are unlimited
    if user.plan_tier in (PlanTier.PRO, PlanTier.ENTERPRISE):
        return

    minutes_limit = user.monthly_minutes_limit
    minutes_used = user.monthly_minutes_used
    minutes_requested = video_duration_seconds / 60.0

    if minutes_used + minutes_requested > minutes_limit:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "error": "plan_limit_exceeded",
                "message": (
                    f"You have used {minutes_used:.1f} of your {minutes_limit} "
                    f"monthly minutes. This video requires {minutes_requested:.1f} more minutes."
                ),
                "minutes_used": round(minutes_used, 2),
                "minutes_limit": minutes_limit,
                "minutes_requested": round(minutes_requested, 2),
                "plan_tier": user.plan_tier.value,
                "upgrade_url": "/billing/checkout",
            },
        )


async def record_usage(
    user: User,
    job_id: str,
    video_duration_seconds: float,
    video_size_mb: float,
    segments_count: int,
    processing_time_seconds: float,
    source: str,
    api_key_id: Optional[int],
    db: AsyncSession,
) -> None:
    """
    Persist a UsageLog row and increment the user's monthly_minutes_used.
    Called after every successful video split.
    """
    log = UsageLog(
        user_id=user.id,
        job_id=job_id,
        video_duration_seconds=video_duration_seconds,
        video_size_mb=video_size_mb,
        segments_count=segments_count,
        processing_time_seconds=processing_time_seconds,
        source=source,
        api_key_id=api_key_id,
    )
    db.add(log)

    # Update user's running counter
    user.monthly_minutes_used = user.monthly_minutes_used + (video_duration_seconds / 60.0)


async def get_user_usage_summary(user: User, db: AsyncSession) -> dict:
    """Return current usage stats and the last 10 jobs for the user."""
    result = await db.execute(
        select(UsageLog)
        .where(UsageLog.user_id == user.id)
        .order_by(UsageLog.created_at.desc())
        .limit(10)
    )
    recent_logs = result.scalars().all()

    return {
        "minutes_used": round(user.monthly_minutes_used, 2),
        "minutes_limit": user.monthly_minutes_limit,
        "plan_tier": user.plan_tier.value,
        "reset_date": user.last_usage_reset,
        "recent_jobs": [
            {
                "job_id": log.job_id,
                "duration_seconds": log.video_duration_seconds,
                "segments_count": log.segments_count,
                "source": log.source,
                "created_at": log.created_at,
            }
            for log in recent_logs
        ],
    }
