"""The signer: verify each instruction, check it again, sign, submit, acknowledge.

Delivery semantics
------------------
* An instruction that fails verification (bad MAC, expired, unknown account,
  already handled) is acknowledged and dropped, since retrying cannot make it
  valid.
* Work is retried by *not* acknowledging it. Anything that fails before an
  order reaches the exchange goes back to Pub/Sub and is redelivered; a message
  that keeps failing ends up on the dead-letter topic and raises an alert.
* Order submission itself is at-most-once. A rejected or unconfirmed order is
  logged, not retried: the engine compares the order book with what it wants
  every cycle and asks again if a listing is missing.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from autolister_core.accounts import Account
from autolister_core.guard import EmptyOrderBook, emergency_floor
from autolister_core.instructions import (
    Action,
    Instruction,
    InstructionError,
    InstructionExpired,
    unseal,
)
from autolister_core.money import format_eth

from . import eip712
from .config import SignerSettings
from .ports import (
    Chain,
    Clock,
    InstructionSource,
    Inventory,
    MarketData,
    OrderGateway,
    ReceivedMessage,
    SecretStore,
)
from .replay import ReplayGuard

log = logging.getLogger(__name__)

PULL_BATCH = 100
SUBMIT_INTERVAL_S = 1.0  # stay well inside the API's rate limits
INSTRUCTION_HMAC_KEY = "instruction-hmac-key"


@dataclass
class Plan:
    """One account's work from a batch, after applying its instructions in issue order."""

    cancel: Instruction | None = None
    listing: Instruction | None = None
    settled_by_cancel: list[Instruction] = field(default_factory=list)
    """The cancellation and everything issued before it: all done once it is mined."""
    instructions: list[Instruction] = field(default_factory=list)
    ack_ids: list[str] = field(default_factory=list)


def plan(batch: Sequence[tuple[ReceivedMessage, Instruction]]) -> dict[str, Plan]:
    """Reduce a batch to at most one cancellation and one listing per account.

    A newer listing supersedes an older one, and a cancellation discards any
    listing issued before it: ``list A, cancel, list B`` becomes "cancel, then
    list B", and ``list A, cancel`` becomes just "cancel". The sort is stable,
    so instructions issued at the same instant keep their delivery order.
    """
    plans: dict[str, Plan] = {}
    for message, instruction in sorted(batch, key=lambda pair: pair[1].issued_at):
        todo = plans.setdefault(instruction.account_id, Plan())
        todo.ack_ids.append(message.ack_id)
        todo.instructions.append(instruction)
        if instruction.action is Action.CANCEL_ALL:
            todo.cancel, todo.listing = instruction, None
            todo.settled_by_cancel = list(todo.instructions)
        else:
            todo.listing = instruction
    return plans


