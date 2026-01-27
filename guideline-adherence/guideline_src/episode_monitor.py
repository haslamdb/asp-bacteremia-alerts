#!/usr/bin/env python3
"""Episode-based guideline adherence monitor.

This module monitors active episodes from the episode database and checks
for element completion, creating alerts when elements are overdue or not met.

Integrates with:
- episode_db.py: Reads active episodes created by bundle_monitor.py
- checkers/*: Uses element checkers to verify completion
- bundle_alerts table: Creates alerts for deviations

Usage:
    # Check all active episodes once
    python -m guideline_src.episode_monitor --once

    # Check continuously (daemon mode)
    python -m guideline_src.episode_monitor --daemon --interval 5

    # Dry run (no alerts created)
    python -m guideline_src.episode_monitor --once --dry-run --verbose
"""

import argparse
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

# Add paths for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from guideline_adherence import GUIDELINE_BUNDLES

from guideline_src.config import config
from guideline_src.episode_db import (
    EpisodeDB,
    BundleEpisode,
    ElementResult,
    BundleAlert,
)

logger = logging.getLogger(__name__)


class EpisodeAdherenceMonitor:
    """Monitors active episodes for guideline adherence.

    This monitor reads episodes from the episode database (created by
    BundleTriggerMonitor) and checks each element for completion.
    """

    def __init__(
        self,
        db: Optional[EpisodeDB] = None,
        fhir_client=None,
    ):
        """Initialize the episode monitor.

        Args:
            db: Episode database. Uses default if not provided.
            fhir_client: FHIR client for element checking. Mock if not provided.
        """
        self.db = db or EpisodeDB()
        self.fhir_client = fhir_client

        # Track which alerts we've already created
        self._alerted_elements: set[str] = set()

    def check_all_episodes(
        self,
        bundle_id: Optional[str] = None,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> list[dict]:
        """Check all active episodes for adherence.

        Args:
            bundle_id: Optional filter to specific bundle.
            dry_run: If True, don't create alerts.
            verbose: If True, print detailed output.

        Returns:
            List of episode summary dicts.
        """
        # Get active episodes
        episodes = self.db.get_active_episodes()

        if bundle_id:
            episodes = [e for e in episodes if e.bundle_id == bundle_id]

        if not episodes:
            logger.info("No active episodes to check")
            return []

        logger.info(f"Checking {len(episodes)} active episode(s)")

        results = []
        for episode in episodes:
            result = self._check_episode(episode, dry_run, verbose)
            results.append(result)

        return results

    def _check_episode(
        self,
        episode: BundleEpisode,
        dry_run: bool = False,
        verbose: bool = False,
    ) -> dict:
        """Check a single episode for adherence.

        Args:
            episode: The episode to check.
            dry_run: If True, don't create alerts.
            verbose: If True, print detailed info.

        Returns:
            Summary dict with episode and element status.
        """
        bundle = GUIDELINE_BUNDLES.get(episode.bundle_id)
        if not bundle:
            logger.warning(f"Unknown bundle: {episode.bundle_id}")
            return {"episode": episode, "error": "Unknown bundle"}

        # Get existing element results
        element_results = self.db.get_element_results(episode.id)

        # If no results exist, initialize them
        if not element_results:
            element_results = self._initialize_elements(episode, bundle)

        # Check each element
        now = datetime.now()
        met_count = 0
        not_met_count = 0
        pending_count = 0
        na_count = 0
        alerts_created = []

        for result in element_results:
            # Check if element is overdue
            if result.status == "pending" and result.deadline:
                if now > result.deadline:
                    # Element overdue - check if actually completed
                    completed = self._check_element_completion(episode, result)

                    if completed:
                        result.status = "met"
                        result.completed_at = now
                        self.db.save_element_result(result)
                    else:
                        result.status = "not_met"
                        result.notes = f"Overdue - deadline was {result.deadline.strftime('%H:%M')}"
                        self.db.save_element_result(result)

                        # Create alert if not dry run
                        if not dry_run:
                            alert_id = self._create_alert_if_new(episode, result)
                            if alert_id:
                                alerts_created.append(alert_id)

            # Count by status
            if result.status == "met":
                met_count += 1
            elif result.status == "not_met":
                not_met_count += 1
            elif result.status == "pending":
                pending_count += 1
            elif result.status == "na":
                na_count += 1

        # Update episode stats
        applicable = len(element_results) - na_count
        adherence_pct = (met_count / applicable * 100) if applicable > 0 else 0

        episode.elements_total = len(element_results)
        episode.elements_applicable = applicable
        episode.elements_met = met_count
        episode.elements_not_met = not_met_count
        episode.elements_pending = pending_count
        episode.adherence_percentage = adherence_pct

        if adherence_pct == 100:
            episode.adherence_level = "full"
        elif adherence_pct > 50:
            episode.adherence_level = "partial"
        else:
            episode.adherence_level = "low"

        # Mark complete if no pending elements
        if pending_count == 0:
            episode.status = "completed"
            episode.completed_at = now

        self.db.save_episode(episode)

        # Print verbose output
        if verbose:
            print(f"\nPatient: {episode.patient_mrn or episode.patient_id}")
            print(f"  Bundle: {episode.bundle_name}")
            print(f"  Trigger: {episode.trigger_time.strftime('%Y-%m-%d %H:%M') if episode.trigger_time else 'N/A'}")
            print(f"  Elements: {met_count} met, {not_met_count} not met, {pending_count} pending")
            print(f"  Adherence: {adherence_pct:.0f}% ({episode.adherence_level})")

            for result in element_results:
                icon = {"met": "✓", "not_met": "✗", "pending": "○", "na": "-"}.get(result.status, "?")
                deadline_str = f" (deadline: {result.deadline.strftime('%H:%M')})" if result.deadline else ""
                value_str = f" = {result.value}" if result.value else ""
                print(f"    [{icon}] {result.element_name}: {result.status}{value_str}{deadline_str}")

            if alerts_created:
                print(f"  Alerts created: {len(alerts_created)}")

        return {
            "episode_id": episode.id,
            "patient_mrn": episode.patient_mrn,
            "bundle_id": episode.bundle_id,
            "bundle_name": episode.bundle_name,
            "met": met_count,
            "not_met": not_met_count,
            "pending": pending_count,
            "adherence_pct": adherence_pct,
            "adherence_level": episode.adherence_level,
            "alerts_created": len(alerts_created),
        }

    def _initialize_elements(
        self,
        episode: BundleEpisode,
        bundle,
    ) -> list[ElementResult]:
        """Initialize element results for a new episode.

        Args:
            episode: The episode.
            bundle: The guideline bundle.

        Returns:
            List of ElementResult objects.
        """
        results = []
        trigger_time = episode.trigger_time or datetime.now()

        for element in bundle.elements:
            # Calculate deadline if time window specified
            deadline = None
            if element.time_window_hours:
                deadline = trigger_time + timedelta(hours=element.time_window_hours)

            # Check if element applies based on age
            is_applicable = self._element_applies_to_patient(element, episode)

            result = ElementResult(
                episode_id=episode.id,
                element_id=element.element_id,
                element_name=element.name,
                element_description=element.description,
                required=element.required,
                time_window_hours=element.time_window_hours,
                deadline=deadline,
                status="pending" if is_applicable else "na",
            )

            result_id = self.db.save_element_result(result)
            result.id = result_id
            results.append(result)

        return results

    def _element_applies_to_patient(
        self,
        element,
        episode: BundleEpisode,
    ) -> bool:
        """Check if an element applies based on patient age.

        Args:
            element: The bundle element.
            episode: The episode with patient context.

        Returns:
            True if element applies.
        """
        age_days = episode.patient_age_days

        # Check element ID for age-specific elements
        element_id = element.element_id.lower()

        # Febrile infant age groups
        if "8_21d" in element_id:
            return age_days is not None and 8 <= age_days <= 21
        if "22_28d" in element_id:
            return age_days is not None and 22 <= age_days <= 28
        if "29_60d" in element_id or "29-60" in element_id:
            return age_days is not None and 29 <= age_days <= 60

        # Neonatal HSV - only for <=21 days
        if episode.bundle_id == "neonatal_hsv_2024":
            return age_days is None or age_days <= 21

        # C. diff - age >=3 years
        if "cdiff_age" in element_id:
            age_years = (age_days or 0) / 365
            return age_years >= 3

        return True

    def _check_element_completion(
        self,
        episode: BundleEpisode,
        result: ElementResult,
    ) -> bool:
        """Check if an element has been completed via FHIR.

        In a real implementation, this would query FHIR for:
        - Lab results
        - Medication administrations
        - Procedure completions
        - Note documentation

        Args:
            episode: The episode.
            result: The element result.

        Returns:
            True if element is now completed.
        """
        if not self.fhir_client:
            # Without FHIR client, can't verify completion
            # Return False to mark as not met
            return False

        # TODO: Implement actual FHIR queries based on element type
        # For now, return False (not completed)
        return False

    def _create_alert_if_new(
        self,
        episode: BundleEpisode,
        result: ElementResult,
    ) -> Optional[int]:
        """Create an alert if not already created.

        Args:
            episode: The episode.
            result: The element result.

        Returns:
            Alert ID if created, None if already exists.
        """
        # Check if already alerted
        alert_key = f"{episode.id}_{result.element_id}"
        if alert_key in self._alerted_elements:
            return None

        # Determine severity
        element_id = result.element_id.lower()
        if "acyclovir" in element_id or "abx_1hr" in element_id or "abx_1h" in element_id:
            severity = "critical"
        elif "repeat" in element_id or "reassess" in element_id:
            severity = "warning"
        else:
            severity = "warning"

        # Create alert
        alert = BundleAlert(
            episode_id=episode.id,
            patient_id=episode.patient_id,
            patient_mrn=episode.patient_mrn,
            encounter_id=episode.encounter_id,
            bundle_id=episode.bundle_id,
            bundle_name=episode.bundle_name,
            element_id=result.element_id,
            element_name=result.element_name,
            alert_type="element_overdue" if result.deadline else "element_not_met",
            severity=severity,
            title=f"Guideline Deviation: {result.element_name}",
            message=self._generate_alert_message(episode, result),
        )

        alert_id = self.db.save_alert(alert)
        self._alerted_elements.add(alert_key)

        logger.info(
            f"Alert created [{severity.upper()}]: {episode.patient_mrn} - {result.element_name}"
        )

        return alert_id

    def _generate_alert_message(
        self,
        episode: BundleEpisode,
        result: ElementResult,
    ) -> str:
        """Generate alert message text.

        Args:
            episode: The episode.
            result: The element result.

        Returns:
            Alert message string.
        """
        bundle_name = episode.bundle_name
        element_name = result.element_name

        # Build message
        msg = f"{bundle_name}: {element_name} not completed"

        if result.deadline:
            msg += f" within required timeframe (deadline: {result.deadline.strftime('%Y-%m-%d %H:%M')})"

        if result.notes:
            msg += f". {result.notes}"

        # Add recommendation based on element
        recommendations = {
            "sepsis_abx_1hr": "Administer broad-spectrum antibiotics immediately.",
            "sepsis_repeat_lactate": "Obtain repeat lactate to assess treatment response.",
            "hsv_acyclovir_started": "Start IV acyclovir 20 mg/kg Q8H immediately.",
            "fi_lp_8_21d": "LP required for all febrile infants 8-21 days per AAP 2021.",
        }

        rec = recommendations.get(result.element_id)
        if rec:
            msg += f" Recommendation: {rec}"

        return msg

    def get_overdue_elements(self) -> list[tuple[BundleEpisode, ElementResult]]:
        """Get all overdue elements across active episodes.

        Returns:
            List of (episode, element_result) tuples.
        """
        overdue = self.db.get_overdue_elements()
        results = []

        for result in overdue:
            episode = self.db.get_episode(result.episode_id)
            if episode:
                results.append((episode, result))

        return results

    def print_status(self):
        """Print current monitoring status."""
        print("\n" + "=" * 70)
        print("GUIDELINE ADHERENCE MONITOR STATUS")
        print("=" * 70)

        # Active episodes
        episodes = self.db.get_active_episodes()
        print(f"\nActive Episodes: {len(episodes)}")

        if episodes:
            print("-" * 70)
            print(f"{'MRN':<15} {'Bundle':<25} {'Adherence':<12} {'Status':<10}")
            print("-" * 70)

            for ep in episodes:
                mrn = ep.patient_mrn or ep.patient_id[:12]
                bundle = (ep.bundle_name or ep.bundle_id)[:23]
                adherence = f"{ep.adherence_percentage or 0:.0f}%"
                level = ep.adherence_level or "unknown"
                print(f"{mrn:<15} {bundle:<25} {adherence:<12} {level:<10}")

        # Overdue elements
        overdue = self.get_overdue_elements()
        print(f"\nOverdue Elements: {len(overdue)}")

        if overdue:
            print("-" * 70)
            for episode, result in overdue[:10]:
                mrn = episode.patient_mrn or episode.patient_id[:12]
                deadline = result.deadline.strftime("%H:%M") if result.deadline else "N/A"
                print(f"  {mrn}: {result.element_name} (deadline: {deadline})")

        # Active alerts
        alerts = self.db.get_active_alerts()
        print(f"\nActive Alerts: {len(alerts)}")

        if alerts:
            print("-" * 70)
            for alert in alerts[:10]:
                mrn = alert.patient_mrn or alert.patient_id[:12]
                print(f"  [{alert.severity.upper():8}] {mrn}: {alert.title}")

        print()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Episode-based guideline adherence monitor"
    )

    parser.add_argument(
        "--once",
        action="store_true",
        help="Check all episodes once and exit",
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run continuously",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show current status and exit",
    )
    parser.add_argument(
        "--bundle",
        type=str,
        help="Filter to specific bundle ID",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=5,
        help="Check interval in minutes (default: 5)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't create alerts",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Verbose output",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        help="Override database path",
    )

    args = parser.parse_args()

    # Setup logging
    level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Initialize monitor
    db = EpisodeDB(args.db_path) if args.db_path else EpisodeDB()
    monitor = EpisodeAdherenceMonitor(db=db)

    if args.status:
        monitor.print_status()
        return

    if not (args.once or args.daemon):
        parser.error("Use --once, --daemon, or --status")

    # Run check
    print("\n" + "=" * 70)
    print("EPISODE ADHERENCE MONITOR")
    print("=" * 70)
    print(f"Mode: {'Single run' if args.once else 'Daemon'}")
    print(f"Dry run: {args.dry_run}")
    if args.bundle:
        print(f"Bundle filter: {args.bundle}")
    print("=" * 70)

    if args.once:
        results = monitor.check_all_episodes(
            bundle_id=args.bundle,
            dry_run=args.dry_run,
            verbose=args.verbose,
        )

        print(f"\nChecked {len(results)} episode(s)")

        total_alerts = sum(r.get("alerts_created", 0) for r in results)
        if total_alerts:
            print(f"Created {total_alerts} alert(s)")

    else:
        # Daemon mode
        print(f"Checking every {args.interval} minutes. Press Ctrl+C to stop.\n")

        try:
            while True:
                results = monitor.check_all_episodes(
                    bundle_id=args.bundle,
                    dry_run=args.dry_run,
                    verbose=args.verbose,
                )

                logger.info(f"Checked {len(results)} episodes")

                time.sleep(args.interval * 60)

        except KeyboardInterrupt:
            print("\nShutting down...")


if __name__ == "__main__":
    main()
