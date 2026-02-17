import logging
import time

from fastapi import Depends, HTTPException, status

from app.saas_layer.auth.dependencies import get_current_active_user
from app.saas_layer.core.redis_client import check_rate_limit, rate_limit_key
from app.saas_layer.db.models import PlanTier, User

logger = logging.getLogger(__name__)

# Requests per minute allowed for the /split endpoint per plan
_SPLIT_RATE_LIMITS: dict[PlanTier, int] = {
    PlanTier.FREE: 5,
    PlanTier.STARTER: 20,
    PlanTier.PRO: 60,
    PlanTier.ENTERPRISE: 200,
}

# General API rate limits (per minute)
_API_RATE_LIMITS: dict[PlanTier, int] = {
    PlanTier.FREE: 60,
    PlanTier.STARTER: 300,
    PlanTier.PRO: 1000,
    PlanTier.ENTERPRISE: 5000,
}


async def check_split_rate_limit(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    FastAPI dependency for the /split endpoint.
    Validates the user is authenticated (via get_current_active_user),
    then enforces per-plan rate limits using Redis.

    Returns the authenticated User so routes don't need a separate auth dependency.
    Fails open (allows request) if Redis is unavailable.
    """
    limit = _SPLIT_RATE_LIMITS.get(current_user.plan_tier, 5)
    key = rate_limit_key(current_user.id, "split")
    allowed, count = await check_rate_limit(key, max_requests=limit, window_seconds=60)

    if not allowed:
        logger.warning(
            "Rate limit exceeded for user %d (plan=%s, count=%d, limit=%d)",
            current_user.id,
            current_user.plan_tier,
            count,
            limit,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                f"Rate limit exceeded: {limit} video splits per minute for your plan. "
                "Upgrade your plan for higher limits."
            ),
            headers={"Retry-After": "60"},
        )

    return current_user


async def check_api_rate_limit(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """
    General API rate limit dependency for non-video endpoints.
    More permissive than the split limit.
    """
    limit = _API_RATE_LIMITS.get(current_user.plan_tier, 60)
    key = rate_limit_key(current_user.id, "api")
    allowed, count = await check_rate_limit(key, max_requests=limit, window_seconds=60)

    if not allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Rate limit exceeded: {limit} requests per minute.",
            headers={"Retry-After": "60"},
        )

    return current_user
