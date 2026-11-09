"""Adapters against recorded API shapes, and the guard's agreement with the engine."""

from types import SimpleNamespace
from typing import Any, Callable

import pytest
import requests
import responses
import yaml
from eth_account import Account as Wallet
from eth_utils import function_signature_to_4byte_selector
from google.api_core.exceptions import DeadlineExceeded
from web3 import Web3
from web3.providers.base import BaseProvider

from autolister_core.protocol import EXCHANGE_ADDRESS, LOOKSRARE_API
from autolister_signer.adapters.chain import EthereumChain, EthereumInventory, TransactionFailed
from autolister_signer.adapters.looksrare import LooksRareGateway
from autolister_signer.adapters.pubsub import PubSubSource
from autolister_signer.adapters.secrets import SecretManagerStore
from autolister_signer.config import SignerSettings

from tests.fakes import COLLECTION, REPO, WALLET_1, WALLET_2

# ------------------------------------------------------------------------------ LooksRare


@responses.activate
def test_reads_the_order_nonce():
    responses.get(f"{LOOKSRARE_API}/orders/nonce", json={"success": True, "data": "41"})
    assert LooksRareGateway("key").order_nonce(WALLET_1.address) == 41
    assert responses.calls[0].request.headers["X-Looks-Api-Key"] == "key"


@responses.activate
def test_reads_the_cheapest_valid_asks():
    responses.get(
        f"{LOOKSRARE_API}/orders",
        match=[
            responses.matchers.query_param_matcher(
                {
                    "isOrderAsk": "true",
                    "collection": COLLECTION,
                    "price[min]": "100000000000000000",
                    "status[]": "VALID",
                    "sort": "PRICE_ASC",
                    "pagination[first]": "21",
                }
            )
        ],
        json={"success": True, "data": [{"price": "1000000000000000000"}, {"price": "2"}]},
    )
    assert LooksRareGateway("key").cheapest_prices(COLLECTION, 21, 10**17) == [10**18, 2]


@responses.activate
@pytest.mark.parametrize(
    "reply, expected",
    [
        ({"json": {"success": True, "data": {}}}, (True, "")),
        (
            {"status": 400, "json": {"success": False, "message": "Invalid nonce"}},
            (False, "Invalid nonce"),
        ),
        ({"status": 502, "body": "Bad gateway"}, (False, "HTTP 502")),
        ({"body": requests.ConnectionError()}, (False, "not confirmed: ConnectionError")),
    ],
)
def test_submission_reports_the_outcome_and_never_raises(reply, expected):
    responses.post(f"{LOOKSRARE_API}/orders", **reply)
    assert LooksRareGateway("key").submit({"tokenId": "1"}) == expected
    assert len(responses.calls) == 1  # never retried


# ------------------------------------------------------------------------------- Ethereum

CANCEL_SELECTOR = function_signature_to_4byte_selector("cancelAllOrdersForSender(uint256)").hex()
TX_HASH = "0x" + "ab" * 32


class FakeNode(BaseProvider):
    """A JSON-RPC endpoint with canned answers: the real web3 stack, no network."""

    def __init__(self, answers: dict[str, Any]) -> None:
        self.answers = answers
        self.requests: list[tuple[str, Any]] = []

    def make_request(self, method: str, params: Any) -> dict[str, Any]:
        self.requests.append((method, params))
        answer = self.answers[method]
        if callable(answer):
            answer = answer(params)
        if isinstance(answer, dict) and "error" in answer:
            return {"jsonrpc": "2.0", "id": 1, **answer}
        return {"jsonrpc": "2.0", "id": 1, "result": answer}

    def isConnected(self) -> bool:
        return True

    def params_of(self, method: str) -> Any:
        return next(params for name, params in self.requests if name == method)


def node_for_cancel(status: str, cancelled_below: int = 0) -> FakeNode:
    return FakeNode(
        {
            "eth_chainId": "0x1",
            "eth_call": "0x" + format(cancelled_below, "064x"),  # userMinOrderNonce
            "eth_getTransactionCount": "0x7",
            "eth_estimateGas": "0xea60",
            "eth_sendRawTransaction": TX_HASH,
            "eth_getTransactionReceipt": {
                "transactionHash": TX_HASH,
                "blockHash": "0x" + "cd" * 32,
                "blockNumber": "0xf00000",
                "status": status,
            },
        }
    )


def test_cancels_with_a_signed_eip1559_transaction():
    node = node_for_cancel(status="0x1")
    chain = EthereumChain(Web3(node), max_fee_gwei=50, priority_fee_gwei=3)

    assert chain.cancel_all_orders(WALLET_1.address, WALLET_1.key.hex(), min_nonce=41) == TX_HASH

    call = node.params_of("eth_estimateGas")[0]
    assert call["to"].lower() == EXCHANGE_ADDRESS.lower()
    assert call["data"] == "0x" + CANCEL_SELECTOR + (41).to_bytes(32, "big").hex()
    [raw] = node.params_of("eth_sendRawTransaction")
    assert Wallet.recover_transaction(raw) == WALLET_1.address


