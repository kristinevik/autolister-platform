"""Deployment settings, validated at start-up.

The signer reads the same ``config/accounts.yaml`` as the engine (its schema is
``autolister_core.accounts``) but not the strategy: the strategy says what the
engine *wants*, while the limits below say what the signer will *allow*. They
are configured separately so that no strategy change can loosen them.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseSettings


class SignerSettings(BaseSettings):
    """Read from ``AUTOLISTER_*`` environment variables, set by Terraform."""

    gcp_project: str
    instruction_subscription: str = "autolister-signer"
    accounts_file: Path = Path("config/accounts.yaml")
    replay_state_file: Path = Path("/var/lib/autolister/replay.json")
    poll_interval_s: float = 10.0

    signing_enabled: bool = True
    """The kill switch. When false the signer consumes nothing; queued instructions expire."""

    # What the signer will sign. The engine controls only the account, price and expiry.
    collection_address: str = "0x34d85c9CDeB23FA97cb08333b511ac86E1C4E258"
    min_percentage_to_ask: int = 9800
    """The least share of the price the seller must receive after fees and royalties (98%)."""
    max_listing_days: int = 30

    # The emergency stop: never list below the ask at rank ``emergency_stop_rank + 1``.
    emergency_stop_rank: int = 20
    guard_min_price_wei: int = 10**17
    """Asks under 0.1 ETH are ignored as troll listings, as the engine ignores them."""

    # Cancellation transactions (EIP-1559)
    max_fee_gwei: int = 50
    priority_fee_gwei: int = 3

    class Config:
        env_prefix = "AUTOLISTER_"
