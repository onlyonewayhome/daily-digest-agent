from __future__ import annotations

import argparse
import json
import logging
import os
import sys

from .config import load_config
from .exceptions import DailyDigestError
from .factory import create_pipeline, create_store


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="daily-digest-agent")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("validate-config", "init-db", "show-budget", "show-last-run"):
        command = commands.add_parser(name)
        command.add_argument("--config")
    run = commands.add_parser("run")
    run.add_argument("--config")
    run.add_argument("--dry-run", action="store_true")
    run.add_argument("--offline", action="store_true")
    run.add_argument("--force", action="store_true")
    run.add_argument("--force-send", action="store_true")
    run.add_argument("--unsafe-budget-override", action="store_true")
    return root


def main() -> None:
    args = parser().parse_args()
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        config = load_config(args.config)
        if args.command == "validate-config":
            print("Configuration is valid.")
            return
        store = create_store(config)
        if args.command == "init-db":
            store.initialize()
            print("State store initialized.")
        elif args.command == "show-budget":
            store.initialize()
            from datetime import datetime
            from zoneinfo import ZoneInfo
            local_date = datetime.now(ZoneInfo(config.digest.timezone)).date()
            print(store.get_usage(local_date).model_dump_json(indent=2))
        elif args.command == "show-last-run":
            store.initialize()
            print(json.dumps(store.get_last_run(), indent=2, default=str))
        elif args.command == "run":
            if args.offline:
                raise DailyDigestError(
                    "Offline mode is reserved for fixture-based test integrations; no fixture was configured"
                )
            dry_run = args.dry_run or os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
            if dry_run:
                logging.warning("DRY RUN: delivery and sent-state updates are disabled")
            result = create_pipeline(config).run(
                dry_run=dry_run,
                force=args.force,
                force_send=args.force_send,
                unsafe_budget_override=args.unsafe_budget_override,
            )
            print(result.model_dump_json(indent=2))
    except DailyDigestError as exc:
        logging.error("%s", exc)
        sys.exit(2)


if __name__ == "__main__":
    main()
