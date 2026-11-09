"""Money arithmetic.

Prices are integer wei everywhere. Ratios and percentages are ``Decimal``.
Floats never hold a price: binary floating point cannot represent most decimal
ETH amounts exactly, and each conversion between ETH and wei is a chance to be
off by a factor of 10^18.
"""

from __future__ import annotations

from decimal import ROUND_HALF_EVEN, Decimal

Wei = int

WEI_PER_ETH = 10**18
_WEI_PER_ETH = Decimal(WEI_PER_ETH)


def eth_to_wei(amount: Decimal | str | int) -> Wei:
    """Convert an ETH amount to wei. Floats are rejected on purpose."""
    if isinstance(amount, float):
        raise TypeError("Pass ETH amounts as str or Decimal, not float")
    return int((Decimal(amount) * _WEI_PER_ETH).to_integral_value(ROUND_HALF_EVEN))


def wei_to_eth(wei: Wei) -> Decimal:
    return Decimal(wei) / _WEI_PER_ETH


def format_eth(wei: Wei, places: int = 4) -> str:
    return f"{wei_to_eth(wei):.{places}f} ETH"


def pct_above(price: Wei, reference: Wei) -> Decimal:
    """How far ``price`` is above ``reference``, in percent (negative when below)."""
    if reference <= 0:
        raise ValueError("Reference price must be positive")
    return (Decimal(price) / Decimal(reference) - 1) * 100


def add_pct(reference: Wei, pct: Decimal) -> Wei:
    """``reference`` raised by ``pct`` percent, rounded to the nearest wei."""
    return int((Decimal(reference) * (1 + pct / 100)).to_integral_value(ROUND_HALF_EVEN))
