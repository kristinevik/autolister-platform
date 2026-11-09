"""Architecture checks: the signer can list and cancel, and nothing else.

The signer holds the keys, so what it is *able* to do bounds what an attacker
who controls its inputs can do. These tests fail the build if it learns to do
more.
"""

from pathlib import Path

from autolister_signer.adapters import chain

SOURCE = "\n".join(
    path.read_text() for path in (Path(__file__).resolve().parents[1] / "src").rglob("*.py")
)


def test_the_signer_knows_one_contract_function_that_writes():
    functions = {entry["name"]: entry for entry in chain.EXCHANGE_ABI + chain.OWNER_OF_ABI}
    writes = {name for name, entry in functions.items() if entry["stateMutability"] != "view"}
    assert set(functions) == {"cancelAllOrdersForSender", "userMinOrderNonce", "ownerOf"}
    assert writes == {"cancelAllOrdersForSender"}


def test_the_only_transaction_it_sends_is_the_cancellation():
    assert SOURCE.count("send_raw_transaction") == 1  # in EthereumChain.cancel_all_orders
    for capability in (
        "send_transaction(",
        "transferFrom",
        "safeTransferFrom",
        "setApprovalForAll",
    ):
        assert capability not in SOURCE
