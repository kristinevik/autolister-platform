from pathlib import Path

import pytest
from pydantic import ValidationError

from autolister_core.accounts import Account, load_accounts

REPO = Path(__file__).resolve().parents[3]
WALLET = "0x" + "ab" * 20


def test_the_accounts_file_is_valid():
    accounts = load_accounts(REPO / "config" / "accounts.yaml")
    assert [a.id for a in accounts] == ["investor-1", "investor-2"]
    assert accounts[0].wallet_secret == "wallet-investor-1"


@pytest.mark.parametrize(
    "field, value",
    [("id", "Investor 1"), ("id", "../wallet"), ("address", "0x123"), ("address", "ab" * 21)],
)
def test_ids_and_addresses_are_validated(field, value):
    fields = {"id": "investor-1", "address": WALLET, "token_ids": ["1"], field: value}
    with pytest.raises(ValidationError):
        Account.parse_obj(fields)


@pytest.mark.parametrize(
    "second",
    [
        "{id: investor-1, address: '0x" + "cd" * 20 + "', token_ids: ['2']}",
        "{id: investor-2, address: '0x" + "AB" * 20 + "', token_ids: ['2']}",
    ],
)
def test_ids_and_wallets_must_be_unique(tmp_path, second):
    path = tmp_path / "accounts.yaml"
    path.write_text(
        f"accounts:\n  - {{id: investor-1, address: '{WALLET}', token_ids: ['1']}}\n  - {second}\n"
    )
    with pytest.raises(ValueError, match="unique|only once"):
        load_accounts(path)
