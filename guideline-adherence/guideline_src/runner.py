#!/usr/bin/env python3
"""CLI runner for guideline adherence monitoring.

This script provides three modes:
1. Adherence checking (FHIR) - Query FHIR directly for patients and check compliance
2. Trigger monitoring - Poll for new diagnoses/orders that create episodes
3. Episode checking - Check episodes in database for adherence and create alerts

Usage:
    # Check adherence for active episodes (queries FHIR directly)
    python -m guideline_src.runner --once                    # Run once
    python -m guideline_src.runner --once --bundle sepsis    # Run for sepsis only
    python -m guideline_src.runner --once --dry-run          # Run without creating alerts
    python -m guideline_src.runner --daemon                  # Run continuously

    # Trigger monitoring (poll for new conditions/orders)
    python -m guideline_src.runner --trigger --once          # Poll once
    python -m guideline_src.runner --trigger --daemon        # Poll continuously
    python -m guideline_src.runner --trigger --status        # Show monitoring status

    # Episode checking (check episodes in database, create alerts)
    python -m guideline_src.runner --episodes --once         # Check episodes once
    python -m guideline_src.runner --episodes --daemon       # Check continuously
    python -m guideline_src.runner --episodes --status       # Show status

    # List bundles
    python -m guideline_src.runner --list-bundles            # List available bundles
"""

import argparse
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure parent paths are available
sys.path.insert(0, str(Path(__file__).parent.parent))

from guideline_adherence import GUIDELINE_BUNDLES

from guideline_src.config import config
from guideline_src.monitor import GuidelineAdherenceMonitor, run_guideline_monitor

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


# =============================================================================
# TRIGGER MONITORING FUNCTIONS
# =============================================================================

def run_trigger_monitor(
    once: bool = False,
    interval_seconds: int = 60,
    bundles: list[str] | None = None,
    use_fhir: bool = False,
) -> int:
    """Run the bundle trigger monitor.

    Args:
        once: If True, run one cycle and exit.
        interval_seconds: Polling interval.
        bundles: Optional list of bundle IDs to monitor.
        use_fhir: If True, use real FHIR client.

    Returns:
        0 on success, 1 on error.
    """
    from guideline_src.episode_db import EpisodeDB
    from guideline_src.bundle_monitor import BundleTriggerMonitor

    # Initialize database
    db = EpisodeDB(config.ADHERENCE_DB_PATH)

    # Initialize FHIR client
    if use_fhir:
        try:
            from guideline_src.fhir_client import get_fhir_client
            fhir_client = get_fhir_client()
            logger.info(f"Using FHIR server: {config.FHIR_BASE_URL}")
        except Exception as e:
            logger.error(f"Failed to initialize FHIR client: {e}")
            fhir_client = _create_mock_fhir_client()
    else:
        logger.info("Using mock FHIR client (use --use-fhir for real data)")
        fhir_client = _create_mock_fhir_client()

    # Create monitor
    monitor = BundleTriggerMonitor(
        fhir_client=fhir_client,
        db=db,
        poll_interval_seconds=interval_seconds,
    )

    # Filter bundles if specified
    if bundles:
        monitor.bundles = {
            k: v for k, v in GUIDELINE_BUNDLES.items() if k in bundles
        }
        logger.info(f"Monitoring bundles: {list(monitor.bundles.keys())}")

    # Display header
    print("\n" + "=" * 70)
    print("BUNDLE TRIGGER MONITOR")
    print("=" * 70)
    print(f"Database: {config.ADHERENCE_DB_PATH}")
    print(f"Poll interval: {interval_seconds} seconds")
    print(f"Bundles: {len(monitor.bundles)}")
    print(f"Mode: {'Single run' if once else 'Continuous'}")
    print("=" * 70 + "\n")

    try:
        monitor.run(once=once)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 0
    except Exception as e:
        logger.exception(f"Error running trigger monitor: {e}")
        return 1


