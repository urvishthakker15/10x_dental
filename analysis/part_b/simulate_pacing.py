"""Project confirmed recall backlog under a configurable weekly pacing policy."""

from __future__ import annotations

import argparse


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simulate 12–24 months of recall pacing.")
    parser.add_argument("--initial-backlog", type=float, required=True)
    parser.add_argument("--weekly-inflow", type=float, required=True)
    parser.add_argument("--weekly-capacity", type=float, required=True)
    parser.add_argument("--confirmed-share", type=float, default=0.90)
    parser.add_argument("--recontact-share", type=float, default=0.05)
    parser.add_argument("--no-history-share", type=float, default=0.05)
    parser.add_argument(
        "--recontact-start-week",
        type=int,
        default=16,
        help="First week with cooled-down non-responder re-contact capacity.",
    )
    parser.add_argument("--conversion-rate", type=float, default=0.10)
    parser.add_argument("--weeks", type=int, default=104)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    shares = args.confirmed_share + args.recontact_share + args.no_history_share
    if abs(shares - 1) > 1e-9:
        raise ValueError("Allocation shares must sum to 1.")

    confirmed_weekly_ceiling = args.weekly_capacity * args.confirmed_share
    recontact_weekly_target = args.weekly_capacity * args.recontact_share
    no_history_weekly_target = args.weekly_capacity * args.no_history_share
    backlog = args.initial_backlog
    total_confirmed_enrolled = 0.0
    total_enrolled = 0.0
    total_expected_bookings = 0.0
    cleared_week = None
    milestones = {1, 13, 26, 39, 52, 65, 78, 91, args.weeks}

    print("Pacing assumptions")
    print(f"  Initial confirmed backlog: {args.initial_backlog:,.0f}")
    print(f"  Weekly newly-overdue inflow: {args.weekly_inflow:.1f}")
    print(f"  Weekly enrollment ceiling: {args.weekly_capacity:.1f}")
    print(f"  Confirmed backlog allocation: {args.confirmed_share:.0%}")
    print(f"  Re-contact allocation: {args.recontact_share:.0%}")
    print(f"  No-history allocation: {args.no_history_share:.0%}")
    print(f"  Re-contact stream starts: week {args.recontact_start_week}")
    print(f"  Booking conversion assumption: {args.conversion_rate:.0%}")
    print("\nProjection")
    print(f"{'Week':>5} {'Confirmed enrolled':>20} {'Expected bookings':>19} {'Backlog remaining':>19}")
    print("-" * 70)

    for week in range(1, args.weeks + 1):
        backlog += args.weekly_inflow
        confirmed_enrolled = min(backlog, confirmed_weekly_ceiling)
        backlog -= confirmed_enrolled

        # When the confirmed backlog is fully cleared, unused confirmed-pool
        # capacity is not forced onto the same people. The program scales down
        # to actual new inflow plus the separately capped re-contact/no-history
        # streams.
        recontact_enrolled = (
            recontact_weekly_target if week >= args.recontact_start_week else 0
        )
        total_this_week = confirmed_enrolled + recontact_enrolled + no_history_weekly_target
        expected_bookings = total_this_week * args.conversion_rate
        total_confirmed_enrolled += confirmed_enrolled
        total_enrolled += total_this_week
        total_expected_bookings += expected_bookings

        if backlog == 0 and cleared_week is None:
            cleared_week = week
        if week in milestones:
            print(
                f"{week:>5} {confirmed_enrolled:>20.1f} {expected_bookings:>19.1f} {backlog:>19.1f}"
            )

    print("\nSummary")
    print(f"  Confirmed backlog cleared in: {cleared_week if cleared_week else 'not within horizon'} weeks")
    print(f"  Confirmed patients enrolled: {total_confirmed_enrolled:,.0f}")
    print(f"  Total enrolled across all pools: {total_enrolled:,.0f}")
    print(f"  Expected bookings across all pools: {total_expected_bookings:,.0f}")
    print(f"  Backlog at end of horizon: {backlog:,.0f}")


if __name__ == "__main__":
    main()
