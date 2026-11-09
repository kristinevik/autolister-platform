"""Fakes for every port, and builders for instructions and order books."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from eth_account import Account as Wallet

from autolister_core.accounts import Account
from autolister_core.instructions import Action, Instruction, seal
from autolister_core.money import Wei, eth_to_wei
from autolister_signer.ports import ReceivedMessage
from autolister_signer.signer import Signer

REPO = Path(__file__).resolve().parents[3]
COLLECTION = "0x34d85c9CDeB23FA97cb08333b511ac86E1C4E258"
NOW = 1_666_000_000.0
HMAC_KEY = "test-hmac-key"
WALLET_1 = Wallet.from_key("0x" + "11" * 32)
WALLET_2 = Wallet.from_key("0x" + "22" * 32)


def eth(amount: str) -> Wei:
    return eth_to_wei(amount)


def ladder(start: str, step: str, count: int) -> list[Wei]:
    return [eth_to_wei(Decimal(start) + Decimal(step) * i) for i in range(count)]


def listing(
    account_id: str = "investor-1", price: str = "1.30", at: float = NOW, days: int = 3
) -> Instruction:
    return Instruction(
        action=Action.LIST,
        account_id=account_id,
        issued_at=at,
        price_wei=eth(price),
        end_time=int(at) + days * 86_400,
    )


def cancel(account_id: str = "investor-1", at: float = NOW) -> Instruction:
    return Instruction(action=Action.CANCEL_ALL, account_id=account_id, issued_at=at)


def events(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.event for r in caplog.records if hasattr(r, "event")]


def last(caplog: pytest.LogCaptureFixture, event: str) -> Any:
    return [r for r in caplog.records if getattr(r, "event", None) == event][-1]


class FakeSource:
    """An in-memory subscription. Nacked messages come back on the next pull."""

    def __init__(self) -> None:
        self.queue: list[ReceivedMessage] = []
        self.outstanding: dict[str, ReceivedMessage] = {}
        self.acked: list[str] = []
        self.nacked: list[str] = []
        self.pulls = 0
        self._sent = 0

    def send(self, *instructions: Instruction, key: str = HMAC_KEY) -> None:
        for instruction in instructions:
            self.send_raw(seal(instruction, key.encode()))

    def send_raw(self, data: bytes) -> None:
        self._sent += 1
        self.queue.append(ReceivedMessage(f"ack-{self._sent}", data))

    def pull(self, max_messages: int) -> list[ReceivedMessage]:
        self.pulls += 1
        batch, self.queue = self.queue[:max_messages], self.queue[max_messages:]
        self.outstanding.update({m.ack_id: m for m in batch})
        return batch

    def ack(self, ack_ids: Sequence[str]) -> None:
        for ack_id in ack_ids:
            self.outstanding.pop(ack_id)
            self.acked.append(ack_id)

    def nack(self, ack_ids: Sequence[str]) -> None:
        for ack_id in ack_ids:
            self.queue.append(self.outstanding.pop(ack_id))
            self.nacked.append(ack_id)


class FakeMarket:
    def __init__(self, asks: Sequence[Wei], nonce: int = 41) -> None:
        self.asks = list(asks)
        self.nonce = nonce
        self.unavailable = False

    def order_nonce(self, address: str) -> int:
        return self.nonce

    def cheapest_prices(self, collection: str, count: int, min_price_wei: Wei) -> list[Wei]:
        if self.unavailable:
            raise ConnectionError("order book unavailable")
        return sorted(p for p in self.asks if p >= min_price_wei)[:count]


class FakeOrders:
    def __init__(self) -> None:
        self.submitted: list[dict[str, Any]] = []
        self.reject: dict[str, str] = {}

    def submit(self, body: dict[str, Any]) -> tuple[bool, str]:
        self.submitted.append(body)
        reason = self.reject.get(body["tokenId"])
        return (False, reason) if reason else (True, "")


class FakeChain:
    def __init__(self) -> None:
        self.cancels: list[tuple[str, int]] = []
        self.failing = False

    def cancel_all_orders(self, address: str, private_key: str, min_nonce: int) -> str | None:
        if self.failing:
            raise ConnectionError("RPC unavailable")
        assert Wallet.from_key(private_key).address == address
        self.cancels.append((address, min_nonce))
        return "0x" + "ab" * 32


class FakeInventory:
    def __init__(self) -> None:
        self.sold: set[str] = set()

    def owned(self, collection: str, address: str, token_ids: Sequence[str]) -> list[str]:
        return [t for t in token_ids if t not in self.sold]


class FakeSecrets:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values

    def get(self, name: str) -> str:
        return self.values[name]


class FakeClock:
    def __init__(self, now: float = NOW) -> None:
        self._now = now
        self.sleeps: list[float] = []

    def now(self) -> float:
        return self._now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self._now += seconds


ACCOUNTS = (
    Account(id="investor-1", address=WALLET_1.address, token_ids=("101", "102")),
    Account(id="investor-2", address=WALLET_2.address, token_ids=("201",)),
)


@dataclass
class World:
    signer: Signer
    source: FakeSource
    market: FakeMarket
    orders: FakeOrders
    chain: FakeChain
    inventory: FakeInventory
    clock: FakeClock

    def prices(self) -> set[str]:
        return {body["price"] for body in self.orders.submitted}

    def tokens(self) -> list[str]:
        return [body["tokenId"] for body in self.orders.submitted]
