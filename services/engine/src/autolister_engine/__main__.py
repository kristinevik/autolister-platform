"""Entry point.

    autolister-engine                    run the pricing loop
    autolister-engine cancel-all --all   break glass: cancel every live order
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from collections.abc import Sequence

from pythonjsonlogger import jsonlogger

from autolister_core.accounts import load_accounts

from .adapters.floor import FloorOracle, alchemy, nftbank
from .adapters.looksrare import LooksRareClient
from .adapters.pubsub import PubSubPublisher
from .adapters.secrets import SecretManagerStore
from .adapters.state import JsonStateStore
from .breakglass import cancel_everything
from .config import EngineSettings, Strategy
from .engine import Engine
from .ports import SystemClock

log = logging.getLogger("autolister_engine")


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


def publisher(settings: EngineSettings, secrets: SecretManagerStore) -> PubSubPublisher:
    return PubSubPublisher(
        settings.gcp_project,
        settings.instruction_topic,
        secrets.get("instruction-hmac-key").encode(),
    )


def build(settings: EngineSettings) -> Engine:
    secrets = SecretManagerStore(settings.gcp_project)
    return Engine(
        strategy=Strategy.from_yaml(settings.strategy_file),
        accounts=load_accounts(settings.accounts_file),
        market=LooksRareClient(),
        floors=FloorOracle(
            [alchemy(secrets.get("alchemy-api-key")), nftbank(secrets.get("nftbank-api-key"))]
        ),
        publisher=publisher(settings, secrets),
        state=JsonStateStore(settings.state_dir),
        clock=SystemClock(),
        trading_enabled=settings.trading_enabled,
    )


def run(settings: EngineSettings) -> None:
    engine = build(settings)
    clock = SystemClock()
    log.info(
        "Engine started", extra={"event": "start", "trading_enabled": settings.trading_enabled}
    )
    while True:
        try:
            engine.run_once()
        except Exception:  # the cycle failed; log it, and the next cycle retries
            log.exception("Engine cycle failed", extra={"event": "error"})
        clock.sleep(settings.interval_s)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="autolister-engine")
    commands = parser.add_subparsers(dest="command")
    commands.add_parser("run", help="run the pricing loop (the default)")
    cancel = commands.add_parser("cancel-all", help="break glass: cancel every live order")
    target = cancel.add_mutually_exclusive_group(required=True)
    target.add_argument("--account", action="append", metavar="ID", help="repeatable")
    target.add_argument("--all", action="store_true", help="every account in the accounts file")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> None:
    args = parse_args(argv)
    configure_logging()
    settings = EngineSettings()
    if args.command == "cancel-all":
        secrets = SecretManagerStore(settings.gcp_project)
        cancel_everything(
            publisher(settings, secrets),
            load_accounts(settings.accounts_file),
            args.account,
            now=time.time(),
        )
    else:
        run(settings)


if __name__ == "__main__":
    main()
