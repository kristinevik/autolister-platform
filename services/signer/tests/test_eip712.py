"""The signed bytes, pinned. If any of these fail, orders would be rejected or, worse,
mean something other than intended."""

import pytest
from eth_keys import keys
from eth_utils import keccak

from autolister_signer import eip712

from tests.fakes import COLLECTION, WALLET_1

GOLDEN_ORDER = dict(
    signer="0x1111111111111111111111111111111111111111",
    collection=COLLECTION,
    token_id="101",
    price_wei=1_070_000_000_000_000_000,
    nonce=41,
    start_time=1_666_000_000,
    end_time=1_666_259_200,
    min_percentage_to_ask=9800,
)
GOLDEN_DIGEST = "bbda44c0e85b6397732bb969c648a9e60276efff99b235e044dca8d68ed0572b"


def test_type_hash_matches_the_exchange_contract():
    # The type string exactly as declared in LooksRare's OrderTypes.sol.
    assert eip712.MAKER_ORDER_TYPEHASH == keccak(
        text="MakerOrder(bool isOrderAsk,address signer,address collection,uint256 price,"
        "uint256 tokenId,uint256 amount,address strategy,address currency,uint256 nonce,"
        "uint256 startTime,uint256 endTime,uint256 minPercentageToAsk,bytes params)"
    )


def test_known_answer():
    # Computed independently with a generic EIP-712 encoder.
    order = eip712.build_ask(**GOLDEN_ORDER)
    assert eip712.signing_digest(order).hex() == GOLDEN_DIGEST


def test_every_field_is_signed():
    order = eip712.build_ask(**GOLDEN_ORDER)
    for name, _ in eip712.MAKER_ORDER:
        if name == "params":
            continue
        changed = dict(order)
        changed[name] = not order[name] if name == "isOrderAsk" else _bump(order[name])
        assert eip712.signing_digest(changed) != eip712.signing_digest(order), name


def test_signature_recovers_to_the_wallet():
    order = eip712.build_ask(**{**GOLDEN_ORDER, "signer": WALLET_1.address})
    body = eip712.sign_ask(order, WALLET_1.key.hex())
    assert body["price"] == "1070000000000000000" and body["tokenId"] == "101"
    assert eip712.recover_signer(body) == WALLET_1.address


@pytest.mark.parametrize(
    "change", [{"price_wei": 0}, {"end_time": 1_666_000_000}, {"signer": "0x1234"}]
)
def test_invalid_orders_are_refused(change):
    with pytest.raises(ValueError):
        eip712.build_ask(**{**GOLDEN_ORDER, **change})


def test_orders_with_params_are_refused():
    order = {**eip712.build_ask(**GOLDEN_ORDER), "params": ["0x01"]}
    with pytest.raises(ValueError, match="params"):
        eip712.signing_digest(order)


def _bump(value):
    if isinstance(value, int):
        return value + 1
    return "0x" + ("1" if value[2] != "1" else "2") + value[3:]


def test_the_signature_covers_the_pinned_digest():
    """Ties the signature to ``signing_digest``, which the known-answer test pins."""
    order = eip712.build_ask(**{**GOLDEN_ORDER, "signer": WALLET_1.address})
    raw = bytes.fromhex(eip712.sign_ask(order, WALLET_1.key.hex())["signature"][2:])
    signature = keys.Signature(raw[:64] + bytes([raw[64] - 27]))
    public_key = signature.recover_public_key_from_msg_hash(eip712.signing_digest(order))
    assert public_key.to_checksum_address() == WALLET_1.address
