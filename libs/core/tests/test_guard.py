import random

import pytest
from hypothesis import given
from hypothesis import strategies as st

from autolister_core.guard import EmptyOrderBook, emergency_floor
from autolister_core.money import eth_to_wei


def test_twenty_asks_stay_in_front():
    asks = [eth_to_wei("1.00") + i * eth_to_wei("0.01") for i in range(50)]
    random.Random(7).shuffle(asks)
    assert emergency_floor(asks, stop_rank=20) == eth_to_wei("1.20")


def test_a_thin_book_uses_its_most_expensive_ask():
    assert emergency_floor([3, 1, 2], stop_rank=20) == 3


def test_an_empty_book_has_no_safe_price():
    with pytest.raises(EmptyOrderBook):
        emergency_floor([], stop_rank=20)


@given(st.lists(st.integers(min_value=1, max_value=10**21), min_size=1), st.integers(0, 60))
def test_never_more_than_stop_rank_asks_below_the_guard(asks, stop_rank):
    guard = emergency_floor(asks, stop_rank)
    assert guard in asks
    assert sum(price < guard for price in asks) <= stop_rank
