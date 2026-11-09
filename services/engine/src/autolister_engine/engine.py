"""The engine cycle: observe the market, decide, publish instructions."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed

from autolister_core.accounts import Account
from autolister_core.instructions import Action as InstructionAction
from autolister_core.instructions import Instruction
from autolister_core.money import Wei, format_eth

from .config import Strategy
from .domain import pricing
from .domain.models import Floor, Listing, ListingState, MarketView
from .domain.pricing import Action
from .ports import Clock, FloorSource, InstructionPublisher, MarketData, StateStore

log = logging.getLogger(__name__)

MAX_COOLDOWN_WAIT_S = 30 * 60
COOLDOWN_POLL_S = 30.0


class Engine:
    def __init__(
        self,
        *,
        strategy: Strategy,
        accounts: Sequence[Account],
        market: MarketData,
        floors: FloorSource,
        publisher: InstructionPublisher,
        state: StateStore,
        clock: Clock,
        trading_enabled: bool = True,
    ) -> None:
        self.strategy = strategy
        self.accounts = tuple(accounts)
        self.market = market
        self.floors = floors
        self.publisher = publisher
        self.state = state
        self.clock = clock
        self.trading_enabled = trading_enabled
        self._own = frozenset(a.address.lower() for a in self.accounts)

    def run_once(self) -> None:
        s = self.strategy
        if not self.market.earns_listing_rewards(s.collection_address, s.rewards_top_n):
            log.info("Collection is not earning listing rewards; paused", extra={"event": "paused"})
            return

        listings, view = self._observe()
        previous = self.state.load_floor() or view.floor
        log.info(
            "Market observed",
            extra={
                "event": "market",
                "global_floor_wei": view.floor.global_wei,
                "looksrare_floor_wei": view.floor.looksrare_wei,
                "listings": len(listings),
            },
        )

        # Accounts are independent, and handling one can mean waiting for the market
        # to settle, so each is managed on its own thread.
        with ThreadPoolExecutor(max_workers=max(1, len(self.accounts))) as pool:
            futures = {
                pool.submit(self._manage, account, listings, view, previous): account
                for account in self.accounts
            }
            for future in as_completed(futures):
                account = futures[future]
                try:
                    future.result()
                except Exception:  # one account must not block the others
                    log.exception(
                        "Failed to manage account", extra={"event": "error", "account": account.id}
                    )
        self.state.save_floor(view.floor)

    # ------------------------------------------------------------- per account

    def _manage(
        self, account: Account, listings: Sequence[Listing], view: MarketView, previous: Floor
    ) -> None:
        current, expires_at = self._live_listing(account, listings)
        decision = pricing.decide(current, view, self.strategy)
        log.info(
            decision.reason,
            extra={"event": "decision", "account": account.id, "action": decision.action.value},
        )

        if decision.action is Action.HOLD:
            assert current is not None
            renew_by = self.clock.now() + self.strategy.renew_before_expiry_min * 60
            if expires_at is not None and expires_at <= renew_by:
                proposal = pricing.propose_price(view, self.strategy)
                self._list(account, pricing.renewal_price(proposal, current), view, "renewal")
            return

        if decision.action is Action.LIST:
            self._list(account, pricing.propose_price(view, self.strategy).price_wei, view, "new")
            return

        if decision.action is Action.CANCEL_AND_RELIST:
            self._publish(
                Instruction(
                    action=InstructionAction.CANCEL_ALL,
                    account_id=account.id,
                    issued_at=self.clock.now(),
                )
            )
            self.state.save(account.id, ListingState())
            self._wait_for_sale_cooldown()
            _, view = self._observe()
            self._list(
                account, pricing.propose_price(view, self.strategy).price_wei, view, "relist"
            )
            return

        # Action.LOWER: let competing bots reprice first, then follow the floor down.
        assert current is not None
        if pricing.is_sharp_drop(view.floor, previous, self.strategy):
            self.clock.sleep(self.strategy.sharp_drop_extra_delay_s)
        self.clock.sleep(self.strategy.settle_delay_s)
        _, view = self._observe()
        proposal = pricing.propose_price(view, self.strategy)
        if proposal.used_rank_fallback:
            log.info(
                "No safe lower price inside the band; holding",
                extra={"event": "hold", "account": account.id},
            )
        elif proposal.price_wei < current:
            self._list(account, proposal.price_wei, view, "lower")

    def _live_listing(
        self, account: Account, listings: Sequence[Listing]
    ) -> tuple[Wei | None, int | None]:
        """The account's cheapest live ask, read from the order book itself.

        Recorded state is trusted only for a listing priced beyond the scanned
        depth, which the book cannot show.
        """
        own = [x for x in listings if x.signer.lower() == account.address.lower()]
        if own:
            best = min(own, key=lambda x: x.price_wei)
            return best.price_wei, best.end_time

        saved = self.state.load(account.id)
        if (
            saved.price_wei is not None
            and saved.expires_at is not None
            and saved.expires_at > self.clock.now()
            and len(listings) >= self.strategy.listings_to_scan
            and saved.price_wei > listings[-1].price_wei
        ):
            return saved.price_wei, saved.expires_at
        return None, None

    def _list(self, account: Account, price: Wei, view: MarketView, reason: str) -> None:
        guard = pricing.emergency_floor(view, self.strategy)
        if price < guard:
            log.warning(
                "Emergency stop: %s is below the guard %s",
                format_eth(price),
                format_eth(guard),
                extra={"event": "emergency_stop", "account": account.id, "price_wei": price},
            )
            return
        now = self.clock.now()
        end_time = int(now + self.strategy.listing_duration_days * 86_400)
        self._publish(
            Instruction(
                action=InstructionAction.LIST,
                account_id=account.id,
                issued_at=now,
                price_wei=price,
                end_time=end_time,
            )
        )
        self.state.save(account.id, ListingState(price_wei=price, expires_at=end_time))
        log.info(
            "Listing at %s (%s)",
            format_eth(price),
            reason,
            extra={"event": "list", "account": account.id, "price_wei": price, "reason": reason},
        )

    def _publish(self, instruction: Instruction) -> None:
        if not self.trading_enabled:
            log.warning(
                "Trading disabled; not publishing %s",
                instruction.action.value,
                extra={"event": "kill_switch", "account": instruction.account_id},
            )
            return
        self.publisher.publish(instruction)

    # ----------------------------------------------------------------- helpers

    def _observe(self) -> tuple[list[Listing], MarketView]:
        s = self.strategy
        listings = self.market.listings(
            s.collection_address, s.listings_to_scan, s.min_price_to_scan_wei
        )
        floor = self.floors.current(s.collection_address, listings)
        return listings, MarketView.build(floor, listings, self._own)

    def _wait_for_sale_cooldown(self) -> None:
        """Don't relist straight after a sale: the floor is likely still moving."""
        cooldown = self.strategy.post_sale_cooldown_min * 60
        waited = 0.0
        while waited < MAX_COOLDOWN_WAIT_S:
            last_sale = self.market.last_sale_time(self.strategy.collection_address)
            if last_sale is None:
                return
            remaining = cooldown - (self.clock.now() - last_sale)
            if remaining <= 0:
                return
            step = min(remaining, COOLDOWN_POLL_S)
            self.clock.sleep(step)
            waited += step
