"""Engine state.

The order book is the source of truth for what is listed. This state is a
cache of the few things the book cannot show: the previous floor (for sharp-drop
detection) and listings priced beyond the scanned depth.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from pathlib import Path
from typing import Any

from ..domain.models import Floor, ListingState


class JsonStateStore:
    """JSON files on the VM's persistent disk, written atomically (write, then rename)."""

    def __init__(self, directory: Path) -> None:
        self._dir = directory
        (self._dir / "accounts").mkdir(parents=True, exist_ok=True)

    def load_floor(self) -> Floor | None:
        data = self._read(self._dir / "floor.json")
        return Floor(**data) if data else None

    def save_floor(self, floor: Floor) -> None:
        self._write(self._dir / "floor.json", floor.to_dict())

    def load(self, account_id: str) -> ListingState:
        data = self._read(self._dir / "accounts" / f"{account_id}.json")
        return ListingState(**data) if data else ListingState()

    def save(self, account_id: str, state: ListingState) -> None:
        self._write(self._dir / "accounts" / f"{account_id}.json", asdict(state))

    @staticmethod
    def _read(path: Path) -> dict[str, Any] | None:
        try:
            data: dict[str, Any] = json.loads(path.read_text())
        except FileNotFoundError:
            return None
        return data

    @staticmethod
    def _write(path: Path, data: dict[str, Any]) -> None:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        os.replace(tmp, path)


class MemoryStateStore:
    def __init__(self) -> None:
        self._floor: Floor | None = None
        self._accounts: dict[str, ListingState] = {}

    def load_floor(self) -> Floor | None:
        return self._floor

    def save_floor(self, floor: Floor) -> None:
        self._floor = floor

    def load(self, account_id: str) -> ListingState:
        state = self._accounts.get(account_id)
        return ListingState(state.price_wei, state.expires_at) if state else ListingState()

    def save(self, account_id: str, state: ListingState) -> None:
        self._accounts[account_id] = ListingState(state.price_wei, state.expires_at)
