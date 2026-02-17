import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.auth.dependencies import require_admin
from app.saas_layer.db.base import get_db
from app.saas_layer.db.models import Job, PlanTier, UsageLog, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Response schemas (local — no need for a separate schemas.py)
# ---------------------------------------------------------------------------

class MetricsResponse(BaseModel):
    total_users: int
    users_by_plan: dict[str, int]
    active_subscriptions: int
    jobs_today: int
    jobs_this_month: int
    minutes_processed_this_month: float


class AdminUserResponse(BaseModel):
    id: int
    email: str
    full_name: Optional[str]
    plan_tier: str
    subscription_status: Optional[str]
    is_admin: bool
    is_active: bool
    monthly_minutes_used: float
    monthly_minutes_limit: int
    created_at: datetime
    last_login: Optional[datetime]

    model_config = ConfigDict(from_attributes=True)


class PaginatedUsers(BaseModel):
    total: int
    page: int
    per_page: int
    users: list[AdminUserResponse]


class SetPlanRequest(BaseModel):
    plan_tier: str
    minutes_limit: Optional[int] = None


class ToggleAdminRequest(BaseModel):
    is_admin: bool


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Aggregate platform metrics.
    Returns user counts by plan, job totals, and minutes processed.
    """
    now = datetime.now(timezone.utc)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Total users
    result = await db.execute(select(func.count(User.id)))
    total_users = result.scalar_one()

    # Users by plan
    result = await db.execute(
        select(User.plan_tier, func.count(User.id)).group_by(User.plan_tier)
    )
    users_by_plan = {row[0].value: row[1] for row in result.all()}

    # Active subscriptions (non-FREE users with active status)
    result = await db.execute(
        select(func.count(User.id)).where(
            User.plan_tier != PlanTier.FREE,
            User.subscription_status == "active",
        )
    )
    active_subscriptions = result.scalar_one()

    # Jobs today
    result = await db.execute(
        select(func.count(Job.id)).where(Job.created_at >= today_start)
    )
    jobs_today = result.scalar_one()

    # Jobs this month
    result = await db.execute(
        select(func.count(Job.id)).where(Job.created_at >= month_start)
    )
    jobs_this_month = result.scalar_one()

    # Minutes processed this month
    result = await db.execute(
        select(func.coalesce(func.sum(UsageLog.video_duration_seconds), 0.0)).where(
            UsageLog.created_at >= month_start
        )
    )
    total_seconds = result.scalar_one()
    minutes_processed_this_month = round(total_seconds / 60.0, 2)

    return MetricsResponse(
        total_users=total_users,
        users_by_plan=users_by_plan,
        active_subscriptions=active_subscriptions,
        jobs_today=jobs_today,
        jobs_this_month=jobs_this_month,
        minutes_processed_this_month=minutes_processed_this_month,
    )


@router.get("/users", response_model=PaginatedUsers)
async def list_users(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=200),
    plan_tier: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None, description="Search by email or name"),
):
    """Paginated list of all users with optional filtering."""
    query = select(User)

    # Filters
    if plan_tier:
        try:
            tier_enum = PlanTier(plan_tier)
            query = query.where(User.plan_tier == tier_enum)
        except ValueError:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid plan_tier: {plan_tier}",
            )

    if search:
        search_term = f"%{search}%"
        query = query.where(
            User.email.ilike(search_term) | User.full_name.ilike(search_term)
        )

    # Count total
    count_result = await db.execute(
        select(func.count()).select_from(query.subquery())
    )
    total = count_result.scalar_one()

    # Paginate
    offset = (page - 1) * per_page
    query = query.order_by(User.created_at.desc()).offset(offset).limit(per_page)
    result = await db.execute(query)
    users = result.scalars().all()

    return PaginatedUsers(
        total=total,
        page=page,
        per_page=per_page,
        users=users,
    )


@router.put("/users/{user_id}/plan", status_code=status.HTTP_200_OK)
async def set_user_plan(
    user_id: int,
    body: SetPlanRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Manually override a user's plan tier and optional minute limit."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    try:
        user.plan_tier = PlanTier(body.plan_tier)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid plan_tier: {body.plan_tier}",
        )

    if body.minutes_limit is not None:
        user.monthly_minutes_limit = body.minutes_limit
    else:
        # Apply default limits for the new plan
        defaults = {
            PlanTier.FREE: 100,
            PlanTier.STARTER: 1000,
            PlanTier.PRO: 999999,
            PlanTier.ENTERPRISE: 999999,
        }
        user.monthly_minutes_limit = defaults.get(user.plan_tier, 100)

    logger.info(
        "Admin %d set user %d plan to %s (%d min)",
        admin.id,
        user_id,
        user.plan_tier.value,
        user.monthly_minutes_limit,
    )
    return {"user_id": user_id, "plan_tier": user.plan_tier.value, "minutes_limit": user.monthly_minutes_limit}


@router.put("/users/{user_id}/admin", status_code=status.HTTP_200_OK)
async def toggle_admin(
    user_id: int,
    body: ToggleAdminRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Grant or revoke admin status for a user."""
    if user_id == admin.id and not body.is_admin:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot revoke your own admin status",
        )

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    user.is_admin = body.is_admin
    logger.info(
        "Admin %d %s admin for user %d",
        admin.id,
        "granted" if body.is_admin else "revoked",
        user_id,
    )
    return {"user_id": user_id, "is_admin": user.is_admin}
