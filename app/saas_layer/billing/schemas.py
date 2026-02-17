from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


class CreateCheckoutRequest(BaseModel):
    plan: Literal["starter", "pro"]


class CheckoutResponse(BaseModel):
    checkout_url: str


class PortalResponse(BaseModel):
    portal_url: str


class SubscriptionStatus(BaseModel):
    plan_tier: str
    subscription_status: Optional[str]
    subscription_ends_at: Optional[datetime]
    monthly_minutes_limit: int
    monthly_minutes_used: float
    stripe_customer_id: Optional[str]
    stripe_publishable_key: str

    model_config = ConfigDict(from_attributes=True)
