"""Market data as the pricing rules see it."""

from __future__ import annotations

from bisect import bisect_left
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

from autolister_core.money import Wei


@dataclass(frozen=True)
class Listing:
    """One active ask on the LooksRare order book."""

    price_wei: Wei
    signer: str
    token_id: str
    end_time: int

    @classmethod
    def from_api(cls, order: Mapping[str, Any]) -> Listing:
        return cls(
            price_wei=int(order["price"]),
            signer=str(order["signer"]),
            token_id=str(order["tokenId"]),
            end_time=int(order["endTime"]),
        )


@dataclass
class ListingState:
    """What the engine last instructed for an account (a cache; the order book is the truth)."""

    price_wei: Optional[Wei] = None
    expires_at: Optional[int] = None


@dataclass(frozen=True)
class Floor:
    looksrare_wei: Wei
    opensea_wei: Optional[Wei] = None

    @property
    def global_wei(self) -> Wei:
        """The cheapest price anyone can buy at, on any tracked marketplace."""
        if self.opensea_wei is None:
            return self.looksrare_wei
        return min(self.looksrare_wei, self.opensea_wei)

    def to_dict(self) -> Dict[str, Optional[int]]:
        return {"looksrare_wei": self.looksrare_wei, "opensea_wei": self.opensea_wei}


@dataclass(frozen=True)
class MarketView:
    """An order-book snapshot, sorted once so every rank query is a binary search."""

    floor: Floor
    prices: Tuple[Wei, ...]
    """Every ask, cheapest first."""
    competitor_prices: Tuple[Wei, ...]
    """Asks from wallets we don't manage, cheapest first."""

    @classmethod
    def build(cls, floor: Floor, listings: Iterable[Listing], own: frozenset[str]) -> MarketView:
        listings = tuple(listings)
        return cls(
            floor=floor,
            prices=tuple(sorted(x.price_wei for x in listings)),
            competitor_prices=tuple(
                sorted(x.price_wei for x in listings if x.signer.lower() not in own)
            ),
        )

    def cheaper_competitors(self, price: Wei) -> int:
        return bisect_left(self.competitor_prices, price)

    def competitor_price_at(self, rank: int) -> Wei:
        """Price of the ``rank``-th cheapest competing ask (1-based, clamped to the book)."""
        return _at_rank(self.competitor_prices, rank)

    def price_at(self, rank: int) -> Wei:
        """Price of the ``rank``-th cheapest ask overall (1-based, clamped to the book)."""
        return _at_rank(self.prices, rank)


def _at_rank(prices: Tuple[Wei, ...], rank: int) -> Wei:
    if not prices:
        raise ValueError("The order book is empty")
    if rank < 1:
        raise ValueError("Ranks are 1-based")
    return prices[min(rank, len(prices)) - 1]
