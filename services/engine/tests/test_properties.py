"""Safety invariants, checked against order books Hypothesis generates (and tries to break)."""

from decimal import Decimal

from hypothesis import assume, given
from hypothesis import strategies as st

from autolister_core.money import pct_above
from autolister_engine.config import Strategy
from autolister_engine.domain import pricing
from autolister_engine.domain.models import Floor, Listing, MarketView
from autolister_engine.domain.pricing import Action, PriceProposal

from tests.fakes import COLLECTION, OTHER, OWN

STRATEGY = Strategy(collection_address=COLLECTION)
prices = st.integers(min_value=10**16, max_value=10**21)


@st.composite
def markets(draw):
    competing = draw(st.lists(prices, min_size=STRATEGY.relist_rank + 1, max_size=220))
    ours = draw(st.lists(prices, max_size=4))
    listings = [Listing(p, OTHER, str(i), 0) for i, p in enumerate(competing)]
    listings += [Listing(p, OWN, f"own{i}", 0) for i, p in enumerate(ours)]
    looks = min(x.price_wei for x in listings)
    ratio = draw(st.none() | st.decimals(min_value="0.85", max_value="1.15", places=3))
    opensea = None if ratio is None else int(looks * ratio)
    return MarketView.build(Floor(looks, opensea), listings, frozenset({OWN.lower()}))


@given(markets())
def test_proposals_never_undercut_the_emergency_floor(market):
    assert pricing.propose_price(market, STRATEGY).price_wei >= pricing.emergency_floor(
        market, STRATEGY
    )


@given(markets(), prices)
def test_a_held_listing_is_always_safe_and_earning(market, current):
    if pricing.decide(current, market, STRATEGY).action is Action.HOLD:
        assert market.cheaper_competitors(current) >= STRATEGY.cancel_rank
        assert pct_above(current, market.floor.global_wei) <= STRATEGY.rewards_ceiling_pct


@given(prices, prices)
def test_renewals_never_raise_the_price(proposed, current):
    assume(current > pricing.RENEWAL_DECREMENT_WEI)
    assert pricing.renewal_price(PriceProposal(proposed, Decimal(0), False), current) < current
