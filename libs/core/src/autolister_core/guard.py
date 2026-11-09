"""The emergency stop: the one pricing rule both services enforce.

The engine applies it before publishing a listing, and the signer applies it
again, on its own read of the public order book, before signing one. Both call
this function, so the two checks cannot drift apart, yet neither relies on the
other having run it.
"""

from __future__ import annotations

from collections.abc import Iterable

from .money import Wei


class EmptyOrderBook(ValueError):
    """There are no asks to measure against, so no price can be shown to be safe."""


def emergency_floor(asks: Iterable[Wei], stop_rank: int) -> Wei:
    """The lowest price the system may list at: the ask at rank ``stop_rank + 1``.

    ``asks`` are prices from the public order book, our own included, so anyone
    can recompute the value from public data. With fewer asks than that, the
    most expensive one is used.
    """
    if stop_rank < 0:
        raise ValueError("stop_rank must not be negative")
    prices = sorted(asks)
    if not prices:
        raise EmptyOrderBook("There are no asks on the order book")
    return prices[min(stop_rank, len(prices) - 1)]
