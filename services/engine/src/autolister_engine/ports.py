"""Ports: the engine's view of the outside world.

The engine depends only on these interfaces. Production wires in the adapters
under ``adapters/``; tests wire in in-memory fakes. Neither the pricing rules
nor the engine loop ever import a network library.
"""

from __future__ import annotations

import time
from typing import List, Optional, Protocol, Sequence

from autolister_core.instructions import Instruction
from autolister_core.money import Wei

from .domain.models import Floor, Listing, ListingState


class MarketData(Protocol):
    def listings(self, collection: str, count: int, min_price_wei: Wei) -> List[Listing]:
        """The ``count`` cheapest valid asks at or above ``min_price_wei``."""

    def last_sale_time(self, collection: str) -> Optional[float]:
        """Unix time of the collection's most recent sale."""

    def earns_listing_rewards(self, collection: str, top_n: int) -> bool:
        """Whether the collection is currently in the listing-rewards programme."""


class FloorSource(Protocol):
    def current(self, collection: str, listings: Sequence[Listing]) -> Floor:
        ...


class InstructionPublisher(Protocol):
    def publish(self, instruction: Instruction) -> None:
        """Seal and publish an instruction for the signer."""


class StateStore(Protocol):
    def load_floor(self) -> Optional[Floor]:
        ...

    def save_floor(self, floor: Floor) -> None:
        ...

    def load(self, account_id: str) -> ListingState:
        ...

    def save(self, account_id: str, state: ListingState) -> None:
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
