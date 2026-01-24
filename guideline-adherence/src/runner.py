"""CLI runner for guideline adherence monitoring.

Usage:
    python -m src.runner --once                    # Run once
    python -m src.runner --once --bundle sepsis    # Run for sepsis only
    python -m src.runner --once --dry-run          # Run without creating alerts
    python -m src.runner --daemon                  # Run continuously
"""

import argparse
import logging
import sys
import time
from pathlib import Path

# Ensure parent paths are available
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import config
from src.monitor import GuidelineAdherenceMonitor, run_guideline_monitor

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging.

    Args:
        verbose: If True, use DEBUG level.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def run_once(
    bundle: str | None = None,
    dry_run: bool = False,
    verbose: bool = False,
) -> int:
    """Run the monitor once and exit.

    Args:
        bundle: Optional bundle ID to filter.
        dry_run: If True, don't create alerts.
        verbose: If True, print detailed output.

    Returns:
        Number of results/alerts found.
    """
    monitor = GuidelineAdherenceMonitor()

    if dry_run:
        print("=" * 60)
        print("GUIDELINE ADHERENCE MONITOR - DRY RUN")
        print("=" * 60)

        results = monitor.check_active_episodes(bundle)

        if not results:
            print("\nNo active episodes found.")
            return 0

        print(f"\nFound {len(results)} active episode(s):\n")

        for result in results:
            print(f"Patient: {result.patient_name} (MRN: {result.patient_mrn})")
            print(f"  Bundle: {result.bundle_name}")
            print(f"  Trigger Time: {result.trigger_time}")
            print(f"  Status: {result.episode_status.value}")
            print(f"  Adherence: {result.adherence_percentage}%")
            print(f"  Elements:")

            for er in result.element_results:
                status_icon = {
                    "met": "\u2713",
                    "not_met": "\u2717",
                    "pending": "\u25cb",
                    "na": "-",
                }.get(er.status.value, "?")

                deadline_str = ""
                if er.deadline:
                    deadline_str = f" (deadline: {er.deadline.strftime('%H:%M')})"

                print(f"    [{status_icon}] {er.element_name}: {er.status.value}{deadline_str}")
                if er.notes and verbose:
                    print(f"        Note: {er.notes}")

            print()

        # Summary
        total_met = sum(r.total_met for r in results)
        total_not_met = sum(r.total_not_met for r in results)
        total_pending = sum(r.total_pending for r in results)

        print("-" * 60)
        print(f"Summary: {total_met} met, {total_not_met} not met, {total_pending} pending")

        return len(results)

    else:
        print("=" * 60)
        print("GUIDELINE ADHERENCE MONITOR")
        print("=" * 60)

        alerts = monitor.check_new_deviations(bundle)

        if not alerts:
            print("\nNo new guideline deviations found.")
            return 0

        print(f"\nCreated {len(alerts)} alert(s):\n")

        for result, element_id, alert_id in alerts:
            print(f"  Alert ID: {alert_id}")
            print(f"    Patient: {result.patient_name} ({result.patient_mrn})")
            print(f"    Element: {element_id}")
            print()

            # Mark as sent
            monitor.mark_alert_sent(alert_id)

        return len(alerts)


def run_daemon(
    bundle: str | None = None,
    interval_minutes: int | None = None,
) -> None:
    """Run the monitor continuously.

    Args:
        bundle: Optional bundle ID to filter.
        interval_minutes: Check interval (default from config).
    """
    interval = interval_minutes or config.CHECK_INTERVAL_MINUTES

    print("=" * 60)
    print("GUIDELINE ADHERENCE MONITOR - DAEMON MODE")
    print(f"Checking every {interval} minutes")
    print("Press Ctrl+C to stop")
    print("=" * 60)

    monitor = GuidelineAdherenceMonitor()

    try:
        while True:
            try:
                logger.info("Starting adherence check...")
                alerts = monitor.check_new_deviations(bundle)

                if alerts:
                    for result, element_id, alert_id in alerts:
                        monitor.mark_alert_sent(alert_id)
                        logger.info(f"Alert created: {result.patient_mrn} - {element_id}")
                else:
                    logger.info("No new deviations found")

            except Exception as e:
                logger.error(f"Error during check: {e}")

            logger.info(f"Sleeping for {interval} minutes...")
            time.sleep(interval * 60)

    except KeyboardInterrupt:
        print("\nShutting down...")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Guideline Adherence Monitor - Real-time bundle compliance checking",
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit",
    )
    mode_group.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously",
    )

    # Options
    parser.add_argument(
        "--bundle",
        type=str,
        help="Filter to specific bundle ID (e.g., sepsis_peds_2024)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check episodes without creating alerts",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Check interval in minutes (daemon mode)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Validate bundle if specified
    if args.bundle:
        from guideline_adherence import GUIDELINE_BUNDLES
        if args.bundle not in GUIDELINE_BUNDLES:
            print(f"Error: Unknown bundle '{args.bundle}'")
            print(f"Available bundles: {', '.join(GUIDELINE_BUNDLES.keys())}")
            sys.exit(1)

    # Run appropriate mode
    if args.once:
        count = run_once(
            bundle=args.bundle,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        sys.exit(0 if count >= 0 else 1)
    elif args.daemon:
        if args.dry_run:
            print("Warning: --dry-run is ignored in daemon mode")
        run_daemon(
            bundle=args.bundle,
            interval_minutes=args.interval,
        )


if __name__ == "__main__":
    main()
