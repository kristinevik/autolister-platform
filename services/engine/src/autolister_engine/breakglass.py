"""Break glass: cancel every live order now, whatever the strategy says.

Nothing but the signer holds the wallet keys, so the cancellations travel the
normal route: sealed instructions on the topic, checked and carried out by the
signer. Pause the engine first (``AUTOLISTER_TRADING_ENABLED=false``), or its
next cycle may list again. See ``docs/runbook.md``.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

from autolister_core.accounts import Account
from autolister_core.instructions import Action, Instruction

from .ports import InstructionPublisher

log = logging.getLogger(__name__)


def cancel_everything(
    publisher: InstructionPublisher,
    accounts: Sequence[Account],
    account_ids: Sequence[str] | None,
    now: float,
) -> list[str]:
    """Publish a cancellation for each account named, or for every account if none are.

    Returns the ids of the accounts cancelled.
    """
    known = [a.id for a in accounts]
    targets = list(account_ids) if account_ids else known
    unknown = sorted(set(targets) - set(known))
    if unknown:
        raise ValueError(f"Unknown accounts: {', '.join(unknown)}")
    for account_id in targets:
        publisher.publish(
            Instruction(action=Action.CANCEL_ALL, account_id=account_id, issued_at=now)
        )
        log.warning(
            "Published a manual cancellation",
            extra={"event": "manual_cancel", "account": account_id},
        )
    return targets
