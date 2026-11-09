"""Fixtures: a signer wired to the fakes in ``tests/fakes.py``."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

import pytest

from autolister_signer.config import SignerSettings
from autolister_signer.replay import ReplayGuard
from autolister_signer.signer import INSTRUCTION_HMAC_KEY, Signer

from tests.fakes import (
    ACCOUNTS,
    HMAC_KEY,
    WALLET_1,
    WALLET_2,
    FakeChain,
    FakeClock,
    FakeInventory,
    FakeMarket,
    FakeOrders,
    FakeSecrets,
    FakeSource,
    World,
    ladder,
)


@pytest.fixture
def make_world(tmp_path: Path) -> Callable[..., World]:
    """A signer wired to fakes. The order book is 1.00, 1.01, ... ETH: the guard is 1.20."""

    def make(**settings: Any) -> World:
        world = World(
            signer=None,  # type: ignore[arg-type]
            source=FakeSource(),
            market=FakeMarket(ladder("1.00", "0.01", 60)),
            orders=FakeOrders(),
            chain=FakeChain(),
            inventory=FakeInventory(),
            clock=FakeClock(),
        )
        world.signer = Signer(
            settings=SignerSettings(gcp_project="test", **settings),
            accounts=ACCOUNTS,
            source=world.source,
            market=world.market,
            orders=world.orders,
            chain=world.chain,
            inventory=world.inventory,
            secrets=FakeSecrets(
                {
                    INSTRUCTION_HMAC_KEY: HMAC_KEY,
                    "wallet-investor-1": WALLET_1.key.hex(),
                    "wallet-investor-2": WALLET_2.key.hex(),
                }
            ),
            replay=ReplayGuard(tmp_path / "replay.json"),
            clock=world.clock,
        )
        return world

    return make


@pytest.fixture
def world(make_world: Callable[..., World]) -> World:
    return make_world()
