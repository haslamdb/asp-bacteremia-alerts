#!/usr/bin/env python3
"""CLI entry point for Drug-Bug Mismatch Monitor."""

import argparse
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from .config import config
from .monitor import DrugBugMismatchMonitor


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Drug-Bug Mismatch Monitor - Detect antibiotic-organism mismatches"
    )

    parser.add_argument(
        "--continuous",
        action="store_true",
        help="Run in continuous monitoring mode",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=None,
        help=f"Poll interval in seconds (default: {config.POLL_INTERVAL})",
    )
    parser.add_argument(
        "--lookback",
        type=int,
        default=None,
        help=f"Hours to look back for cultures (default: {config.LOOKBACK_HOURS})",
    )
    parser.add_argument(
        "--fhir-url",
        type=str,
        default=None,
        help=f"FHIR server URL (default: {config.FHIR_BASE_URL})",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Alert database path (default from config)",
    )

    args = parser.parse_args()

    # Override config if arguments provided
    if args.fhir_url:
        config.FHIR_BASE_URL = args.fhir_url
    if args.db_path:
        config.ALERT_DB_PATH = args.db_path

    # Create monitor
    lookback_hours = args.lookback or config.LOOKBACK_HOURS
    monitor = DrugBugMismatchMonitor(lookback_hours=lookback_hours)

    # Run
    if args.continuous:
        interval = args.interval or config.POLL_INTERVAL
        monitor.run_continuous(interval_seconds=interval)
    else:
        alerts = monitor.run_once()
        print(f"\nTotal alerts generated: {alerts}")


if __name__ == "__main__":
    main()
