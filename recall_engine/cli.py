"""Command-line interface for a cron-invoked recall outreach engine."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

from .config import Settings
from .database import Database
from .delivery import DryRunSender, ResendSender
from .engine import RecallEngine


def parse_as_of(value: str | None, time_zone: str) -> datetime:
    """Use current local time by default; parse date-only values at local noon."""
    zone = ZoneInfo(time_zone)
    if value is None:
        return datetime.now(zone)
    if len(value) == 10:
        return datetime.combine(datetime.fromisoformat(value).date(), time(12), zone)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=zone) if parsed.tzinfo is None else parsed.astimezone(zone)


def shared_data_arguments(parser: argparse.ArgumentParser) -> None:
    """Add the common CSV paths and practice-controlled template values."""
    parser.add_argument("--patients", type=Path, required=True, help="Path to patients.csv")
    parser.add_argument("--appointments", type=Path, required=True, help="Path to appointments.csv")
    parser.add_argument("--as-of", help="Optional ISO date or datetime, for reproducible runs")
    parser.add_argument("--practice-name", default="Your Dental Practice")
    parser.add_argument("--booking-link", default="https://example.com/book")
    parser.add_argument("--unsubscribe-link", default="https://example.com/unsubscribe")


def build_parser() -> argparse.ArgumentParser:
    """Define state, planning, delivery, pause, and suppression commands."""
    parser = argparse.ArgumentParser(description="Stateful, paced recall-outreach engine")
    parser.add_argument("--db", type=Path, default=Path("data/recall_engine.sqlite3"), help="SQLite database path")
    parser.add_argument("--verbose", action="store_true")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-db", help="Create the SQLite schema")
    subparsers.add_parser("pause", help="Pause planning and delivery without losing state")
    subparsers.add_parser("resume", help="Resume planning and delivery")
    subparsers.add_parser("status", help="Show persisted engine status")
    suppress = subparsers.add_parser("suppress", help="Persist an opt-out or other patient suppression")
    suppress.add_argument("--patient-id", required=True)
    suppress.add_argument("--reason", default="manual_suppression")
    unsuppress = subparsers.add_parser("unsuppress", help="Remove a persisted patient suppression")
    unsuppress.add_argument("--patient-id", required=True)

    plan = subparsers.add_parser("plan-week", help="Create this week's idempotent paced enrollment plan")
    shared_data_arguments(plan)
    plan.add_argument("--weekly-capacity", type=int, help="Override configured weekly enrollment capacity")

    run = subparsers.add_parser("run", help="Refresh data, plan once per week, and deliver due touches")
    shared_data_arguments(run)
    run.add_argument("--weekly-capacity", type=int, help="Override configured weekly enrollment capacity")
    mode = run.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Log due messages without sending them (default)")
    mode.add_argument("--send", action="store_true", help="Actually send through Resend; requires .env credentials")
    run.add_argument(
        "--recipient-override",
        help="Send every due message to this controlled address; use for a safe end-to-end demonstration",
    )
    run.add_argument("--delivery-limit", type=int, help="Maximum due messages to process in this invocation")

    deliver = subparsers.add_parser("deliver", help="Refresh data and deliver due touches without planning")
    shared_data_arguments(deliver)
    mode = deliver.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Log due messages without sending them (default)")
    mode.add_argument("--send", action="store_true", help="Actually send through Resend; requires .env credentials")
    deliver.add_argument("--recipient-override", help="Send every due message to this controlled address")
    deliver.add_argument("--delivery-limit", type=int, help="Maximum due messages to process in this invocation")
    return parser


def print_result(result: dict) -> None:
    """Print machine-readable command results for logs and scheduled jobs."""
    print(json.dumps(result, indent=2, sort_keys=True, default=str))


def sender_for(settings: Settings, send: bool):
    """Default to dry-run; require explicit credentials for real delivery."""
    if not send:
        return DryRunSender(), True
    if not settings.resend_api_key or settings.resend_api_key.startswith("replace_with_"):
        raise ValueError("Set RESEND_API_KEY in .env before using --send")
    if not settings.email_from:
        raise ValueError("Set EMAIL_FROM in .env before using --send")
    return ResendSender(settings.resend_api_key, settings.email_from), False


def main(argv: list[str] | None = None) -> int:
    """Execute one stateful engine command and print its result."""
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(levelname)s %(message)s")
    settings = Settings.from_environment(args.db)
    engine = RecallEngine(Database(settings.database_path), settings.time_zone)
    engine.initialize()

    if args.command == "init-db":
        print_result({"database": str(settings.database_path), "initialized": True})
        return 0
    if args.command == "pause":
        engine.set_paused(True)
        print_result({"paused": True})
        return 0
    if args.command == "resume":
        engine.set_paused(False)
        print_result({"paused": False})
        return 0
    if args.command == "status":
        print_result(engine.status())
        return 0
    if args.command == "suppress":
        applied = engine.suppress_patient(args.patient_id, args.reason, datetime.now(engine.zone))
        print_result({"patient_id": args.patient_id, "suppressed": applied, "reason": args.reason})
        return 0
    if args.command == "unsuppress":
        removed = engine.unsuppress_patient(args.patient_id)
        print_result({"patient_id": args.patient_id, "suppression_removed": removed})
        return 0

    now = parse_as_of(args.as_of, settings.time_zone)
    states = engine.load_states(args.patients, args.appointments, now)
    cancelled = engine.suppress_booked_patients(states, now)
    if args.command == "plan-week":
        capacity = args.weekly_capacity or settings.weekly_capacity
        result = engine.plan_week(
            states, now, capacity, args.practice_name, args.booking_link, args.unsubscribe_link
        )
        result["cancelled_for_booking"] = cancelled
        print_result(result)
        return 0

    sender, dry_run = sender_for(settings, args.send)
    result: dict = {"cancelled_for_booking": cancelled}
    if args.command == "run":
        capacity = args.weekly_capacity or settings.weekly_capacity
        result["plan"] = engine.plan_week(
            states, now, capacity, args.practice_name, args.booking_link, args.unsubscribe_link
        )
    result["delivery"] = engine.send_due_messages(
        states, now, sender, dry_run, recipient_override=args.recipient_override,
        delivery_limit=args.delivery_limit,
    )
    print_result(result)
    return 0


def entrypoint() -> int:
    """Convert expected configuration/input failures into concise CLI errors."""
    try:
        return main()
    except (ValueError, FileNotFoundError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(entrypoint())