class Signer:
    def __init__(
        self,
        *,
        settings: SignerSettings,
        accounts: Sequence[Account],
        source: InstructionSource,
        market: MarketData,
        orders: OrderGateway,
        chain: Chain,
        inventory: Inventory,
        secrets: SecretStore,
        replay: ReplayGuard,
        clock: Clock,
    ) -> None:
        self.settings = settings
        self.accounts: Mapping[str, Account] = {a.id: a for a in accounts}
        self.source = source
        self.market = market
        self.orders = orders
        self.chain = chain
        self.inventory = inventory
        self.secrets = secrets
        self.replay = replay
        self.clock = clock
        self._hmac_key = secrets.get(INSTRUCTION_HMAC_KEY).encode()

    def run_once(self) -> int:
        """Handle one batch of instructions. Returns the number of messages received."""
        if not self.settings.signing_enabled:
            return 0  # the kill switch: consume nothing, and let queued instructions expire

        messages = self.source.pull(PULL_BATCH)
        batch: list[tuple[ReceivedMessage, Instruction]] = []
        for message in messages:
            instruction = self._verify(message)
            if instruction is None:
                self.source.ack([message.ack_id])
            else:
                batch.append((message, instruction))

        for account_id, todo in plan(batch).items():
            self._execute(self.accounts[account_id], todo)
        return len(messages)

    # ---------------------------------------------------------------- verification

    def _verify(self, message: ReceivedMessage) -> Instruction | None:
        """The instruction if it may be acted on; otherwise ``None``, with the reason logged."""
        try:
            instruction = unseal(message.data, self._hmac_key, now=self.clock.now())
        except InstructionExpired as exc:
            log.warning("Dropped instruction: %s", exc, extra={"event": "expired"})
            return None
        except InstructionError as exc:
            log.error("Rejected instruction: %s", exc, extra={"event": "rejected"})
            return None

        context = {"account": instruction.account_id, "instruction_id": instruction.instruction_id}
        if instruction.account_id not in self.accounts:
            log.error(
                "Rejected instruction for an unknown account",
                extra={"event": "rejected", **context},
            )
            return None
        if not self.replay.is_new(instruction):
            # Usually a Pub/Sub redelivery: at-least-once delivery makes these routine.
            log.info(
                "Dropped an instruction already handled or superseded",
                extra={"event": "duplicate", **context},
            )
            return None
        return instruction

    # ------------------------------------------------------------------- execution

    def _execute(self, account: Account, todo: Plan) -> None:
        try:
            if todo.cancel is not None:
                self._cancel_all(account)
                # Mined cancellations are final. Never repeat one, even if the
                # listing below fails and this batch is redelivered.
                self._record(todo.settled_by_cancel)
            if todo.listing is not None:
                self._list(account, todo.listing)
        except Exception:  # hand the batch back; other accounts carry on
            log.exception(
                "Instructions failed; returned for redelivery",
                extra={"event": "error", "account": account.id},
            )
            self.source.nack(todo.ack_ids)
            return
        self._record(todo.instructions)
        self.source.ack(todo.ack_ids)

    def _record(self, instructions: Sequence[Instruction]) -> None:
        for instruction in instructions:
            self.replay.record(instruction)

    def _cancel_all(self, account: Account) -> None:
        nonce = self.market.order_nonce(account.address)
        tx_hash = self.chain.cancel_all_orders(
            account.address, self.secrets.get(account.wallet_secret), nonce
        )
        log.info(
            "Cancelled every order below nonce %d%s",
            nonce,
            "" if tx_hash else " (already cancelled on chain)",
            extra={"event": "cancelled", "account": account.id, "tx": tx_hash},
        )

    def _list(self, account: Account, instruction: Instruction) -> None:
        assert instruction.price_wei is not None and instruction.end_time is not None  # schema
        s = self.settings
        price = instruction.price_wei
        context = {
            "account": account.id,
            "instruction_id": instruction.instruction_id,
            "price_wei": price,
        }

        now = int(self.clock.now())
        if not now < instruction.end_time <= now + s.max_listing_days * 86_400:
            log.error(
                "Rejected listing: expiry out of range", extra={"event": "rejected", **context}
            )
            return

        # The emergency stop, recomputed from the signer's own read of the public
        # order book. The engine applies the same rule, but the signer never relies on it.
        asks = self.market.cheapest_prices(
            s.collection_address, s.emergency_stop_rank + 1, s.guard_min_price_wei
        )
        try:
            guard = emergency_floor(asks, s.emergency_stop_rank)
        except EmptyOrderBook:
            log.warning(
                "Emergency stop: the order book is empty",
                extra={"event": "emergency_stop", **context},
            )
            return
        if price < guard:
            log.warning(
                "Emergency stop: refused %s, below the guard %s",
                format_eth(price),
                format_eth(guard),
                extra={"event": "emergency_stop", "guard_wei": guard, **context},
            )
            return

        held = self.inventory.owned(s.collection_address, account.address, account.token_ids)
        if not held:
            log.info(
                "Nothing to list: the wallet holds none of its tokens",
                extra={"event": "nothing_to_list", **context},
            )
            return

        private_key = self.secrets.get(account.wallet_secret)
        nonce = self.market.order_nonce(account.address)
        listed: list[str] = []
        failed: dict[str, str] = {}
        for offset, token_id in enumerate(held):
            if offset:
                self.clock.sleep(SUBMIT_INTERVAL_S)
            order = eip712.build_ask(
                signer=account.address,
                collection=s.collection_address,
                token_id=token_id,
                price_wei=price,
                nonce=nonce + offset,
                start_time=now,
                end_time=instruction.end_time,
                min_percentage_to_ask=s.min_percentage_to_ask,
            )
            accepted, reason = self.orders.submit(eip712.sign_ask(order, private_key))
            if accepted:
                listed.append(token_id)
            else:
                failed[token_id] = reason
        log.info(
            "Listed %d of %d tokens at %s",
            len(listed),
            len(held),
            format_eth(price),
            extra={"event": "listed", "listed": listed, "failed": failed, **context},
        )
