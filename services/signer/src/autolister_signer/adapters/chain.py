"""Ethereum: on-chain cancellation and ERC-721 ownership."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from eth_account import Account
from web3 import Web3
from web3.exceptions import ContractLogicError

from autolister_core.protocol import CHAIN_ID, EXCHANGE_ADDRESS

EXCHANGE_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "minNonce", "type": "uint256"}],
        "name": "cancelAllOrdersForSender",
        "outputs": [],
        "stateMutability": "nonpayable",
        "type": "function",
    },
    {
        "inputs": [{"internalType": "address", "name": "", "type": "address"}],
        "name": "userMinOrderNonce",
        "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
        "stateMutability": "view",
        "type": "function",
    },
]
OWNER_OF_ABI = [
    {
        "inputs": [{"internalType": "uint256", "name": "tokenId", "type": "uint256"}],
        "name": "ownerOf",
        "outputs": [{"internalType": "address", "name": "", "type": "address"}],
        "stateMutability": "view",
        "type": "function",
    }
]


class TransactionFailed(RuntimeError):
    pass


class EthereumChain:
    def __init__(
        self,
        web3: Web3,
        max_fee_gwei: int = 50,
        priority_fee_gwei: int = 3,
        receipt_timeout_s: int = 300,
    ) -> None:
        self._w3 = web3
        self._exchange = web3.eth.contract(
            address=Web3.toChecksumAddress(EXCHANGE_ADDRESS), abi=EXCHANGE_ABI
        )
        self._max_fee = Web3.toWei(max_fee_gwei, "gwei")
        self._priority_fee = Web3.toWei(priority_fee_gwei, "gwei")
        # Must stay below the subscription's ack deadline (600 s), or Pub/Sub would
        # redeliver the instruction while its cancellation is still being mined.
        self._receipt_timeout = receipt_timeout_s

    def build_cancel(
        self, address: str, min_nonce: int, tx_nonce: int, gas: int | None = None
    ) -> dict[str, Any]:
        """``cancelAllOrdersForSender(minNonce)``: orders below ``min_nonce`` become invalid."""
        params: dict[str, Any] = {
            "from": Web3.toChecksumAddress(address),
            "nonce": tx_nonce,
            "chainId": CHAIN_ID,
            "maxFeePerGas": self._max_fee,
            "maxPriorityFeePerGas": self._priority_fee,
        }
        if gas is not None:
            params["gas"] = gas
        # Without an explicit limit, web3 estimates gas for this exact call.
        tx: dict[str, Any] = self._exchange.functions.cancelAllOrdersForSender(
            min_nonce
        ).build_transaction(params)
        return tx

    def cancel_all_orders(self, address: str, private_key: str, min_nonce: int) -> str | None:
        if Account.from_key(private_key).address.lower() != address.lower():
            raise ValueError("The private key does not belong to this account")
        sender = Web3.toChecksumAddress(address)
        # Idempotent: if a cancellation up to this nonce is already on chain (say,
        # the signer restarted while one was being mined), there is nothing to send.
        if self._exchange.functions.userMinOrderNonce(sender).call() >= min_nonce:
            return None
        tx = self.build_cancel(sender, min_nonce, self._w3.eth.get_transaction_count(sender))
        signed = Account.sign_transaction(tx, private_key)
        tx_hash = self._w3.eth.send_raw_transaction(signed.rawTransaction)
        receipt: Mapping[str, Any] = self._w3.eth.wait_for_transaction_receipt(
            tx_hash, timeout=self._receipt_timeout
        )
        if receipt["status"] != 1:
            raise TransactionFailed(f"Cancellation reverted: {tx_hash.hex()}")
        return str(tx_hash.hex())


class EthereumInventory:
    """Which tokens a wallet still holds (ERC-721 ``ownerOf``)."""

    def __init__(self, web3: Web3) -> None:
        self._w3 = web3

    def owned(self, collection: str, address: str, token_ids: Sequence[str]) -> list[str]:
        contract = self._w3.eth.contract(
            address=Web3.toChecksumAddress(collection), abi=OWNER_OF_ABI
        )
        owner = Web3.toChecksumAddress(address)
        held = []
        for token_id in token_ids:
            try:
                if contract.functions.ownerOf(int(token_id)).call() == owner:
                    held.append(token_id)
            except ContractLogicError:
                continue  # burned or nonexistent token
        return held
