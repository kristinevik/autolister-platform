"""Pulls instructions from the signer's Pub/Sub subscription.

The subscription has message ordering enabled, so each account's instructions
arrive in the order the engine issued them. Delivery is at least once:
idempotency comes from the replay guard, and a message that keeps failing ends
up on the dead-letter topic.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from google.api_core.exceptions import DeadlineExceeded
from google.cloud import pubsub_v1

from ..ports import ReceivedMessage

PULL_TIMEOUT_S = 30.0


class PubSubSource:
    def __init__(self, project: str, subscription: str, client: Any = None) -> None:
        self._client = client or pubsub_v1.SubscriberClient()
        self._path = self._client.subscription_path(project, subscription)

    def pull(self, max_messages: int) -> list[ReceivedMessage]:
        try:
            response = self._client.pull(
                request={"subscription": self._path, "max_messages": max_messages},
                timeout=PULL_TIMEOUT_S,
            )
        except DeadlineExceeded:
            return []
        return [
            ReceivedMessage(ack_id=m.ack_id, data=m.message.data)
            for m in response.received_messages
        ]

    def ack(self, ack_ids: Sequence[str]) -> None:
        if ack_ids:
            self._client.acknowledge(request={"subscription": self._path, "ack_ids": list(ack_ids)})

    def nack(self, ack_ids: Sequence[str]) -> None:
        if ack_ids:
            self._client.modify_ack_deadline(
                request={
                    "subscription": self._path,
                    "ack_ids": list(ack_ids),
                    "ack_deadline_seconds": 0,
                }
            )
