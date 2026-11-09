"""The signer end to end, against fakes: what it signs, what it refuses, and how
it behaves when parts of the world fail."""

import pytest

from autolister_core.instructions import seal
from autolister_signer.eip712 import recover_signer
from autolister_signer.ports import ReceivedMessage
from autolister_signer.replay import ReplayGuard
from autolister_signer.signer import SUBMIT_INTERVAL_S, plan

from tests.fakes import COLLECTION, NOW, WALLET_1, cancel, eth, events, last, listing

# ------------------------------------------------------------------------ the happy path


def test_lists_every_held_token_signed_by_its_own_wallet(world):
    world.source.send(listing(price="1.30"))

    assert world.signer.run_once() == 1

    bodies = world.orders.submitted
    assert world.tokens() == ["101", "102"]
    assert [b["nonce"] for b in bodies] == [41, 42]
    assert world.prices() == {str(eth("1.30"))}
    assert all(recover_signer(b) == WALLET_1.address for b in bodies)
    assert all(b["collection"] == COLLECTION and b["minPercentageToAsk"] == 9800 for b in bodies)
    assert world.source.acked == ["ack-1"]
    assert world.clock.sleeps == [SUBMIT_INTERVAL_S]  # submissions are spaced out


def test_cancels_every_order_below_the_current_nonce(world, caplog):
    world.source.send(cancel())
    world.signer.run_once()
    assert world.chain.cancels == [(WALLET_1.address, 41)]
    assert world.source.acked == ["ack-1"]
    assert events(caplog) == ["cancelled"]


# ---------------------------------------------------------------------- emergency stop


def test_refuses_a_price_below_the_21st_cheapest_ask(world, caplog):
    world.source.send(listing(price="1.19"))  # the guard is 1.20
    world.signer.run_once()
    assert world.orders.submitted == []
    assert world.source.acked == ["ack-1"]  # refusing is handling it: never retried
    assert last(caplog, "emergency_stop").guard_wei == eth("1.20")


def test_lists_at_the_guard_itself(world):
    world.source.send(listing(price="1.20"))
    world.signer.run_once()
    assert len(world.orders.submitted) == 2


def test_dust_listings_cannot_drag_the_guard_down(world):
    world.market.asks += [eth("0.01")] * 30  # troll asks under 0.1 ETH are ignored
    world.source.send(listing(price="1.10"))
    world.signer.run_once()
    assert world.orders.submitted == []


def test_refuses_to_list_against_an_empty_order_book(world, caplog):
    world.market.asks = []
    world.source.send(listing())
    world.signer.run_once()
    assert world.orders.submitted == []
    assert events(caplog) == ["emergency_stop"]


# ------------------------------------------------------------------------ verification


@pytest.mark.parametrize(
    "data",
    [
        b"not json",
        seal(listing(), b"not-the-engine"),
        seal(listing("investor-9"), b"test-hmac-key"),
    ],
    ids=["malformed", "wrong-key", "unknown-account"],
)
def test_unauthenticated_or_unknown_instructions_are_dropped(world, caplog, data):
    world.source.send_raw(data)
    world.signer.run_once()
    assert world.orders.submitted == [] and world.chain.cancels == []
    assert world.source.acked == ["ack-1"]
    assert events(caplog) == ["rejected"]
    assert last(caplog, "rejected").levelname == "ERROR"


def test_expired_instructions_are_dropped_quietly(world, caplog):
    world.source.send(listing(at=NOW - 2 * 3600))
    world.signer.run_once()
    assert world.orders.submitted == []
    assert events(caplog) == ["expired"]
    assert last(caplog, "expired").levelname == "WARNING"


@pytest.mark.parametrize("days", [0, 31])
def test_expiry_must_fall_within_30_days(world, caplog, days):
    world.source.send(listing(days=days))
    world.signer.run_once()
    assert world.orders.submitted == []
    assert events(caplog) == ["rejected"]


def test_an_instruction_is_carried_out_once(world, caplog):
    instruction = listing()
    world.source.send(instruction)
    world.signer.run_once()
    world.source.send(instruction)  # a Pub/Sub redelivery, or a replay
    world.signer.run_once()
    assert world.tokens() == ["101", "102"]
    assert events(caplog)[-1] == "duplicate"


