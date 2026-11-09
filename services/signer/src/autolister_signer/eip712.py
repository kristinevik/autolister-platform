"""LooksRare maker orders: construction and EIP-712 signing.

``MAKER_ORDER`` mirrors the ``MakerOrder`` struct in the exchange contract
(``OrderTypes.sol``), and both the type hash and the encoding are derived from
it, so they cannot disagree. Building the digest directly, rather than through
a generic typed-data encoder, keeps the signed bytes explicit; a known-answer
test (``tests/test_eip712.py``) pins them.

In EIP-191 terms, an EIP-712 signature is a version ``0x01`` message whose
header is the domain separator and whose body is the struct hash, which is how
``signable`` hands it to ``eth_account``.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import eth_abi
from eth_account import Account
from eth_account.messages import SignableMessage
from eth_utils import keccak, to_checksum_address

from autolister_core.money import Wei
from autolister_core.protocol import CHAIN_ID, EXCHANGE_ADDRESS, STRATEGY_FIXED_PRICE, WETH_ADDRESS


def abi_encode(types: Sequence[str], values: Sequence[Any]) -> bytes:
    """``eth_abi.encode``, typed: eth-abi 2.2 does not annotate it."""
    return bytes(eth_abi.encode(types, values))  # type: ignore[no-untyped-call]


MAKER_ORDER: tuple[tuple[str, str], ...] = (
    ("isOrderAsk", "bool"),
    ("signer", "address"),
    ("collection", "address"),
    ("price", "uint256"),
    ("tokenId", "uint256"),
    ("amount", "uint256"),
    ("strategy", "address"),
    ("currency", "address"),
    ("nonce", "uint256"),
    ("startTime", "uint256"),
    ("endTime", "uint256"),
    ("minPercentageToAsk", "uint256"),
    ("params", "bytes"),
)
MAKER_ORDER_TYPEHASH = keccak(
    text="MakerOrder(" + ",".join(f"{kind} {name}" for name, kind in MAKER_ORDER) + ")"
)
DOMAIN_SEPARATOR = keccak(
    abi_encode(
        ["bytes32", "bytes32", "bytes32", "uint256", "address"],
        [
            keccak(
                text="EIP712Domain(string name,string version,uint256 chainId,"
                "address verifyingContract)"
            ),
            keccak(text="LooksRareExchange"),
            keccak(text="1"),
            CHAIN_ID,
            to_checksum_address(EXCHANGE_ADDRESS),
        ],
    )
)


def build_ask(
    *,
    signer: str,
    collection: str,
    token_id: str,
    price_wei: Wei,
    nonce: int,
    start_time: int,
    end_time: int,
    min_percentage_to_ask: int,
) -> dict[str, Any]:
    """A fixed-price sell order for one token, settled in WETH."""
    if price_wei <= 0:
        raise ValueError("price must be positive")
    if end_time <= start_time:
        raise ValueError("end_time must be after start_time")
    return {
        "isOrderAsk": True,
        "signer": to_checksum_address(signer),
        "collection": to_checksum_address(collection),
        "price": price_wei,
        "tokenId": int(token_id),
        "amount": 1,
        "strategy": to_checksum_address(STRATEGY_FIXED_PRICE),
        "currency": to_checksum_address(WETH_ADDRESS),
        "nonce": nonce,
        "startTime": start_time,
        "endTime": end_time,
        "minPercentageToAsk": min_percentage_to_ask,
        "params": [],
    }


def _field(kind: str, value: Any) -> tuple[str, Any]:
    """One struct field as EIP-712 encodes it: dynamic ``bytes`` become their keccak hash."""
    if kind == "bytes":
        if value:
            raise ValueError("Only orders without extra params are supported")
        return "bytes32", keccak(b"")
    if kind == "address":
        return kind, to_checksum_address(value)
    if kind == "bool":
        return kind, bool(value)
    return kind, int(value)


def order_hash(order: dict[str, Any]) -> bytes:
    """The EIP-712 struct hash of a maker order (``OrderTypes.hash`` in the contract)."""
    fields = [_field(kind, order[name]) for name, kind in MAKER_ORDER]
    return keccak(
        abi_encode(
            ["bytes32"] + [kind for kind, _ in fields],
            [MAKER_ORDER_TYPEHASH] + [value for _, value in fields],
        )
    )


def signable(order: dict[str, Any]) -> SignableMessage:
    return SignableMessage(version=b"\x01", header=DOMAIN_SEPARATOR, body=order_hash(order))


def signing_digest(order: dict[str, Any]) -> bytes:
    """What the wallet signs: ``keccak256(0x1901 ‖ domain separator ‖ order hash)``."""
    return keccak(b"\x19\x01" + DOMAIN_SEPARATOR + order_hash(order))


def sign_ask(order: dict[str, Any], private_key: str) -> dict[str, Any]:
    """The API request body: the order and its signature, with big numbers as strings."""
    signature = Account.sign_message(signable(order), private_key).signature.hex()
    return {
        **order,
        "price": str(order["price"]),
        "tokenId": str(order["tokenId"]),
        "signature": signature,
    }


def recover_signer(body: dict[str, Any]) -> str:
    """The address that produced ``body["signature"]``: what the exchange checks."""
    return str(Account.recover_message(signable(body), signature=body["signature"]))
