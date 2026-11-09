"""Fakes for every port, and builders for order books."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from decimal import Decimal
from pathlib import Path

from autolister_core.instructions import Instruction
from autolister_core.money import Wei, eth_to_wei
from autolister_engine.domain.models import Floor, Listing, MarketView

REPO = Path(__file__).resolve().parents[3]
COLLECTION = "0x34d85c9CDeB23FA97cb08333b511ac86E1C4E258"
OWN = "0x00000000000000000000000000000000000000aa"
OTHER = "0x00000000000000000000000000000000000000bb"
NOW = 1_666_000_000.0


def eth(amount: str) -> Wei:
    return eth_to_wei(amount)


def ladder(start: str, step: str, count: int) -> list[Wei]:
    return [eth_to_wei(Decimal(start) + Decimal(step) * i) for i in range(count)]


def book(
    prices: Iterable[Wei], signer: str = OTHER, end_time: int = 2_000_000_000
) -> list[Listing]:
    return [Listing(p, signer, str(i), end_time) for i, p in enumerate(prices)]


def view(listings: Sequence[Listing], opensea: Wei | None = None) -> MarketView:
    floor = Floor(min(x.price_wei for x in listings), opensea)
    return MarketView.build(floor, listings, frozenset({OWN.lower()}))


class FakeMarket:
    def __init__(
        self, listings: Sequence[Listing], rewards: bool = True, last_sale: float | None = None
    ):
        self.book = list(listings)
        self.rewards = rewards
        self.last_sale = last_sale

    def listings(self, collection: str, count: int, min_price_wei: Wei) -> list[Listing]:
        return sorted(
            (x for x in self.book if x.price_wei >= min_price_wei), key=lambda x: x.price_wei
        )[:count]

    def last_sale_time(self, collection: str) -> float | None:
        return self.last_sale

    def earns_listing_rewards(self, collection: str, top_n: int) -> bool:
        return self.rewards


class FakeFloors:
    def __init__(self, opensea: Wei | None = None) -> None:
        self.opensea = opensea

    def current(self, collection: str, listings: Sequence[Listing]) -> Floor:
        return Floor(min(x.price_wei for x in listings), self.opensea)


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[Instruction] = []

    def publish(self, instruction: Instruction) -> None:
        self.published.append(instruction)


class FakeClock:
    def __init__(self, now: float = NOW) -> None:
        self._now = now
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += seconds