def show_trigger_status() -> None:
    """Show current trigger monitoring status."""
    from guideline_src.episode_db import EpisodeDB

    db = EpisodeDB(config.ADHERENCE_DB_PATH)

    print("\n" + "=" * 70)
    print("BUNDLE MONITORING STATUS")
    print("=" * 70)

    # Active episodes
    episodes = db.get_active_episodes(limit=20)
    print(f"\nActive Episodes: {len(episodes)}")
    print("-" * 70)

    if episodes:
        print(f"{'Patient':<15} {'Bundle':<25} {'Adherence':<12} {'Status':<10}")
        print("-" * 70)
        for ep in episodes:
            patient = ep.patient_mrn or ep.patient_id[:12]
            bundle = ep.bundle_name[:23] if ep.bundle_name else ep.bundle_id[:23]
            adherence = f"{ep.adherence_percentage or 0:.0f}%"
            print(f"{patient:<15} {bundle:<25} {adherence:<12} {ep.status:<10}")
    else:
        print("No active episodes")

    # Active alerts
    alerts = db.get_active_alerts(limit=10)
    print(f"\nActive Alerts: {len(alerts)}")
    print("-" * 70)

    if alerts:
        print(f"{'Severity':<10} {'Bundle':<20} {'Element':<25} {'Patient':<15}")
        print("-" * 70)
        for alert in alerts:
            patient = alert.patient_mrn or alert.patient_id[:12]
            bundle_name = alert.bundle_name[:18] if alert.bundle_name else "N/A"
            element_name = (alert.element_name or "N/A")[:23]
            print(f"{alert.severity:<10} {bundle_name:<20} {element_name:<25} {patient:<15}")
    else:
        print("No active alerts")

    # Adherence statistics
    stats = db.get_adherence_stats(days=30)
    print(f"\nAdherence Summary (Last 30 Days)")
    print("-" * 70)

    if stats:
        print(f"{'Bundle':<30} {'Episodes':<10} {'Full':<8} {'Partial':<8} {'Low':<8} {'Avg %':<8}")
        print("-" * 70)
        for bundle_id, s in stats.items():
            bundle_name = (s.get('bundle_name') or bundle_id)[:28]
            print(
                f"{bundle_name:<30} {s['total_episodes']:<10} "
                f"{s['full_adherence']:<8} {s['partial_adherence']:<8} "
                f"{s['low_adherence']:<8} {s['avg_adherence_pct'] or 0:.1f}%"
            )
    else:
        print("No completed episodes in last 30 days")

    print()


def list_bundles() -> None:
    """List all available bundles."""
    print("\n" + "=" * 70)
    print("AVAILABLE GUIDELINE BUNDLES")
    print("=" * 70)

    for bundle_id, bundle in GUIDELINE_BUNDLES.items():
        print(f"\n{bundle.name}")
        print(f"  ID: {bundle_id}")
        desc = bundle.description[:60] if len(bundle.description) > 60 else bundle.description
        print(f"  Description: {desc}...")
        print(f"  Elements: {len(bundle.elements)}")
        print(f"  ICD-10 triggers: {len(bundle.condition_icd10_codes)} codes")

        # Show first few elements
        print("  Key elements:")
        for element in bundle.elements[:5]:
            req = "[Required]" if element.required else "[Optional]"
            window = f"({element.time_window_hours}h)" if element.time_window_hours else ""
            print(f"    - {req} {element.name} {window}")
        if len(bundle.elements) > 5:
            print(f"    ... and {len(bundle.elements) - 5} more")

    print()


