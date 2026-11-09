"""LooksRare API: nonces, the public order book, and order submission."""

from __future__ import annotations

from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autolister_core.money import Wei
from autolister_core.protocol import LOOKSRARE_API


class LooksRareGateway:
    def __init__(
        self, api_key: str, base_url: str = LOOKSRARE_API, timeout_s: float = 15.0
    ) -> None:
        self._base_url = base_url
        self._timeout = timeout_s
        self._session = requests.Session()
        retry = Retry(
            total=4,
            backoff_factor=0.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),  # reads only: see submit()
        )
        self._session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session.headers.update({"Accept": "application/json", "X-Looks-Api-Key": api_key})

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        response = self._session.get(
            f"{self._base_url}{path}", params=params, timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()["data"]

    def order_nonce(self, address: str) -> int:
        return int(self._get("/orders/nonce", {"address": address}))

    def cheapest_prices(self, collection: str, count: int, min_price_wei: Wei) -> list[Wei]:
        orders = self._get(
            "/orders",
            {
                "isOrderAsk": "true",
                "collection": collection,
                "price[min]": str(min_price_wei),
                "status[]": "VALID",
                "sort": "PRICE_ASC",
                "pagination[first]": count,
            },
        )
        return [int(order["price"]) for order in orders]

    def submit(self, body: dict[str, Any]) -> tuple[bool, str]:
        """POST a signed order. Never retried: a second attempt could list the token twice."""
        try:
            response = self._session.post(
                f"{self._base_url}/orders", json=body, timeout=self._timeout
            )
        except requests.RequestException as exc:
            return False, f"not confirmed: {type(exc).__name__}"
        try:
            result = response.json()
        except ValueError:
            result = {}
        if response.ok and result.get("success"):
            return True, ""
        return False, str(result.get("message") or f"HTTP {response.status_code}")
