"""Student storage plans.

Free tier is 5 GB. Every paid plan adds another 10 GB to the account's
lifetime entitlement:

    free   ->  5 GB
    plan 1 -> 15 GB   INR 3,999   (+10 GB)
    plan 2 -> 25 GB   INR 6,999   (+10 GB)
    plan 3 -> 35 GB   INR 6,999   (+10 GB)
    ...   (each further plan adds another 10 GB at INR 6,999)

Money is kept in paise (the smallest Razorpay unit) so nothing is ever
floating point. A plan, once paid for, is permanent: entitlement only ever
grows. Deleting documents never reduces the entitlement — that keeps the
"you paid for this space" promise.
"""
from __future__ import annotations

GB = 1024 * 1024 * 1024

FREE_GB = 5
STEP_GB = 10

# tier number -> price in INR. Tier 1 is the upgrade from the free 5 GB to
# 15 GB; tier 2 is 25 GB; every tier from 2 upwards is priced the same as the
# spec allows ("like that").
TIER_PRICES_INR: dict[int, int] = {1: 3999, 2: 6999}
DEFAULT_TIER_PRICE_INR = 6999

PLAN_LABELS: dict[int, str] = {
    0: "Free",
    1: "Storage 15 GB",
    2: "Storage 25 GB",
}


def inr_to_paise(inr: int) -> int:
    return int(inr) * 100


def total_gb_for_tier(tier: int) -> int:
    """Total storage an account owns after paying for ``tier``."""
    if tier <= 0:
        return FREE_GB
    return FREE_GB + STEP_GB * tier


def price_inr_for_tier(tier: int) -> int:
    return TIER_PRICES_INR.get(tier, DEFAULT_TIER_PRICE_INR)


def label_for_tier(tier: int) -> str:
    return PLAN_LABELS.get(tier, f"Storage {total_gb_for_tier(tier)} GB")


def free_bytes() -> int:
    return FREE_GB * GB


def bytes_for_total_gb(total_gb: int) -> int:
    return int(total_gb) * GB


def tier_from_entitlement_bytes(entitlement_bytes: int) -> int:
    """Derive the current paid tier from an account's entitlement."""
    extra_gb = (int(entitlement_bytes) - FREE_GB * GB) // GB
    if extra_gb < 0:
        extra_gb = 0
    return extra_gb // STEP_GB


def next_plan(entitlement_bytes: int) -> dict:
    """The plan an account is eligible to buy next."""
    tier = tier_from_entitlement_bytes(entitlement_bytes) + 1
    total_gb = total_gb_for_tier(tier)
    price_inr = price_inr_for_tier(tier)
    return {
        "tier": tier,
        "label": label_for_tier(tier),
        "total_gb": total_gb,
        "added_gb": STEP_GB,
        "price_inr": price_inr,
        "price_paise": inr_to_paise(price_inr),
        "total_bytes": bytes_for_total_gb(total_gb),
    }


def plan_catalog() -> list[dict]:
    """The full ladder shown on the pricing page."""
    out = [{
        "tier": 0,
        "label": label_for_tier(0),
        "total_gb": FREE_GB,
        "added_gb": FREE_GB,
        "price_inr": 0,
        "price_paise": 0,
        "total_bytes": bytes_for_total_gb(FREE_GB),
    }]
    for tier in (1, 2, 3, 4):
        total_gb = total_gb_for_tier(tier)
        price_inr = price_inr_for_tier(tier)
        out.append({
            "tier": tier,
            "label": label_for_tier(tier),
            "total_gb": total_gb,
            "added_gb": STEP_GB,
            "price_inr": price_inr,
            "price_paise": inr_to_paise(price_inr),
            "total_bytes": bytes_for_total_gb(total_gb),
        })
    return out
