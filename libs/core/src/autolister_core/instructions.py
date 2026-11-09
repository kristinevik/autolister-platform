"""The instruction protocol between the engine and the signer.

The engine publishes instructions to a Pub/Sub topic; the signer consumes them.
Pub/Sub IAM already restricts who may publish, but the signer must not depend
on a single access-control setting staying correct. Every instruction is
therefore also *sealed* at the application layer:

* an HMAC-SHA256 over a canonical JSON encoding proves it came from the engine,
* ``issued_at`` lets the signer refuse stale instructions,
* ``instruction_id`` lets it recognise duplicates, which Pub/Sub's
  at-least-once delivery will occasionally produce.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field, ValidationError, root_validator

SCHEMA_VERSION = 1
DEFAULT_MAX_AGE_S = 3600.0


class InstructionError(ValueError):
    """An instruction failed verification and must not be acted on."""


class InstructionExpired(InstructionError):
    """An authentic instruction that is too old, or dated in the future.

    Kept apart from other failures: an expiry is expected after the signer has
    been paused, whereas a bad MAC never is.
    """


class Action(str, Enum):
    CANCEL_ALL = "cancel_all"
    LIST = "list"


class Instruction(BaseModel):
    action: Action
    account_id: str
    issued_at: float
    instruction_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    price_wei: Optional[int] = None
    end_time: Optional[int] = None

    class Config:
        frozen = True
        extra = "forbid"

    @root_validator(skip_on_failure=True)
    def _price_only_on_listings(cls, values: Dict[str, Any]) -> Dict[str, Any]:
        if values["action"] is Action.LIST:
            if not values.get("price_wei") or not values.get("end_time"):
                raise ValueError("LIST instructions need a positive price_wei and an end_time")
        elif values.get("price_wei") is not None or values.get("end_time") is not None:
            raise ValueError("Only LIST instructions carry a price")
        return values


def _canonical(payload: Dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()


def _mac(key: bytes, payload: Dict[str, Any]) -> str:
    return hmac.new(key, _canonical(payload), hashlib.sha256).hexdigest()


def seal(instruction: Instruction, key: bytes) -> bytes:
    """Serialise and authenticate an instruction for publishing."""
    payload = json.loads(instruction.json())
    payload["v"] = SCHEMA_VERSION
    return json.dumps({"payload": payload, "mac": _mac(key, payload)}).encode()


def unseal(
    data: bytes, key: bytes, now: float, max_age_s: float = DEFAULT_MAX_AGE_S
) -> Instruction:
    """Verify and parse a sealed instruction. Raises ``InstructionError`` on any problem."""
    try:
        envelope = json.loads(data)
        payload, mac = envelope["payload"], envelope["mac"]
        if not isinstance(payload, dict):
            raise TypeError("payload must be an object")
    except (ValueError, KeyError, TypeError) as exc:
        raise InstructionError("Malformed instruction") from exc

    if not hmac.compare_digest(_mac(key, payload), str(mac)):
        raise InstructionError("Bad MAC")
    if payload.pop("v", None) != SCHEMA_VERSION:
        raise InstructionError("Unsupported schema version")
    try:
        instruction = Instruction.parse_obj(payload)
    except ValidationError as exc:
        raise InstructionError(f"Invalid instruction: {exc}") from exc

    age = now - instruction.issued_at
    if age > max_age_s:
        raise InstructionExpired(f"Instruction expired ({age:.0f}s old)")
    if age < -60:
        raise InstructionExpired("Instruction is dated in the future")
    return instruction
