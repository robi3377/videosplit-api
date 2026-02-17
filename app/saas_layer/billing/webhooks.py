"""
Stripe webhook handler.
Mounted at /webhooks/stripe — NO authentication dependency (uses Stripe signature).

When STRIPE_WEBHOOK_SECRET is blank (local dev), events are silently accepted
without signature validation so the app still starts and the endpoint exists.
"""
import logging
from datetime import datetime, timezone
from typing import Callable, Optional

import stripe
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.saas_layer.billing.stripe_client import construct_webhook_event, retrieve_subscription
from app.saas_layer.core.config import settings
from app.saas_layer.db.base import get_db
from app.saas_layer.db.models import PlanTier, User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Map Stripe price IDs → (PlanTier, monthly_minutes_limit)
# Built lazily so settings are already loaded
def _get_price_plan_map() -> dict[str, tuple[PlanTier, int]]:
    return {
        settings.STRIPE_PRICE_ID_STARTER: (PlanTier.STARTER, 1000),
        settings.STRIPE_PRICE_ID_PRO: (PlanTier.PRO, 999999),
    }


async def _get_user_by_customer_id(
    customer_id: str, db: AsyncSession
) -> Optional[User]:
    result = await db.execute(
        select(User).where(User.stripe_customer_id == customer_id)
    )
    return result.scalar_one_or_none()


async def _handle_checkout_completed(event_data: dict, db: AsyncSession) -> None:
    """
    checkout.session.completed
    Triggered when user completes Stripe checkout.
    Sets customer_id, subscription_id, and upgrades plan.
    """
    session = event_data["object"]
    user_id_str = session.get("metadata", {}).get("user_id")
    if not user_id_str:
        logger.warning("checkout.session.completed missing user_id in metadata")
        return

    user_id = int(user_id_str)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        logger.warning("checkout.session.completed: user %d not found", user_id)
        return

    customer_id = session.get("customer")
    subscription_id = session.get("subscription")

    # Update Stripe identifiers
    if customer_id:
        user.stripe_customer_id = customer_id
    if subscription_id:
        user.stripe_subscription_id = subscription_id

    # Fetch subscription details to get the price ID
    if subscription_id:
        try:
            subscription = await retrieve_subscription(subscription_id)
            price_id = subscription["items"]["data"][0]["price"]["id"]
            price_plan_map = _get_price_plan_map()
            if price_id in price_plan_map:
                plan_tier, minutes_limit = price_plan_map[price_id]
                user.plan_tier = plan_tier
                user.monthly_minutes_limit = minutes_limit
                user.subscription_status = subscription.get("status", "active")
                logger.info(
                    "Upgraded user %d to %s (%d min/month)",
                    user_id,
                    plan_tier.value,
                    minutes_limit,
                )
        except Exception as exc:
            logger.error(
                "Failed to retrieve subscription %s: %s", subscription_id, exc
            )


async def _handle_subscription_updated(event_data: dict, db: AsyncSession) -> None:
    """
    customer.subscription.updated
    Handles plan changes and status updates (e.g., past_due → active).
    """
    subscription = event_data["object"]
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    user = await _get_user_by_customer_id(customer_id, db)
    if not user:
        logger.warning(
            "subscription.updated: no user found for customer %s", customer_id
        )
        return

    sub_status = subscription.get("status", "")
    user.subscription_status = sub_status
    user.stripe_subscription_id = subscription.get("id")

    # Update plan tier from price ID
    try:
        items = subscription.get("items", {}).get("data", [])
        if items:
            price_id = items[0].get("price", {}).get("id", "")
            price_plan_map = _get_price_plan_map()
            if price_id in price_plan_map:
                plan_tier, minutes_limit = price_plan_map[price_id]
                user.plan_tier = plan_tier
                user.monthly_minutes_limit = minutes_limit
    except Exception as exc:
        logger.error("Error reading subscription items: %s", exc)

    # Set end date if subscription is canceling at period end
    cancel_at_period_end = subscription.get("cancel_at_period_end", False)
    if cancel_at_period_end:
        period_end = subscription.get("current_period_end")
        if period_end:
            user.subscription_ends_at = datetime.fromtimestamp(
                period_end, tz=timezone.utc
            )
    elif sub_status == "active":
        user.subscription_ends_at = None

    logger.info(
        "Updated subscription for user %d: status=%s plan=%s",
        user.id,
        sub_status,
        user.plan_tier.value,
    )


