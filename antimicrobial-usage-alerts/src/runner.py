"""Main runner for Antimicrobial Usage Alerts.

Monitors for broad-spectrum antibiotic usage exceeding threshold
and sends alerts via configured channels.
"""

import argparse
import logging
import time
import sys

from .config import config
from .monitor import BroadSpectrumMonitor
from .alerters import EmailAlerter, TeamsAlerter

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def run_once(monitor: BroadSpectrumMonitor, dry_run: bool = False) -> int:
    """Run a single monitoring check and send alerts.

    Args:
        monitor: The monitor instance to use.
        dry_run: If True, don't send alerts, just log what would be sent.

    Returns:
        Number of alerts sent (or would be sent in dry run).
    """
    # Get new alerts only (not previously alerted)
    # Returns list of (assessment, alert_id) tuples
    alert_tuples = monitor.check_new_alerts()

    if not alert_tuples:
        logger.info("No new alerts to send")
        return 0

    logger.info(f"Found {len(alert_tuples)} new alert(s) to send")

    if dry_run:
        for assessment, alert_id in alert_tuples:
            logger.info(
                f"[DRY RUN] Would alert: {assessment.patient.name} - "
                f"{assessment.medication.medication_name} "
                f"({assessment.duration_hours:.1f}h) [ID: {alert_id}]"
            )
        return len(alert_tuples)

    # Initialize alerters
    email_alerter = EmailAlerter()
    teams_alerter = TeamsAlerter()

    sent_count = 0
    for assessment, alert_id in alert_tuples:
        logger.info(
            f"Sending alert: {assessment.patient.name} - "
            f"{assessment.medication.medication_name} [ID: {alert_id}]"
        )

        sent_via_channel = False

        # Send via all configured channels
        if email_alerter.is_configured():
            if email_alerter.send_alert(assessment):
                sent_via_channel = True

        if teams_alerter.is_configured():
            if teams_alerter.send_alert(assessment, alert_id=alert_id):
                sent_via_channel = True

        # Mark alert as sent in store if any channel succeeded
        if sent_via_channel and alert_id:
            monitor.mark_alert_sent(alert_id)
            sent_count += 1

    return sent_count


def run_daemon(monitor: BroadSpectrumMonitor) -> None:
    """Run continuously, checking at configured intervals."""
    poll_interval = config.POLL_INTERVAL
    logger.info(f"Starting daemon mode (poll interval: {poll_interval}s)")

    while True:
        try:
            run_once(monitor)
        except Exception as e:
            logger.exception(f"Error during monitoring check: {e}")

        logger.info(f"Sleeping for {poll_interval} seconds...")
        time.sleep(poll_interval)


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor broad-spectrum antibiotic usage and send alerts."
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run once and exit (default: continuous polling)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't send alerts, just log what would be sent",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Check all patients (including previously alerted)",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Print configuration
    logger.info("Antimicrobial Usage Alert Monitor")
    logger.info(f"  Threshold: {config.ALERT_THRESHOLD_HOURS} hours")
    logger.info(f"  Monitored: {list(config.MONITORED_MEDICATIONS.values())}")
    logger.info(f"  FHIR URL: {config.get_fhir_base_url()}")

    # Check alerter configuration
    email_alerter = EmailAlerter()
    teams_alerter = TeamsAlerter()

    if email_alerter.is_configured():
        logger.info("  Email: configured")
    else:
        logger.info("  Email: not configured")

    if teams_alerter.is_configured():
        logger.info("  Teams: configured")
    else:
        logger.info("  Teams: not configured")

    # Initialize monitor
    monitor = BroadSpectrumMonitor()

    if args.once:
        if args.all:
            # Check all patients
            assessments = monitor.check_all_patients()
            if assessments:
                logger.info(f"Found {len(assessments)} patient(s) exceeding threshold")
                for assessment in assessments:
                    print(f"\n{assessment.patient.name} ({assessment.patient.mrn})")
                    print(f"  {assessment.medication.medication_name}: {assessment.duration_hours:.1f}h")
                    print(f"  Severity: {assessment.severity.value}")
            else:
                logger.info("No patients exceeding threshold")
            return 0
        else:
            sent = run_once(monitor, dry_run=args.dry_run)
            return 0 if sent >= 0 else 1
    else:
        try:
            run_daemon(monitor)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
