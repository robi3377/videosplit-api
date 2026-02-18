import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.auth.dependencies import get_current_active_user
from app.saas_layer.billing import stripe_client
from app.saas_layer.billing.schemas import (
    CheckoutResponse,
    CreateCheckoutRequest,
    PortalResponse,
    SubscriptionStatus,
)
from app.saas_layer.core.config import settings
from app.saas_layer.db.base import get_db
from app.saas_layer.db.models import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/billing", tags=["billing"])

# Map plan name → Stripe price ID
_PLAN_PRICE_MAP = {
    "starter": settings.STRIPE_PRICE_ID_STARTER,
    "pro": settings.STRIPE_PRICE_ID_PRO,
}

# Numeric order used to determine upgrade vs downgrade
_TIER_ORDER = {"free": 0, "starter": 1, "pro": 2, "enterprise": 3}


@router.post("/checkout", response_model=CheckoutResponse)
async def create_checkout(
    body: CreateCheckoutRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upgrade or downgrade a subscription.
    - Existing subscribers: modify the subscription directly (prorated).
    - New subscribers: create a Stripe Checkout Session.
    """
    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured on this server",
        )

    price_id = _PLAN_PRICE_MAP.get(body.plan)
    if not price_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown plan: {body.plan}",
        )

    # If the user already has an active subscription, modify it directly — no new checkout needed
    if current_user.stripe_subscription_id and current_user.subscription_status in ("active", "trialing"):
        current_order = _TIER_ORDER.get(current_user.plan_tier.value.lower(), 0)
        target_order = _TIER_ORDER.get(body.plan, 0)
        is_upgrade = target_order > current_order
        try:
            await stripe_client.modify_subscription(
                subscription_id=current_user.stripe_subscription_id,
                new_price_id=price_id,
                is_upgrade=is_upgrade,
            )
        except Exception as exc:
            logger.error("Stripe subscription modification failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Failed to modify subscription",
            )
        return CheckoutResponse(plan_changed=True)

    # New subscriber — create a Checkout Session
    success_url = f"{settings.APP_BASE_URL}/static/dashboard.html?payment=success"
    cancel_url = f"{settings.APP_BASE_URL}/static/dashboard.html?payment=cancelled"

    try:
        session = await stripe_client.create_checkout_session(
            user_id=current_user.id,
            user_email=current_user.email,
            price_id=price_id,
            success_url=success_url,
            cancel_url=cancel_url,
            stripe_customer_id=current_user.stripe_customer_id,
        )
    except Exception as exc:
        logger.error("Stripe checkout session creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create checkout session",
        )

    return CheckoutResponse(checkout_url=session.url)


@router.post("/portal", response_model=PortalResponse)
async def customer_portal(
    current_user: User = Depends(get_current_active_user),
):
    """
    Create a Stripe Customer Portal session.
    Allows the user to manage their subscription, payment method, and invoices.
    Requires the user to have an active Stripe customer ID.
    """
    if not settings.stripe_enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Billing is not configured on this server",
        )

    if not current_user.stripe_customer_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active subscription found. Please subscribe to a plan first.",
        )

    return_url = f"{settings.APP_BASE_URL}/static/index.html"

    try:
        portal_session = await stripe_client.create_customer_portal_session(
            stripe_customer_id=current_user.stripe_customer_id,
            return_url=return_url,
        )
    except Exception as exc:
        logger.error("Stripe portal session creation failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to create portal session",
        )

    return PortalResponse(portal_url=portal_session.url)


@router.get("/status", response_model=SubscriptionStatus)
async def get_subscription_status(
    current_user: User = Depends(get_current_active_user),
):
    """
    Return the current user's subscription and usage status.
    Always works — reads from the local database, no Stripe API call.
    """
    return SubscriptionStatus(
        plan_tier=current_user.plan_tier.value,
        subscription_status=current_user.subscription_status,
        subscription_ends_at=current_user.subscription_ends_at,
        monthly_minutes_limit=current_user.monthly_minutes_limit,
        monthly_minutes_used=round(current_user.monthly_minutes_used, 2),
        stripe_customer_id=current_user.stripe_customer_id,
        stripe_publishable_key=settings.STRIPE_PUBLISHABLE_KEY,
    )