async def _handle_subscription_deleted(event_data: dict, db: AsyncSession) -> None:
    """
    customer.subscription.deleted
    Triggered when subscription is fully canceled. Downgrades user to FREE.
    """
    subscription = event_data["object"]
    customer_id = subscription.get("customer")
    if not customer_id:
        return

    user = await _get_user_by_customer_id(customer_id, db)
    if not user:
        return

    user.plan_tier = PlanTier.FREE
    user.monthly_minutes_limit = 100
    user.subscription_status = "canceled"
    user.stripe_subscription_id = None
    user.subscription_ends_at = None

    logger.info("Downgraded user %d to FREE (subscription canceled)", user.id)


async def _handle_invoice_paid(event_data: dict, db: AsyncSession) -> None:
    """
    invoice.paid
    Confirms the subscription is active (e.g., after recovery from past_due).
    """
    invoice = event_data["object"]
    customer_id = invoice.get("customer")
    if not customer_id:
        return

    user = await _get_user_by_customer_id(customer_id, db)
    if not user:
        return

    if user.subscription_status == "past_due":
        user.subscription_status = "active"
        logger.info("Restored subscription to active for user %d", user.id)


async def _handle_invoice_payment_failed(event_data: dict, db: AsyncSession) -> None:
    """
    invoice.payment_failed
    Marks the subscription as past_due. Stripe will retry automatically.
    """
    invoice = event_data["object"]
    customer_id = invoice.get("customer")
    if not customer_id:
        return

    user = await _get_user_by_customer_id(customer_id, db)
    if not user:
        return

    user.subscription_status = "past_due"
    logger.warning("Payment failed for user %d — subscription is past_due", user.id)


# Dispatch table: event type → handler
_EVENT_HANDLERS: dict[str, Callable] = {
    "checkout.session.completed": _handle_checkout_completed,
    "customer.subscription.updated": _handle_subscription_updated,
    "customer.subscription.deleted": _handle_subscription_deleted,
    "invoice.paid": _handle_invoice_paid,
    "invoice.payment_failed": _handle_invoice_payment_failed,
}


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Receive and process Stripe webhook events.
    Uses Stripe signature validation when STRIPE_WEBHOOK_SECRET is configured.
    When the secret is blank (local dev), events are accepted without validation.
    Always returns 200 — Stripe retries on non-2xx responses.
    """
    payload = await request.body()

    # Validate signature if webhook secret is configured
    if settings.stripe_webhooks_enabled:
        sig_header = request.headers.get("stripe-signature", "")
        if not sig_header:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Missing stripe-signature header",
            )
        try:
            event = await construct_webhook_event(
                payload=payload,
                sig_header=sig_header,
                webhook_secret=settings.STRIPE_WEBHOOK_SECRET,
            )
        except stripe.error.SignatureVerificationError:
            logger.warning("Stripe webhook signature verification failed")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid webhook signature",
            )
    else:
        # Local dev: parse JSON without signature check
        import json
        try:
            event = json.loads(payload)
        except Exception:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid JSON payload",
            )

    event_type = event.get("type") if isinstance(event, dict) else event["type"]
    event_data = event.get("data") if isinstance(event, dict) else event["data"]

    handler = _EVENT_HANDLERS.get(event_type)
    if handler:
        try:
            await handler(event_data, db)
        except Exception as exc:
            # Log but don't return non-2xx — Stripe would retry infinitely
            logger.exception(
                "Error handling Stripe event %s: %s", event_type, exc
            )
    else:
        logger.debug("Unhandled Stripe event type: %s", event_type)

    return {"status": "ok"}
