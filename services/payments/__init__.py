"""Payment services — Stars + YooKassa."""

from services.payments.packages import PACKAGES, REFERRAL_BONUS_PERCENT, SUBSCRIPTIONS, Package, Subscription
from services.payments.stars import StarsPaymentService, credit_referral_bonus
from services.payments.yookassa import YooKassaPaymentService

__all__ = [
    "PACKAGES",
    "REFERRAL_BONUS_PERCENT",
    "SUBSCRIPTIONS",
    "Package",
    "StarsPaymentService",
    "Subscription",
    "YooKassaPaymentService",
    "credit_referral_bonus",
]
