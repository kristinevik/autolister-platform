"""Replay protection.

A valid MAC proves an instruction came from the engine, not that it is new:
Pub/Sub delivers at least once, and a captured message could be replayed. So
for each account the signer remembers when the newest instruction it handled
was issued, and the ids of every instruction issued at that same moment. It
then refuses anything it has handled before, and anything issued before an
instruction it has already carried out: an account never moves backwards.

``is_new`` and ``record`` are separate on purpose. An instruction is recorded
only once it has been handled, so one that failed can be redelivered and tried
again instead of being mistaken for a replay.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from autolister_core.instructions import Instruction


@dataclass
class _Mark:
    issued_at: float
    ids: set[str] = field(default_factory=set)


class ReplayGuard:
    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._marks: dict[str, _Mark] = {}
        if path is not None and path.exists():
            for account_id, mark in json.loads(path.read_text()).items():
                self._marks[account_id] = _Mark(float(mark["issued_at"]), set(mark["ids"]))

    def is_new(self, instruction: Instruction) -> bool:
        mark = self._marks.get(instruction.account_id)
        if mark is None or instruction.issued_at > mark.issued_at:
            return True
        return (
            instruction.issued_at == mark.issued_at and instruction.instruction_id not in mark.ids
        )

    def record(self, instruction: Instruction) -> None:
        mark = self._marks.get(instruction.account_id)
        if mark is None or instruction.issued_at > mark.issued_at:
            self._marks[instruction.account_id] = _Mark(
                instruction.issued_at, {instruction.instruction_id}
            )
        elif instruction.issued_at == mark.issued_at:
            mark.ids.add(instruction.instruction_id)
        else:
            return
        self._save()

    def _save(self) -> None:
        if self._path is None:
            return
        data = {
            account_id: {"issued_at": mark.issued_at, "ids": sorted(mark.ids)}
            for account_id, mark in self._marks.items()
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        os.replace(tmp, self._path)  # atomic: a crash never leaves a half-written file
