"""The accounts file: the investor wallets under management.

Both services read the same ``config/accounts.yaml``, so its schema lives here.
Private keys are never in the file: the signer reads each wallet's key from
Secret Manager, under the name ``wallet-<account id>``.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Tuple

import yaml
from pydantic import BaseModel, validator

_ACCOUNT_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")
_ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


class Account(BaseModel):
    """An investor wallet and the tokens in it that the system manages."""

    id: str
    address: str
    token_ids: Tuple[str, ...]

    class Config:
        frozen = True
        extra = "forbid"

    @validator("id")
    def _is_slug(cls, value: str) -> str:
        # The id names the wallet's secret and is the account's Pub/Sub ordering key.
        if not _ACCOUNT_ID.match(value):
            raise ValueError("use lowercase letters, digits and hyphens")
        return value

    @validator("address")
    def _is_address(cls, value: str) -> str:
        if not _ADDRESS.match(value):
            raise ValueError("not an Ethereum address")
        return value

    @property
    def wallet_secret(self) -> str:
        """The Secret Manager secret that holds this wallet's private key."""
        return f"wallet-{self.id}"


def load_accounts(path: Path) -> Tuple[Account, ...]:
    accounts = tuple(Account.parse_obj(a) for a in yaml.safe_load(path.read_text())["accounts"])
    if len({a.id for a in accounts}) != len(accounts):
        raise ValueError("account ids must be unique")
    if len({a.address.lower() for a in accounts}) != len(accounts):
        raise ValueError("each wallet may appear only once")
    return accounts
