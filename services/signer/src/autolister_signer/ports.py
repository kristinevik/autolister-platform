"""Ports: the signer's view of the outside world.

The signer depends only on these interfaces; ``adapters/`` implements them
against Pub/Sub, the LooksRare API, Ethereum and Secret Manager, and the tests
implement them in memory.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from autolister_core.money import Wei


@dataclass(frozen=True)
class ReceivedMessage:
    ack_id: str
    data: bytes


class InstructionSource(Protocol):
    def pull(self, max_messages: int) -> list[ReceivedMessage]:
        ...

    def ack(self, ack_ids: Sequence[str]) -> None:
        """Mark messages as handled, so they are never delivered again."""

    def nack(self, ack_ids: Sequence[str]) -> None:
        """Hand messages back for redelivery (and, after repeated failures, dead-lettering)."""


class MarketData(Protocol):
    def order_nonce(self, address: str) -> int:
        """The next order nonce the exchange will accept from ``address``."""

    def cheapest_prices(self, collection: str, count: int, min_price_wei: Wei) -> list[Wei]:
        """Prices of the ``count`` cheapest valid asks at or above ``min_price_wei``."""


class OrderGateway(Protocol):
    def submit(self, body: dict[str, Any]) -> tuple[bool, str]:
        """Submit a signed order: ``(True, "")`` if accepted, else ``(False, reason)``.

        Never raises for transport errors: an order whose fate is unknown is
        reported as not accepted, and is not retried.
        """


class Chain(Protocol):
    def cancel_all_orders(self, address: str, private_key: str, min_nonce: int) -> str | None:
        """Invalidate every order below ``min_nonce`` on chain.

        Returns the transaction hash, or ``None`` if those orders already are invalid.
        """


class Inventory(Protocol):
    def owned(self, collection: str, address: str, token_ids: Sequence[str]) -> list[str]:
        """The subset of ``token_ids`` that ``address`` still owns."""


class SecretStore(Protocol):
    def get(self, name: str) -> str:
        ...


class Clock(Protocol):
    def now(self) -> float:
        ...

    def sleep(self, seconds: float) -> None:
        ...


class SystemClock:
    def now(self) -> float:
        return time.time()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)
