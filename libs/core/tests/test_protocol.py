import re

from autolister_core import protocol

ADDRESS = re.compile(r"^0x[0-9a-fA-F]{40}$")


def test_contract_addresses_are_well_formed():
    for address in (
        protocol.EXCHANGE_ADDRESS,
        protocol.STRATEGY_FIXED_PRICE,
        protocol.WETH_ADDRESS,
    ):
        assert ADDRESS.match(address)


def test_mainnet():
    assert protocol.CHAIN_ID == 1
    assert protocol.LOOKSRARE_API.startswith("https://")
