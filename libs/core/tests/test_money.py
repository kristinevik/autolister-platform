from decimal import Decimal

import pytest

from autolister_core.money import add_pct, eth_to_wei, format_eth, pct_above, wei_to_eth


def test_conversions_are_exact():
    assert eth_to_wei("1.5") == 1_500_000_000_000_000_000
    assert eth_to_wei(Decimal("0.000000000000000001")) == 1
    assert wei_to_eth(eth_to_wei("2.25")) == Decimal("2.25")
    assert format_eth(eth_to_wei("1.23456")) == "1.2346 ETH"


def test_floats_are_rejected():
    with pytest.raises(TypeError):
        eth_to_wei(0.1)  # type: ignore[arg-type]


def test_percentages():
    assert pct_above(eth_to_wei("1.07"), eth_to_wei("1")) == Decimal("7")
    assert add_pct(eth_to_wei("1"), Decimal("7")) == eth_to_wei("1.07")
    with pytest.raises(ValueError, match="positive"):
        pct_above(1, 0)
