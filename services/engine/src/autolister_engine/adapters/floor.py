"""Cross-marketplace floor oracle.

The LooksRare floor comes from its own order book. The OpenSea floor comes from
two independent providers, Alchemy and NFTBank: the freshest reading wins, and
either provider failing is tolerated.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

import requests

from autolister_core.money import Wei, eth_to_wei

from ..domain.models import Floor, Listing

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class FloorReading:
    price_wei: Wei
    observed_at: float


FloorProvider = Callable[[str], FloorReading]


def alchemy(api_key: str, timeout_s: float = 15.0) -> FloorProvider:
    def fetch(collection: str) -> FloorReading:
        url = f"https://eth-mainnet.g.alchemy.com/nft/v2/{api_key}/getFloorPrice"
        response = requests.get(url, params={"contractAddress": collection}, timeout=timeout_s)
        response.raise_for_status()
        opensea = response.json()["openSea"]
        observed = datetime.fromisoformat(opensea["retrievedAt"].replace("Z", "+00:00"))
        return FloorReading(eth_to_wei(Decimal(str(opensea["floorPrice"]))), observed.timestamp())

    return fetch


def nftbank(api_key: str, timeout_s: float = 15.0) -> FloorProvider:
    def fetch(collection: str) -> FloorReading:
        url = f"https://api.nftbank.ai/estimates-v2/floor_price/{collection}"
        response = requests.get(
            url, params={"chain_id": "ETHEREUM"}, headers={"x-api-key": api_key}, timeout=timeout_s
        )
        response.raise_for_status()
        estimate = response.json()["data"][0]
        observed = datetime.strptime(estimate["estimated_at"], "%a, %d %b %Y %H:%M:%S %Z")
        prices = estimate["floor_price"]
        opensea = next((p for p in prices if p.get("marketplace") == "opensea"), prices[1])
        return FloorReading(
            eth_to_wei(Decimal(str(opensea["floor_price"]))),
            observed.replace(tzinfo=timezone.utc).timestamp(),
        )

    return fetch


class FloorOracle:
    def __init__(self, opensea_providers: Sequence[FloorProvider]) -> None:
        self._providers = tuple(opensea_providers)

    def opensea_floor(self, collection: str) -> Wei | None:
        readings: list[FloorReading] = []
        for provider in self._providers:
            try:
                readings.append(provider(collection))
            except Exception:  # one failing provider must not stop the cycle
                log.warning(
                    "Floor provider failed", exc_info=True, extra={"event": "provider_error"}
                )
        if not readings:
            return None
        return max(readings, key=lambda r: r.observed_at).price_wei

    def current(self, collection: str, listings: Sequence[Listing]) -> Floor:
        if not listings:
            raise ValueError("Cannot read the LooksRare floor from an empty order book")
        return Floor(
            looksrare_wei=min(x.price_wei for x in listings),
            opensea_wei=self.opensea_floor(collection),
        )
