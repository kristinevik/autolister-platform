"""Entry point: wires the adapters to the signer and runs the consume loop."""

from __future__ import annotations

import logging
import sys
import time

from pythonjsonlogger import jsonlogger
from web3 import Web3

from autolister_core.accounts import load_accounts

from .adapters.chain import EthereumChain, EthereumInventory
from .adapters.looksrare import LooksRareGateway
from .adapters.pubsub import PubSubSource
from .adapters.secrets import SecretManagerStore
from .config import SignerSettings
from .ports import SystemClock
from .replay import ReplayGuard
from .signer import Signer

log = logging.getLogger("autolister_signer")


def configure_logging() -> None:
    """One JSON object per line on stdout; Cloud Logging parses it into jsonPayload."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            rename_fields={"levelname": "severity", "asctime": "time"},
        )
    )
    logging.basicConfig(level=logging.INFO, handlers=[handler])


def build(settings: SignerSettings) -> Signer:
    secrets = SecretManagerStore(settings.gcp_project)
    web3 = Web3(Web3.HTTPProvider(secrets.get("eth-rpc-url")))
    gateway = LooksRareGateway(secrets.get("looksrare-api-key"))
    return Signer(
        settings=settings,
        accounts=load_accounts(settings.accounts_file),
        source=PubSubSource(settings.gcp_project, settings.instruction_subscription),
        market=gateway,
        orders=gateway,
        chain=EthereumChain(web3, settings.max_fee_gwei, settings.priority_fee_gwei),
        inventory=EthereumInventory(web3),
        secrets=secrets,
        replay=ReplayGuard(settings.replay_state_file),
        clock=SystemClock(),
    )


def main() -> None:
    configure_logging()
    settings = SignerSettings()
    signer = build(settings)
    if settings.signing_enabled:
        log.info("Signer started", extra={"event": "start", "signing_enabled": True})
    else:
        log.warning(
            "Signer started with signing disabled; consuming nothing",
            extra={"event": "kill_switch", "signing_enabled": False},
        )
    while True:
        try:
            received = signer.run_once()
        except Exception:  # log it; anything not acknowledged is redelivered
            log.exception("Signer cycle failed", extra={"event": "error"})
            received = 0
        if received == 0:
            time.sleep(settings.poll_interval_s)


if __name__ == "__main__":
    main()
