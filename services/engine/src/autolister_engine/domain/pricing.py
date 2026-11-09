"""The pricing rules.

Pure functions: no network, no clock, no I/O. Every price the system proposes
is decided here, which is what lets the safety properties be tested
exhaustively (see ``tests/test_properties.py``).

Objective: keep each position inside LooksRare's listing-rewards band, close
enough to the floor to earn, while keeping enough cheaper listings in front of
it that a market move or a floor sweep does not sell it below value.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from typing import Optional

from autolister_core import guard
from autolister_core.money import Wei, add_pct, pct_above

from ..config import Strategy
from .models import Floor, MarketView

MAX_PREMIUM_STEPS = 50
RENEWAL_DECREMENT_WEI: Wei = 10**11
"""A renewal must undercut the live ask: LooksRare rejects a second, equal or higher ask."""


class Action(str, Enum):
    HOLD = "hold"
    LIST = "list"
    CANCEL_AND_RELIST = "cancel_and_relist"
    LOWER = "lower"


@dataclass(frozen=True)
class PriceProposal:
    price_wei: Wei
    premium_pct: Decimal
    used_rank_fallback: bool


@dataclass(frozen=True)
class Decision:
    action: Action
    reason: str


def emergency_floor(view: MarketView, strategy: Strategy) -> Wei:
    """The lowest price the system will ever list at (``autolister_core.guard``).

    It counts every ask, our own included, so the signer can recompute it
    independently from public data.
    """
    return guard.emergency_floor(view.prices, strategy.emergency_stop_rank)


def propose_price(view: MarketView, strategy: Strategy) -> PriceProposal:
    """Choose a listing price.

    1. Start ``target_premium_pct`` above the global floor.
    2. Raise it in ``premium_step_pct`` steps until it clears the LooksRare floor
       by more than ``min_premium_over_looksrare_pct``.
    3. If that leaves fewer than ``relist_rank`` cheaper competitors, or the
       premium has left the rewards band, use the price that keeps exactly
       ``relist_rank`` competitors in front instead.
    """
    floor = view.floor
    premium = strategy.target_premium_pct
    price = add_pct(floor.global_wei, premium)
    for _ in range(MAX_PREMIUM_STEPS):
        if pct_above(price, floor.looksrare_wei) > strategy.min_premium_over_looksrare_pct:
            break
        premium += strategy.premium_step_pct
        price = add_pct(floor.global_wei, premium)

    too_shallow = view.cheaper_competitors(price) < strategy.relist_rank
    if too_shallow or premium > strategy.rewards_ceiling_pct:
        fallback = view.competitor_price_at(strategy.relist_rank + 1)
        return PriceProposal(fallback, pct_above(fallback, floor.global_wei), True)
    return PriceProposal(price, premium, False)


def decide(current: Optional[Wei], view: MarketView, strategy: Strategy) -> Decision:
    """What to do with a position's live listing, given the market right now."""
    if current is None:
        return Decision(Action.LIST, "not listed")

    floor: Floor = view.floor
    vs_global = pct_above(current, floor.global_wei)
    vs_looks = pct_above(current, floor.looksrare_wei)
    cheaper = view.cheaper_competitors(current)

    if vs_global < strategy.cancel_below_global_pct:
        return Decision(Action.CANCEL_AND_RELIST, f"{vs_global:.2f}% above the global floor")
    if vs_looks < strategy.cancel_below_looksrare_pct:
        return Decision(Action.CANCEL_AND_RELIST, f"{vs_looks:.2f}% above the LooksRare floor")
    if cheaper < strategy.cancel_rank:
        return Decision(Action.CANCEL_AND_RELIST, f"only {cheaper} cheaper listings")
    if vs_global > strategy.rewards_ceiling_pct:
        return Decision(Action.LOWER, f"{vs_global:.2f}% above the floor, outside the band")
    return Decision(Action.HOLD, f"{vs_global:.2f}% above the floor, {cheaper} cheaper listings")


def renewal_price(proposal: PriceProposal, current: Wei) -> Wei:
    """Price for renewing an expiring listing: never higher than the live one."""
    if proposal.price_wei >= current:
        return current - RENEWAL_DECREMENT_WEI
    return proposal.price_wei


def is_sharp_drop(new: Floor, old: Floor, strategy: Strategy) -> bool:
    return Decimal(new.global_wei) / Decimal(old.global_wei) < strategy.sharp_drop_ratio
