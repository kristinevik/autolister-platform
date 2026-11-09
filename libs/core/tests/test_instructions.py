import json

import pytest
from hypothesis import given
from hypothesis import strategies as st

from autolister_core.instructions import (
    Action,
    Instruction,
    InstructionError,
    InstructionExpired,
    seal,
    unseal,
)

KEY = b"test-key"
NOW = 1_666_000_000.0


def listing(at: float = NOW) -> Instruction:
    return Instruction(
        action=Action.LIST,
        account_id="investor-1",
        issued_at=at,
        price_wei=10**18,
        end_time=1_700_000_000,
    )


def test_round_trip():
    original = listing()
    assert unseal(seal(original, KEY), KEY, now=NOW) == original


def test_every_instruction_gets_a_unique_id():
    assert listing().instruction_id != listing().instruction_id


@pytest.mark.parametrize(
    "mutate, error",
    [
        (lambda env: env.update(mac="0" * 64), "Bad MAC"),
        (lambda env: env["payload"].update(price_wei=1), "Bad MAC"),
        (lambda env: env.pop("mac"), "Malformed"),
    ],
)
def test_tampering_is_rejected(mutate, error):
    envelope = json.loads(seal(listing(), KEY))
    mutate(envelope)
    with pytest.raises(InstructionError, match=error):
        unseal(json.dumps(envelope).encode(), KEY, now=NOW)


def test_wrong_key_and_stale_or_future_instructions_are_rejected():
    with pytest.raises(InstructionError, match="Bad MAC"):
        unseal(seal(listing(), KEY), b"attacker", now=NOW)
    with pytest.raises(InstructionExpired, match="expired"):
        unseal(seal(listing(at=NOW - 7200), KEY), KEY, now=NOW)
    with pytest.raises(InstructionExpired, match="future"):
        unseal(seal(listing(at=NOW + 600), KEY), KEY, now=NOW)


def test_schema_rules():
    with pytest.raises(ValueError):
        Instruction(action=Action.LIST, account_id="a", issued_at=NOW)
    with pytest.raises(ValueError):
        Instruction(action=Action.CANCEL_ALL, account_id="a", issued_at=NOW, price_wei=1)
    with pytest.raises(ValueError):
        Instruction(action=Action.CANCEL_ALL, account_id="a", issued_at=NOW, surprise=True)


@given(st.data())
def test_any_single_byte_change_is_rejected_or_harmless(data):
    sealed = seal(listing(), KEY).decode()
    index = data.draw(st.integers(min_value=0, max_value=len(sealed) - 1))
    replacement = data.draw(
        st.characters(min_codepoint=32, max_codepoint=126).filter(lambda c: c != sealed[index])
    )
    tampered = sealed[:index] + replacement + sealed[index + 1 :]
    try:
        decoded = unseal(tampered.encode(), KEY, now=NOW)
    except InstructionError:
        return
    # Only meaning-preserving edits (such as JSON whitespace) may get through.
    assert decoded == unseal(sealed.encode(), KEY, now=NOW)