def test_a_cancellation_already_on_chain_is_not_sent_again():
    node = node_for_cancel(status="0x1", cancelled_below=41)
    chain = EthereumChain(Web3(node))
    assert chain.cancel_all_orders(WALLET_1.address, WALLET_1.key.hex(), min_nonce=41) is None
    sent = {method for method, _ in node.requests}
    assert not sent & {"eth_getTransactionCount", "eth_estimateGas", "eth_sendRawTransaction"}


def test_a_reverted_cancellation_raises():
    chain = EthereumChain(Web3(node_for_cancel(status="0x0")))
    with pytest.raises(TransactionFailed):
        chain.cancel_all_orders(WALLET_1.address, WALLET_1.key.hex(), min_nonce=41)


def test_builds_the_cancellation_offline():
    chain = EthereumChain(Web3(), max_fee_gwei=50, priority_fee_gwei=3)  # no provider: no RPC
    tx = chain.build_cancel(WALLET_1.address, min_nonce=41, tx_nonce=7, gas=60_000)

    assert tx["to"] == EXCHANGE_ADDRESS
    assert tx["data"] == "0x" + CANCEL_SELECTOR + (41).to_bytes(32, "big").hex()
    assert (tx["nonce"], tx["chainId"], tx["gas"], tx["value"]) == (7, 1, 60_000, 0)
    assert tx["maxFeePerGas"] == 50 * 10**9 and tx["maxPriorityFeePerGas"] == 3 * 10**9


def test_refuses_a_key_that_does_not_belong_to_the_account():
    chain = EthereumChain(Web3())
    with pytest.raises(ValueError, match="does not belong"):
        chain.cancel_all_orders(WALLET_2.address, WALLET_1.key.hex(), min_nonce=41)


def owner_of(owners: dict[int, str]) -> Callable[[Any], Any]:
    def answer(params: Any) -> Any:
        token_id = int(params[0]["data"][-64:], 16)
        if token_id not in owners:
            return {"error": {"code": -32000, "message": "execution reverted"}}
        return "0x" + "00" * 12 + owners[token_id][2:].lower()

    return answer


def test_inventory_keeps_only_tokens_the_wallet_still_owns():
    node = FakeNode(
        {
            "eth_chainId": "0x1",
            "eth_call": owner_of({101: WALLET_1.address, 102: WALLET_2.address}),
        }
    )
    inventory = EthereumInventory(Web3(node))
    # 102 was sold; 103 was burned, so ownerOf reverts.
    assert inventory.owned(COLLECTION, WALLET_1.address, ["101", "102", "103"]) == ["101"]


# -------------------------------------------------------------------------------- Pub/Sub


class FakeSubscriber:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.calls = response, error, []

    def subscription_path(self, project, subscription):
        return f"projects/{project}/subscriptions/{subscription}"

    def pull(self, request, timeout):
        self.calls.append(("pull", request))
        if self.error:
            raise self.error
        return self.response

    def acknowledge(self, request):
        self.calls.append(("ack", request))

    def modify_ack_deadline(self, request):
        self.calls.append(("nack", request))


def test_pulls_acks_and_nacks():
    message = SimpleNamespace(ack_id="a1", message=SimpleNamespace(data=b"{}"))
    client = FakeSubscriber(SimpleNamespace(received_messages=[message]))
    source = PubSubSource("proj", "autolister-signer", client=client)

    assert [(m.ack_id, m.data) for m in source.pull(10)] == [("a1", b"{}")]
    source.ack(["a1"])
    source.nack(["a2"])
    source.ack([])  # nothing to send

    path = "projects/proj/subscriptions/autolister-signer"
    assert client.calls == [
        ("pull", {"subscription": path, "max_messages": 10}),
        ("ack", {"subscription": path, "ack_ids": ["a1"]}),
        ("nack", {"subscription": path, "ack_ids": ["a2"], "ack_deadline_seconds": 0}),
    ]


def test_an_empty_pull_is_not_an_error():
    source = PubSubSource("proj", "sub", client=FakeSubscriber(error=DeadlineExceeded("idle")))
    assert source.pull(10) == []


def test_reads_the_latest_version_of_a_secret():
    requests_made = []

    def access_secret_version(request):
        requests_made.append(request)
        return SimpleNamespace(payload=SimpleNamespace(data=b"s3cret\n"))  # pasted with a newline

    client = SimpleNamespace(access_secret_version=access_secret_version)
    assert SecretManagerStore("proj", client=client).get("wallet-investor-1") == "s3cret"
    assert requests_made == [{"name": "projects/proj/secrets/wallet-investor-1/versions/latest"}]


# ------------------------------------------------------------------------- configuration


def test_the_signer_enforces_the_same_guard_as_the_engine():
    """The two services are configured separately; their defaults must still agree."""
    strategy = yaml.safe_load((REPO / "config" / "strategy.yaml").read_text())["strategy"]
    settings = SignerSettings(gcp_project="test")
    assert settings.emergency_stop_rank == strategy["emergency_stop_rank"]
    assert settings.guard_min_price_wei == strategy["min_price_to_scan_wei"]
    assert settings.collection_address == strategy["collection_address"]
