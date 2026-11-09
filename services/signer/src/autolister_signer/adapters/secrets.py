"""Secret Manager access.

The signer's service account can read the wallet keys, the instruction HMAC
key, the LooksRare API key and the RPC URL, and nothing else (see
``infra/terraform/secrets.tf``). Keys are fetched when needed and never written
to disk or logs.
"""

from __future__ import annotations

from typing import Any

from google.cloud import secretmanager


class SecretManagerStore:
    """Reads the latest version of a secret on every call; nothing is cached here.

    The services read API keys and the HMAC key once, at start-up, so rotating
    those takes a restart. The signer reads a wallet key each time it uses one.
    """

    def __init__(self, project: str, client: Any = None) -> None:
        self._client = client or secretmanager.SecretManagerServiceClient()
        self._project = project

    def get(self, name: str) -> str:
        path = f"projects/{self._project}/secrets/{name}/versions/latest"
        response = self._client.access_secret_version(request={"name": path})
        # Values are pasted in by hand; surrounding whitespace is never part of one.
        return str(response.payload.data.decode("utf-8")).strip()
