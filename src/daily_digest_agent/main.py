from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from .config import load_config
from .delivery.recovery import retry_delivery
from .exceptions import DailyDigestError
from .factory import create_delivery, create_pipeline, create_store
from .models import BudgetStatus


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="daily-digest-agent")
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("validate-config", "init-db", "show-budget", "show-last-run"):
        command = commands.add_parser(name)
        command.add_argument("--config")
    reservations = commands.add_parser("show-budget-reservations")
    reservations.add_argument("--config")
    reservations.add_argument("--month")
    reservations.add_argument("--state")
    reservations.add_argument("--limit", type=int, default=100)
    release = commands.add_parser("release-budget-reservation")
    release.add_argument("--config")
    release.add_argument("--id", required=True)
    release.add_argument("--reason", required=True)
    release.add_argument("--unsafe-release", action="store_true", required=True)
    stale = commands.add_parser("show-stale")
    stale.add_argument("--config")
    stale.add_argument("--older-than-hours", type=float, default=6.0)
    deliveries = commands.add_parser("show-deliveries")
    deliveries.add_argument("--config")
    deliveries.add_argument("--limit", type=int, default=20)
    delivery = commands.add_parser("show-delivery")
    delivery.add_argument("--config")
    delivery.add_argument("--id", required=True)
    retry = commands.add_parser("retry-delivery")
    retry.add_argument("--config")
    retry.add_argument("--id", required=True)
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
            local_date = datetime.now(ZoneInfo(config.digest.timezone)).date()
            usage = store.get_usage(local_date)
            threshold = config.budget.monthly_usd_cap - config.budget.monthly_safety_buffer_usd
            status = BudgetStatus(
                local_date=local_date,
                local_month=local_date.strftime("%Y-%m"),
                monthly_usd_cap=config.budget.monthly_usd_cap,
                monthly_safety_buffer_usd=config.budget.monthly_safety_buffer_usd,
                monthly_safety_threshold_usd=threshold,
                estimated_monthly_cost_usd=usage.estimated_monthly_cost_usd,
                reserved_monthly_cost_usd=usage.reserved_monthly_cost_usd,
                remaining_application_capacity_usd=max(
                    0.0, threshold - usage.estimated_monthly_cost_usd - usage.reserved_monthly_cost_usd
                ),
                provider_calls_today=usage.provider_calls_today,
                provider_calls_month=usage.provider_calls_month,
            )
            print(status.model_dump_json(indent=2))
        elif args.command == "show-budget-reservations":
            store.initialize()
            month = args.month or datetime.now(ZoneInfo(config.digest.timezone)).strftime("%Y-%m")
            print(json.dumps(store.list_budget_reservations(month, args.state, args.limit), indent=2, default=str))
        elif args.command == "release-budget-reservation":
            store.initialize()
            if not store.release_budget_reservation(args.id, args.reason):
                raise DailyDigestError(
                    f"Reservation {args.id} was not found or is not in the reserved state"
                )
            print(json.dumps({"id": args.id, "state": "released", "reason": args.reason}, indent=2))
        elif args.command == "show-stale":
            store.initialize()
            cutoff = datetime.now(UTC) - timedelta(hours=args.older_than_hours)
            print(json.dumps(store.list_stale_records(cutoff), indent=2, default=str))
        elif args.command == "show-last-run":
            store.initialize()
            print(json.dumps(store.get_last_run(), indent=2, default=str))
        elif args.command == "show-deliveries":
            store.initialize()
            print(json.dumps(store.list_deliveries(args.limit), indent=2, default=str))
        elif args.command == "show-delivery":
            store.initialize()
            print(json.dumps(store.get_delivery(args.id), indent=2, default=str))
        elif args.command == "retry-delivery":
            store.initialize()
            delivery_result = retry_delivery(store, create_delivery(config), args.id)
            print(json.dumps(delivery_result, indent=2, default=str))
        elif args.command == "run":
            if args.offline:
                raise DailyDigestError(
                    "Offline mode is reserved for fixture-based test integrations; no fixture was configured"
                )
            dry_run = args.dry_run or os.getenv("DRY_RUN", "false").lower() in {"1", "true", "yes"}
            if dry_run:
                logging.warning("DRY RUN: delivery and sent-state updates are disabled")
            run_result = create_pipeline(config).run(
                dry_run=dry_run,
                force=args.force,
                force_send=args.force_send,
                unsafe_budget_override=args.unsafe_budget_override,
            )
            print(run_result.model_dump_json(indent=2))
    except DailyDigestError as exc:
        logging.error("%s", exc)
        sys.exit(2)


if __name__ == "__main__":
    main()
