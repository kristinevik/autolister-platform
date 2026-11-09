"""Publishes sealed instructions to Pub/Sub.

Each account's instructions share an ordering key, so the signer receives them
in the order they were issued, while different accounts never block each other.
"""

from __future__ import annotations

from typing import Any

# Imported from the submodule: google.cloud.pubsub_v1 ships without type information.
from google.cloud.pubsub_v1 import PublisherClient
from google.cloud.pubsub_v1.types import PublisherOptions

from autolister_core.instructions import Instruction, seal

PUBLISH_TIMEOUT_S = 30.0


class PubSubPublisher:
    def __init__(self, project: str, topic: str, hmac_key: bytes, client: Any = None) -> None:
        self._client = client or PublisherClient(
            publisher_options=PublisherOptions(enable_message_ordering=True)
        )
        self._topic = self._client.topic_path(project, topic)
        self._key = hmac_key

    def publish(self, instruction: Instruction) -> None:
        future = self._client.publish(
            self._topic,
            seal(instruction, self._key),
            ordering_key=instruction.account_id,
            action=instruction.action.value,
        )
        future.result(timeout=PUBLISH_TIMEOUT_S)
