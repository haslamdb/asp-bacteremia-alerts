"""Drug-Bug Mismatch monitoring service.

Polls FHIR server for cultures with susceptibilities and checks
if patients have adequate antibiotic coverage.
"""

import time
from datetime import datetime

from .config import config
from .fhir_client import DrugBugFHIRClient, get_fhir_client
from .matcher import assess_mismatch, should_alert
from .models import AlertSeverity

from common.alert_store import AlertStore, AlertType, AlertStatus


class DrugBugMismatchMonitor:
    """Monitors cultures for drug-bug mismatches."""

    def __init__(
        self,
        fhir_client: DrugBugFHIRClient | None = None,
        alert_store: AlertStore | None = None,
        lookback_hours: int | None = None,
    ):
        self.fhir = fhir_client or DrugBugFHIRClient()
        self.alert_store = alert_store or AlertStore(db_path=config.ALERT_DB_PATH)
        self.lookback_hours = lookback_hours or config.LOOKBACK_HOURS
        self.processed_cultures: set[str] = set()  # In-memory cache
        self.alerts_generated = 0

    def check_culture(self, culture) -> tuple[bool, str | None]:
        """
        Check a single culture for drug-bug mismatches.

        Returns:
            Tuple of (alert_generated, alert_id)
        """
        # Skip if already processed in memory
        if culture.fhir_id in self.processed_cultures:
            return False, None

        # Check persistent store (include resolved to prevent re-alerting)
        if self.alert_store.check_if_alerted(
            AlertType.DRUG_BUG_MISMATCH,
            culture.fhir_id,
            include_resolved=True,
        ):
            self.processed_cultures.add(culture.fhir_id)
            return False, None

        self.processed_cultures.add(culture.fhir_id)

        # Skip if no susceptibility data
        if not culture.susceptibilities:
            print(f"  Skipping culture {culture.fhir_id}: no susceptibility data")
            return False, None

        # Get patient info
        if not culture.patient_id:
            print(f"  Warning: Culture {culture.fhir_id} has no patient reference")
            return False, None

        patient = self.fhir.get_patient(culture.patient_id)
        if not patient:
            print(f"  Warning: Patient {culture.patient_id} not found")
            return False, None

        # Get active antibiotics
        antibiotics = self.fhir.get_current_antibiotics(culture.patient_id)

        # Assess coverage
        assessment = assess_mismatch(patient, culture, antibiotics)

        # Generate alert if needed
        if should_alert(assessment):
            alert_id = self._create_alert(assessment)
            return True, alert_id

        return False, None

    def _create_alert(self, assessment) -> str | None:
        """Create and save alert for a mismatch assessment."""
        alert_id = None
        patient = assessment.patient
        culture = assessment.culture

        # Determine severity string
        severity_map = {
            AlertSeverity.CRITICAL: "critical",
            AlertSeverity.WARNING: "warning",
            AlertSeverity.INFO: "info",
        }
        severity = severity_map.get(assessment.severity, "warning")

        # Build title
        mismatch_type = "Mismatch"
        if assessment.mismatches:
            first_mismatch = assessment.mismatches[0]
            mismatch_type = first_mismatch.mismatch_type.value.replace("_", " ").title()

        title = f"Drug-Bug Mismatch: {culture.organism} ({mismatch_type})"

        # Build summary
        resistant_abx = [
            m.antibiotic.medication_name
            for m in assessment.mismatches
            if m.mismatch_type.value == "resistant"
        ]
        if resistant_abx:
            summary = f"Resistant to {', '.join(resistant_abx)}"
        else:
            summary = assessment.recommendation[:100]

        try:
            stored_alert = self.alert_store.save_alert(
                alert_type=AlertType.DRUG_BUG_MISMATCH,
                source_id=culture.fhir_id,
                severity=severity,
                patient_id=patient.fhir_id,
                patient_mrn=patient.mrn,
                patient_name=patient.name,
                title=title,
                summary=summary,
                content=assessment.to_alert_content(),
            )
            alert_id = stored_alert.id
            print(f"  Created alert {alert_id[:8]}... for {patient.name} ({patient.mrn})")
            self.alerts_generated += 1
        except Exception as e:
            print(f"  Warning: Failed to save alert: {e}")

        return alert_id

    def run_once(self) -> int:
        """
        Run a single check cycle.

        Returns the number of alerts generated this cycle.
        """
        print(
            f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] "
            f"Checking for drug-bug mismatches..."
        )

        # Get recent cultures with susceptibilities
        cultures = self.fhir.get_cultures_with_susceptibilities(
            hours_back=self.lookback_hours
        )

        print(
            f"  Found {len(cultures)} culture(s) with susceptibilities "
            f"in the last {self.lookback_hours} hours"
        )

        cycle_alerts = 0
        for culture in cultures:
            try:
                print(f"  Checking: {culture.organism} (Culture {culture.fhir_id[:8]}...)")
                alerted, alert_id = self.check_culture(culture)
                if alerted:
                    cycle_alerts += 1
            except Exception as e:
                print(f"  Error processing culture {culture.fhir_id}: {e}")

        if cycle_alerts:
            print(f"  Generated {cycle_alerts} alert(s)")
        else:
            print("  No mismatches detected")

        return cycle_alerts

    def run_continuous(self, interval_seconds: int | None = None):
        """
        Run continuous monitoring loop.

        Args:
            interval_seconds: Seconds between checks (default from config)
        """
        interval = interval_seconds or config.POLL_INTERVAL

        print("=" * 60)
        print("Drug-Bug Mismatch Monitor - Starting")
        print("=" * 60)
        print(f"  FHIR Server: {config.get_fhir_base_url()}")
        print(f"  Poll Interval: {interval} seconds")
        print(f"  Lookback Window: {self.lookback_hours} hours")
        print("=" * 60)
        print("\nPress Ctrl+C to stop\n")

        try:
            while True:
                self.run_once()
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\nMonitor stopped by user")
            print(f"Total alerts generated: {self.alerts_generated}")

    def get_alert_count(self) -> int:
        """Return the number of alerts generated."""
        return self.alerts_generated


def main():
    """Main entry point for testing."""
    monitor = DrugBugMismatchMonitor()

    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--continuous":
        monitor.run_continuous()
    else:
        # Single run for testing
        monitor.run_once()
        print(f"\nTotal alerts: {monitor.get_alert_count()}")


if __name__ == "__main__":
    main()
