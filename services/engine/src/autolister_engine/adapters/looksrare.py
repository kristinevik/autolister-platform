"""LooksRare REST API (v1) client."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from autolister_core.money import Wei
from autolister_core.protocol import LOOKSRARE_API

from ..domain.models import Listing

PAGE_SIZE = 150
"""The orders endpoint returns at most 150 orders per page."""


def _session() -> requests.Session:
    session = requests.Session()
    retry = Retry(
        total=4,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["Accept"] = "application/json"
    return session


class LooksRareClient:
    def __init__(self, base_url: str = LOOKSRARE_API, timeout_s: float = 15.0) -> None:
        self._base_url = base_url
        self._timeout = timeout_s
        self._session = _session()

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        response = self._session.get(
            f"{self._base_url}{path}", params=params, timeout=self._timeout
        )
        response.raise_for_status()
        return response.json()["data"]

    def listings(self, collection: str, count: int, min_price_wei: Wei) -> list[Listing]:
        """Cheapest valid asks first, following the API's pagination cursor."""
        listings: list[Listing] = []
        cursor: str | None = None
        while len(listings) < count:
            page_size = min(PAGE_SIZE, count - len(listings))
            params: dict[str, Any] = {
                "isOrderAsk": "true",
                "collection": collection,
                "price[min]": str(min_price_wei),
                "status[]": "VALID",
                "sort": "PRICE_ASC",
                "pagination[first]": page_size,
            }
            if cursor:
                params["pagination[cursor]"] = cursor
            page = self._get("/orders", params)
            listings.extend(Listing.from_api(order) for order in page)
            if len(page) < page_size:
                break
            cursor = page[-1]["hash"]
        return listings

    def last_sale_time(self, collection: str) -> float | None:
        events = self._get(
            "/events", {"collection": collection, "type": "SALE", "pagination[first]": 1}
        )
        if not events:
            return None
        created = datetime.fromisoformat(events[0]["createdAt"].replace("Z", "+00:00"))
        return created.timestamp()

    def earns_listing_rewards(self, collection: str, top_n: int) -> bool:
        collections = self._get("/collections/listing-rewards", {})
        eligible = {item["collection"]["address"].lower() for item in collections[:top_n]}
        return collection.lower() in eligible