def _create_mock_fhir_client():
    """Create a mock FHIR client for testing."""

    class MockFHIRClient:
        """Mock FHIR client for testing."""

        def get_patient(self, patient_id):
            return {
                "id": patient_id,
                "mrn": f"MRN{patient_id[-6:]}",
                "birth_date": datetime(2024, 1, 1).date(),
            }

        def get_recent_conditions(self, since_time, icd10_patterns=None):
            return []

        def get_recent_medication_orders(self, since_time):
            return []

        def get_recent_lab_orders(self, since_time, loinc_codes=None):
            return []

        def get_lab_results(self, patient_id, loinc_codes, since_time):
            return []

        def get_medication_administrations(self, patient_id, since_time):
            return []

        def get_medication_orders(self, patient_id, since_time):
            return []

        def get_recent_notes(self, patient_id, since_time):
            return []

        def get_orders(self, patient_id, order_type, since_time):
            return []

        def get_patient_conditions(self, patient_id):
            return []

        def get_sepsis_patients(self):
            return []

        def get_patients_by_condition(self, icd10_prefixes, max_age_days=None):
            return []

    return MockFHIRClient()


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Guideline Adherence Monitor - Real-time bundle compliance checking",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Check adherence for active episodes
  %(prog)s --once --dry-run                  Check without creating alerts
  %(prog)s --once --bundle sepsis_peds_2024  Check specific bundle
  %(prog)s --daemon                          Run continuously

  # Trigger monitoring (poll for new conditions/orders)
  %(prog)s --trigger --once                  Poll once for new triggers
  %(prog)s --trigger --daemon                Poll continuously
  %(prog)s --trigger --status                Show monitoring status
  %(prog)s --trigger --list-bundles          List available bundles
        """
    )

    # Mode selection
    mode_group = parser.add_mutually_exclusive_group()
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

    # Trigger monitoring mode
    parser.add_argument(
        "--trigger",
        action="store_true",
        help="Use trigger monitoring mode (poll for new diagnoses/orders)",
    )

    # Episode checking mode
    parser.add_argument(
        "--episodes",
        action="store_true",
        help="Check episodes in database for adherence (creates alerts)",
    )

    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current monitoring status (with --trigger or --episodes)",
    )
    parser.add_argument(
        "--list-bundles",
        action="store_true",
        help="List available bundles and exit",
    )

    # Options
    parser.add_argument(
        "--bundle",
        type=str,
        action="append",
        help="Filter to specific bundle ID(s) (can repeat)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Check episodes without creating alerts",
    )
    parser.add_argument(
        "--interval",
        type=int,
        help="Check interval (minutes for adherence, seconds for trigger)",
    )
    parser.add_argument(
        "--use-fhir",
        action="store_true",
        help="Use real FHIR client (default: mock for testing)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Handle list-bundles
    if args.list_bundles:
        list_bundles()
        sys.exit(0)

    # Handle trigger mode
    if args.trigger:
        if args.status:
            show_trigger_status()
            sys.exit(0)

        if not (args.once or args.daemon):
            parser.error("--trigger requires --once or --daemon")

        interval = args.interval or 60  # seconds for trigger mode
        result = run_trigger_monitor(
            once=args.once,
            interval_seconds=interval,
            bundles=args.bundle,
            use_fhir=args.use_fhir,
        )
        sys.exit(result)

    # Handle episode checking mode
    if args.episodes:
        from guideline_src.episode_monitor import EpisodeAdherenceMonitor

        monitor = EpisodeAdherenceMonitor()

        if args.status:
            monitor.print_status()
            sys.exit(0)

        if not (args.once or args.daemon):
            parser.error("--episodes requires --once or --daemon")

        bundle = args.bundle[0] if args.bundle else None

        print("\n" + "=" * 70)
        print("EPISODE ADHERENCE MONITOR")
        print("=" * 70)
        print(f"Mode: {'Single run' if args.once else 'Daemon'}")
        print(f"Dry run: {args.dry_run}")
        print("=" * 70)

        if args.once:
            results = monitor.check_all_episodes(
                bundle_id=bundle,
                dry_run=args.dry_run,
                verbose=args.verbose,
            )
            print(f"\nChecked {len(results)} episode(s)")
            total_alerts = sum(r.get("alerts_created", 0) for r in results)
            if total_alerts:
                print(f"Created {total_alerts} alert(s)")
            sys.exit(0)
        else:
            interval = args.interval or 5  # minutes for episode checking
            print(f"Checking every {interval} minutes. Press Ctrl+C to stop.\n")

            try:
                while True:
                    results = monitor.check_all_episodes(
                        bundle_id=bundle,
                        dry_run=args.dry_run,
                        verbose=args.verbose,
                    )
                    logger.info(f"Checked {len(results)} episodes")
                    time.sleep(interval * 60)
            except KeyboardInterrupt:
                print("\nShutting down...")
            sys.exit(0)

    # Handle adherence mode (default)
    if not (args.once or args.daemon):
        parser.error("Use --once or --daemon (or --trigger for trigger monitoring)")

    # Validate bundle if specified
    if args.bundle:
        for b in args.bundle:
            if b not in GUIDELINE_BUNDLES:
                print(f"Error: Unknown bundle '{b}'")
                print(f"Available bundles: {', '.join(GUIDELINE_BUNDLES.keys())}")
                sys.exit(1)
        bundle = args.bundle[0]  # Use first bundle for adherence mode
    else:
        bundle = None

    # Run appropriate mode
    if args.once:
        count = run_once(
            bundle=bundle,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )
        sys.exit(0 if count >= 0 else 1)
    elif args.daemon:
        if args.dry_run:
            print("Warning: --dry-run is ignored in daemon mode")
        run_daemon(
            bundle=bundle,
            interval_minutes=args.interval,
        )


if __name__ == "__main__":
    main()