def test_never_acts_on_an_instruction_older_than_one_already_carried_out(world):
    world.source.send(listing(price="1.40", at=NOW))
    world.signer.run_once()
    world.source.send(cancel(at=NOW - 60), listing(price="1.30", at=NOW - 30))
    world.signer.run_once()
    assert world.chain.cancels == []
    assert world.prices() == {str(eth("1.40"))}


def test_the_kill_switch_consumes_nothing(make_world):
    world = make_world(signing_enabled=False)
    world.source.send(listing())
    assert world.signer.run_once() == 0
    assert world.source.pulls == 0 and world.orders.submitted == []


# -------------------------------------------------------------------- batching and order


def test_a_batch_is_reduced_to_the_latest_intent(world):
    world.source.send(
        listing(price="1.50", at=NOW - 20),
        cancel(at=NOW - 10),
        listing(price="1.40", at=NOW),
    )
    world.signer.run_once()
    assert world.chain.cancels == [(WALLET_1.address, 41)]
    assert world.prices() == {str(eth("1.40"))}
    assert world.source.acked == ["ack-1", "ack-2", "ack-3"]


def test_a_cancellation_discards_listings_issued_before_it(world):
    world.source.send(listing(at=NOW - 10), cancel(at=NOW))
    world.signer.run_once()
    assert len(world.chain.cancels) == 1 and world.orders.submitted == []


def test_a_cancellation_and_a_listing_issued_at_the_same_instant_both_happen(world):
    world.source.send(cancel(at=NOW))
    world.signer.run_once()
    world.source.send(listing(at=NOW))
    world.signer.run_once()
    assert len(world.chain.cancels) == 1 and len(world.orders.submitted) == 2


def test_plan_follows_issue_order_not_delivery_order():
    earlier, later = listing(at=NOW - 10), cancel(at=NOW)
    todo = plan([(ReceivedMessage("b", b""), later), (ReceivedMessage("a", b""), earlier)])
    assert todo["investor-1"].cancel == later and todo["investor-1"].listing is None


# --------------------------------------------------------------------------- failures


def test_a_failed_cancellation_is_retried(world):
    world.chain.failing = True
    world.source.send(cancel())
    world.signer.run_once()
    assert world.source.nacked == ["ack-1"] and world.source.acked == []

    world.chain.failing = False
    world.signer.run_once()  # redelivered
    assert len(world.chain.cancels) == 1 and world.source.acked == ["ack-1"]


def test_a_mined_cancellation_is_not_repeated_when_the_listing_fails(world):
    world.market.unavailable = True
    world.source.send(cancel(at=NOW - 10), listing(at=NOW))
    world.signer.run_once()
    assert len(world.chain.cancels) == 1 and world.orders.submitted == []
    assert world.source.nacked == ["ack-1", "ack-2"]

    world.market.unavailable = False
    world.signer.run_once()  # both redelivered: only the listing is still to do
    assert len(world.chain.cancels) == 1
    assert world.tokens() == ["101", "102"]
    assert sorted(world.source.acked) == ["ack-1", "ack-2"]


def test_one_account_failing_does_not_hold_up_another(world):
    world.chain.failing = True
    world.source.send(cancel("investor-1"), listing("investor-2"))
    world.signer.run_once()
    assert world.source.nacked == ["ack-1"]
    assert world.tokens() == ["201"] and world.source.acked == ["ack-2"]


def test_a_rejected_order_is_reported_and_not_retried(world, caplog):
    world.orders.reject = {"101": "Token not approved"}
    world.source.send(listing())
    world.signer.run_once()
    assert world.tokens() == ["101", "102"]
    assert world.source.acked == ["ack-1"]
    record = last(caplog, "listed")
    assert record.listed == ["102"] and record.failed == {"101": "Token not approved"}


def test_sold_tokens_are_not_listed(world):
    world.inventory.sold = {"101"}
    world.source.send(listing())
    world.signer.run_once()
    assert world.tokens() == ["102"]


# ------------------------------------------------------------------------- replay guard


def test_replay_marks_survive_a_restart(tmp_path):
    path = tmp_path / "replay.json"
    handled = listing(at=NOW)
    ReplayGuard(path).record(handled)

    restarted = ReplayGuard(path)
    assert not restarted.is_new(handled)
    assert not restarted.is_new(cancel(at=NOW - 1))
    assert restarted.is_new(cancel(at=NOW))  # same instant, different instruction
    assert restarted.is_new(listing("investor-2", at=NOW - 1))  # accounts are independent
