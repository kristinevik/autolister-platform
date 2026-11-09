"""The pricing rules, as worked examples."""

from decimal import Decimal

import pytest

from autolister_engine.domain import pricing
from autolister_engine.domain.models import Floor, MarketView
from autolister_engine.domain.pricing import Action, PriceProposal

from tests.fakes import OWN, book, eth, ladder, view


def test_market_view_ignores_our_own_listings():
    listings = book([eth("1.0"), eth("1.2")]) + book([eth("1.1")], signer=OWN)
    market = MarketView.build(Floor(eth("1.0")), listings, frozenset({OWN.lower()}))
    assert market.cheaper_competitors(eth("1.15")) == 1
    assert market.competitor_price_at(2) == eth("1.2")
    assert market.price_at(2) == eth("1.1")


def test_global_floor_is_the_cheapest_marketplace():
    assert Floor(eth("1.2"), eth("1.0")).global_wei == eth("1.0")
    assert Floor(eth("1.2")).global_wei == eth("1.2")


def test_emergency_floor_keeps_twenty_asks_in_front(strategy):
    assert pricing.emergency_floor(view(book(ladder("1.0", "0.01", 50))), strategy) == eth("1.20")


def test_target_premium_in_a_deep_book(strategy):
    proposal = pricing.propose_price(view(book(ladder("1.0", "0.001", 200))), strategy)
    assert proposal == PriceProposal(eth("1.07"), Decimal("7.0"), False)


def test_premium_steps_up_to_clear_the_looksrare_floor(strategy):
    # OpenSea (global floor, 1.00) is 6% under LooksRare (1.06).
    market = view(book(ladder("1.06", "0.0005", 200)), opensea=eth("1.00"))
    proposal = pricing.propose_price(market, strategy)
    assert not proposal.used_rank_fallback
    assert proposal.premium_pct > strategy.target_premium_pct


def test_rank_fallback_in_a_thin_book(strategy):
    market = view(book([eth("1.0"), eth("1.01"), eth("1.02"), *ladder("1.2", "0.01", 100)]))
    proposal = pricing.propose_price(market, strategy)
    assert proposal.used_rank_fallback
    assert market.cheaper_competitors(proposal.price_wei) == strategy.relist_rank


@pytest.mark.parametrize(
    "price, action",
    [
        (None, Action.LIST),
        ("1.02", Action.CANCEL_AND_RELIST),  # under 3% above the global floor
        ("1.15", Action.LOWER),  # over 10%: earning nothing
        ("1.07", Action.HOLD),
    ],
)
def test_decisions(strategy, price, action):
    market = view(book(ladder("1.0", "0.001", 200)))
    assert pricing.decide(eth(price) if price else None, market, strategy).action is action


def test_cancel_when_too_close_to_the_looksrare_floor(strategy):
    market = view(book(ladder("1.03", "0.0001", 200)), opensea=eth("1.00"))
    assert pricing.decide(eth("1.04"), market, strategy).action is Action.CANCEL_AND_RELIST


def test_cancel_when_too_few_listings_in_front(strategy):
    market = view(book(ladder("1.0", "0.004", 10) + ladder("1.2", "0.01", 100)))
    decision = pricing.decide(eth("1.05"), market, strategy)
    assert decision.action is Action.CANCEL_AND_RELIST
    assert "only 10 cheaper" in decision.reason


def test_renewal_never_raises_the_price():
    assert pricing.renewal_price(PriceProposal(eth("1.2"), Decimal(9), False), eth("1.1")) < eth(
        "1.1"
    )
    assert pricing.renewal_price(PriceProposal(eth("1.05"), Decimal(5), False), eth("1.1")) == eth(
        "1.05"
    )


def test_sharp_drop(strategy):
    assert pricing.is_sharp_drop(Floor(eth("0.90")), Floor(eth("1.0")), strategy)
    assert not pricing.is_sharp_drop(Floor(eth("0.97")), Floor(eth("1.0")), strategy)
