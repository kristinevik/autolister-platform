"""Configuration.

* ``config/strategy.yaml``: strategy parameters, reviewed like code.
* ``config/accounts.yaml``: the investor wallets under management.
* Environment (``AUTOLISTER_*``): deployment settings, set by Terraform.

Everything is validated at start-up, so a bad value stops the service before it
can trade rather than surfacing as a mispriced listing hours later.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

import yaml
from pydantic import BaseModel, BaseSettings, root_validator


class Strategy(BaseModel):
    collection_address: str

    # Pricing
    target_premium_pct: Decimal = Decimal("7.0")
    premium_step_pct: Decimal = Decimal("0.3")
    min_premium_over_looksrare_pct: Decimal = Decimal("3.0")
    rewards_ceiling_pct: Decimal = Decimal("10.0")

    # Cancellation triggers
    cancel_below_global_pct: Decimal = Decimal("3.0")
    cancel_below_looksrare_pct: Decimal = Decimal("1.5")
    cancel_rank: int = 25
    rank_buffer: int = 5

    # Safety
    emergency_stop_rank: int = 20
    sharp_drop_ratio: Decimal = Decimal("0.95")
    settle_delay_s: int = 60
    sharp_drop_extra_delay_s: int = 60
    post_sale_cooldown_min: int = 10
    rewards_top_n: int = 5

    # Orders
    listing_duration_days: int = 3
    renew_before_expiry_min: int = 65
    listings_to_scan: int = 200
    min_price_to_scan_wei: int = 10**17

    class Config:
        frozen = True
        extra = "forbid"

    @root_validator(skip_on_failure=True)
    def _consistent(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if not 0 < values["emergency_stop_rank"] < values["cancel_rank"]:
            raise ValueError("need 0 < emergency_stop_rank < cancel_rank")
        if values["cancel_rank"] + values["rank_buffer"] >= values["listings_to_scan"]:
            raise ValueError("listings_to_scan must exceed cancel_rank + rank_buffer")
        if not (
            values["cancel_below_global_pct"]
            < values["target_premium_pct"]
            < values["rewards_ceiling_pct"]
        ):
            raise ValueError(
                "need cancel_below_global_pct < target_premium_pct < rewards_ceiling_pct"
            )
        if not Decimal(0) < values["sharp_drop_ratio"] < Decimal(1):
            raise ValueError("sharp_drop_ratio must be between 0 and 1")
        return values

    @property
    def relist_rank(self) -> int:
        return self.cancel_rank + self.rank_buffer

    @classmethod
    def from_yaml(cls, path: Path) -> Strategy:
        return cls.parse_obj(yaml.safe_load(path.read_text())["strategy"])


class EngineSettings(BaseSettings):
    """Deployment settings, read from ``AUTOLISTER_*`` environment variables."""

    gcp_project: str
    instruction_topic: str = "autolister-instructions"
    strategy_file: Path = Path("config/strategy.yaml")
    accounts_file: Path = Path("config/accounts.yaml")
    state_dir: Path = Path("/var/lib/autolister")
    interval_s: int = 60
    trading_enabled: bool = True
    """The kill switch. When false the engine observes and logs, but publishes nothing."""

    class Config:
        env_prefix = "AUTOLISTER_"
