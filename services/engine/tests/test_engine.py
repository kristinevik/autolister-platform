"""The engine cycle against fakes of every port."""

from __future__ import annotations

import pytest

from autolister_core.accounts import Account
from autolister_core.instructions import Action
from autolister_engine.adapters.state import MemoryStateStore
from autolister_engine.domain.models import Floor, Listing, ListingState
from autolister_engine.engine import Engine

from tests.fakes import (
    NOW,
    OWN,
    FakeClock,
    FakeFloors,
    FakeMarket,
    FakePublisher,
    book,
    eth,
    ladder,
)


class Rig:
    def __init__(self, strategy, accounts, market: FakeMarket, trading_enabled: bool = True):
        self.publisher = FakePublisher()
        self.clock = FakeClock()
        self.state = MemoryStateStore()
        self.engine = Engine(
            strategy=strategy,
            accounts=accounts,
            market=market,
            floors=FakeFloors(),
            publisher=self.publisher,
            state=self.state,
            clock=self.clock,
            trading_enabled=trading_enabled,
        )

    @property
    def actions(self) -> list[Action]:
        return [i.action for i in self.publisher.published]


def deep() -> list[Listing]:
    return book(ladder("1.0", "0.001", 200))


def ours(price: str, end_time: int = int(NOW) + 86_400) -> Listing:
    return Listing(eth(price), OWN, "101", end_time)


def test_lists_a_missing_position_at_the_target_premium(strategy, account):
    rig = Rig(strategy, [account], FakeMarket(deep()))
    rig.engine.run_once()
    [instruction] = rig.publisher.published
    assert instruction.action is Action.LIST
    assert instruction.price_wei == eth("1.07")
    assert instruction.end_time == int(NOW) + 3 * 86_400
    assert rig.state.load_floor() == Floor(eth("1.0"))


def test_holds_a_healthy_listing(strategy, account):
    rig = Rig(strategy, [account], FakeMarket([*deep(), ours("1.07")]))
    rig.engine.run_once()
    assert rig.publisher.published == []


def test_cancels_and_relists_when_the_floor_catches_up(strategy, account):
    rig = Rig(strategy, [account], FakeMarket([*deep(), ours("1.01")]))
    rig.engine.run_once()
    assert rig.actions == [Action.CANCEL_ALL, Action.LIST]


def test_waits_out_the_post_sale_cooldown_before_relisting(strategy, account):
    rig = Rig(strategy, [account], FakeMarket([*deep(), ours("1.01")], last_sale=NOW - 60))
    rig.engine.run_once()
    assert sum(rig.clock.sleeps) == 9 * 60
    assert rig.actions == [Action.CANCEL_ALL, Action.LIST]


def test_lowers_after_letting_competitors_settle(strategy, account):
    rig = Rig(strategy, [account], FakeMarket([*deep(), ours("1.15")]))
    rig.state.save_floor(Floor(eth("1.2")))  # the floor just fell by more than 5%
    rig.engine.run_once()
    assert rig.clock.sleeps == [60, 60]
    assert [i.price_wei for i in rig.publisher.published] == [eth("1.07")]


def test_holds_when_no_safe_lower_price_exists(strategy, account):
    gapped = book(ladder("1.0", "0.001", 28) + ladder("1.3", "0.01", 100))
    rig = Rig(strategy, [account], FakeMarket([*gapped, ours("1.12")]))
    rig.engine.run_once()
    assert rig.publisher.published == []


def test_renews_an_expiring_listing_without_raising_it(strategy, account):
    rig = Rig(strategy, [account], FakeMarket([*deep(), ours("1.06", end_time=int(NOW) + 600)]))
    rig.engine.run_once()
    [instruction] = rig.publisher.published
    assert instruction.price_wei is not None and instruction.price_wei < eth("1.06")


def test_listing_beyond_the_scanned_depth_is_taken_from_state(strategy, account):
    rig = Rig(strategy, [account], FakeMarket(deep()))
    rig.state.save(account.id, ListingState(eth("5.0"), int(NOW) + 86_400))
    rig.engine.run_once()
    assert rig.clock.sleeps == [60]  # treated as far above the band, so lowered
    assert rig.actions == [Action.LIST]


def test_pauses_outside_the_rewards_programme(strategy, account):
    rig = Rig(strategy, [account], FakeMarket(deep(), rewards=False))
    rig.engine.run_once()
    assert rig.publisher.published == []


def test_kill_switch_observes_but_publishes_nothing(strategy, account, caplog):
    rig = Rig(strategy, [account], FakeMarket(deep()), trading_enabled=False)
    rig.engine.run_once()
    assert rig.publisher.published == []
    assert any(getattr(r, "event", None) == "kill_switch" for r in caplog.records)


def test_emergency_stop_blocks_a_listing_below_the_guard(strategy, account, caplog):
    rig = Rig(strategy, [account], FakeMarket(book(ladder("1.0", "0.01", 50))))
    _, market_view = rig.engine._observe()
    rig.engine._list(account, eth("1.05"), market_view, "test")
    assert rig.publisher.published == []
    assert any(getattr(r, "event", None) == "emergency_stop" for r in caplog.records)


def test_one_failing_account_does_not_block_the_others(strategy, account, caplog):
    broken = Account(
        id="broken", address="0x00000000000000000000000000000000000000cc", token_ids=("1",)
    )
    rig = Rig(strategy, [broken, account], FakeMarket(deep()))
    original = rig.engine._manage

    def manage(acct, *args):
        if acct.id == "broken":
            raise RuntimeError("boom")
        original(acct, *args)

    rig.engine._manage = manage  # type: ignore[method-assign]
    rig.engine.run_once()
    assert [i.account_id for i in rig.publisher.published] == ["investor-1"]
    assert any(getattr(r, "event", None) == "error" for r in caplog.records)


@pytest.mark.parametrize("enabled", [True, False])
def test_kill_switch_flag_is_respected_per_instance(strategy, account, enabled):
    rig = Rig(strategy, [account], FakeMarket(deep()), trading_enabled=enabled)
    rig.engine.run_once()
    assert bool(rig.publisher.published) is enabled
