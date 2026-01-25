"""Main runner for Antimicrobial Usage Alerts.

Monitors for:
1. Broad-spectrum antibiotic usage exceeding threshold (duration monitoring)
2. Antibiotic orders without documented indications (indication monitoring)

Both monitors send alerts to the ASP alerts queue.
"""

import argparse
import logging
import time
import sys

from .config import config
from .monitor import BroadSpectrumMonitor
from .indication_monitor import IndicationMonitor
from .llm_extractor import get_indication_extractor
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
            if email_alerter.send_alert(assessment, alert_id=alert_id):
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


def run_indication_once(dry_run: bool = False, use_llm: bool = True) -> int:
    """Run indication monitor once.

    Args:
        dry_run: If True, don't create alerts.
        use_llm: If True, use LLM for extraction (if available).

    Returns:
        Number of alerts found.
    """
    # Get LLM extractor if requested
    llm_extractor = None
    if use_llm:
        llm_extractor = get_indication_extractor()
        if llm_extractor:
            logger.info("LLM extractor available - will attempt note extraction for N/U")
        else:
            logger.info("LLM extractor not available - using ICD-10 only")

    # Initialize monitor
    monitor = IndicationMonitor(llm_extractor=llm_extractor)

    # Get new alerts
    alert_tuples = monitor.check_new_alerts()

    if not alert_tuples:
        logger.info("No new indication alerts")
        return 0

    logger.info(f"Found {len(alert_tuples)} new indication alert(s)")

    if dry_run:
        for assessment, alert_id in alert_tuples:
            logger.info(
                f"[DRY RUN] Would alert: {assessment.candidate.patient.name} - "
                f"{assessment.candidate.medication.medication_name} "
                f"(classification: {assessment.candidate.final_classification})"
            )
        return len(alert_tuples)

    # Mark alerts as sent
    sent_count = 0
    for assessment, alert_id in alert_tuples:
        if alert_id:
            monitor.mark_alert_sent(alert_id)
            sent_count += 1

    return sent_count


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Monitor antibiotic usage and indications, send ASP alerts."
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

    # Monitor selection
    monitor_group = parser.add_mutually_exclusive_group()
    monitor_group.add_argument(
        "--indication",
        action="store_true",
        help="Run indication monitor only (default: broad-spectrum duration)",
    )
    monitor_group.add_argument(
        "--both",
        action="store_true",
        help="Run both broad-spectrum and indication monitors",
    )

    # Indication monitor options
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Skip LLM extraction for indication monitoring",
    )

    args = parser.parse_args()
    setup_logging(args.verbose)

    # Print configuration
    logger.info("Antimicrobial Usage Alert Monitor")
    logger.info(f"  FHIR URL: {config.get_fhir_base_url()}")

    if args.indication:
        logger.info("  Mode: Indication monitoring only")
    elif args.both:
        logger.info("  Mode: Both broad-spectrum and indication")
    else:
        logger.info("  Mode: Broad-spectrum duration monitoring")
        logger.info(f"  Threshold: {config.ALERT_THRESHOLD_HOURS} hours")
        logger.info(f"  Monitored: {list(config.MONITORED_MEDICATIONS.values())}")

    # Check alerter configuration
    email_alerter = EmailAlerter()
    teams_alerter = TeamsAlerter()

    if email_alerter.is_configured():
        logger.info("  Email: configured")
    if teams_alerter.is_configured():
        logger.info("  Teams: configured")

    # Run appropriate monitor(s)
    if args.once:
        total_alerts = 0

        # Run indication monitor if requested
        if args.indication or args.both:
            logger.info("\n--- Running Indication Monitor ---")
            count = run_indication_once(
                dry_run=args.dry_run,
                use_llm=not args.no_llm,
            )
            total_alerts += count
            logger.info(f"Indication monitor: {count} new alert(s)")

        # Run broad-spectrum monitor if requested
        if not args.indication or args.both:
            logger.info("\n--- Running Broad-Spectrum Monitor ---")
            monitor = BroadSpectrumMonitor()

            if args.all:
                assessments = monitor.check_all_patients()
                if assessments:
                    logger.info(f"Found {len(assessments)} patient(s) exceeding threshold")
                    for assessment in assessments:
                        print(f"\n{assessment.patient.name} ({assessment.patient.mrn})")
                        print(f"  {assessment.medication.medication_name}: {assessment.duration_hours:.1f}h")
                        print(f"  Severity: {assessment.severity.value}")
                else:
                    logger.info("No patients exceeding threshold")
            else:
                count = run_once(monitor, dry_run=args.dry_run)
                total_alerts += count
                logger.info(f"Broad-spectrum monitor: {count} new alert(s)")

        logger.info(f"\nTotal new alerts: {total_alerts}")
        return 0

    else:
        # Daemon mode - only broad-spectrum for now
        if args.indication:
            logger.error("Daemon mode not supported for indication monitor")
            logger.info("Use cron with --indication --once instead")
            return 1

        monitor = BroadSpectrumMonitor()
        try:
            run_daemon(monitor)
        except KeyboardInterrupt:
            logger.info("Shutting down...")
            return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
