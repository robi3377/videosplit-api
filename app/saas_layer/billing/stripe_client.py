"""
Thin async wrappers around the synchronous Stripe Python SDK.
All SDK calls are dispatched to a thread pool via asyncio.to_thread()
so they don't block the async event loop.
"""
import asyncio
import logging
from typing import Optional

import stripe

from app.saas_layer.core.config import settings

logger = logging.getLogger(__name__)

# Set the API key at module load time (empty string disables Stripe SDK calls)
stripe.api_key = settings.STRIPE_SECRET_KEY


async def create_checkout_session(
    user_id: int,
    user_email: str,
    price_id: str,
    success_url: str,
    cancel_url: str,
    stripe_customer_id: Optional[str] = None,
) -> stripe.checkout.Session:
    """
    Create a Stripe Checkout Session for a subscription.
    Attaches existing customer if stripe_customer_id is provided.
    """
    def _create():
        params: dict = {
            "mode": "subscription",
            "line_items": [{"price": price_id, "quantity": 1}],
            "success_url": success_url,
            "cancel_url": cancel_url,
            "metadata": {"user_id": str(user_id)},
            "allow_promotion_codes": True,
        }
        if stripe_customer_id:
            params["customer"] = stripe_customer_id
        else:
            params["customer_email"] = user_email
        return stripe.checkout.Session.create(**params)

    return await asyncio.to_thread(_create)


async def create_customer_portal_session(
    stripe_customer_id: str,
    return_url: str,
) -> stripe.billing_portal.Session:
    """Create a Stripe Customer Portal session for subscription management."""
    def _create():
        return stripe.billing_portal.Session.create(
            customer=stripe_customer_id,
            return_url=return_url,
        )

    return await asyncio.to_thread(_create)


async def retrieve_subscription(subscription_id: str) -> stripe.Subscription:
    """Fetch a Stripe Subscription with its items expanded."""
    def _retrieve():
        return stripe.Subscription.retrieve(
            subscription_id,
            expand=["items.data.price"],
        )

    return await asyncio.to_thread(_retrieve)


async def modify_subscription(
    subscription_id: str,
    new_price_id: str,
    is_upgrade: bool,
) -> stripe.Subscription:
    """
    Switch an existing subscription to a new price ID.
    Upgrades charge the prorated difference immediately.
    Downgrades credit unused time on the next invoice.
    """
    def _modify():
        sub = stripe.Subscription.retrieve(subscription_id, expand=["items.data.price"])
        item_id = sub["items"]["data"][0]["id"]
        return stripe.Subscription.modify(
            subscription_id,
            items=[{"id": item_id, "price": new_price_id}],
            proration_behavior="always_invoice" if is_upgrade else "create_prorations",
        )

    return await asyncio.to_thread(_modify)


async def construct_webhook_event(
    payload: bytes,
    sig_header: str,
    webhook_secret: str,
) -> stripe.Event:
    """
    Validate the Stripe webhook signature and return the Event object.
    Raises stripe.error.SignatureVerificationError on invalid signature.
    """
    def _construct():
        return stripe.Webhook.construct_event(payload, sig_header, webhook_secret)

    return await asyncio.to_thread(_construct)
