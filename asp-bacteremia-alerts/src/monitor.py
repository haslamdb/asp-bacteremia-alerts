#!/usr/bin/env python3
"""Blood culture monitoring service.

Polls FHIR server for new blood culture results and checks
if patients have adequate antibiotic coverage.
"""

import time
from datetime import datetime, timedelta

from .alerters import create_alerter_from_config, MultiChannelAlerter
from .fhir_client import get_fhir_client
from .matcher import assess_coverage, should_alert
from .models import Antibiotic, CultureResult, Patient
from .config import config

from common.alert_store import AlertStore, AlertType, AlertStatus


class BacteremiaMonitor:
    """Monitors blood cultures and checks antibiotic coverage."""

    def __init__(
        self,
        alerter=None,
        lookback_hours: int = 24,
        alert_store: AlertStore | None = None,
    ):
        self.fhir = get_fhir_client()
        self.alerter = alerter or create_alerter_from_config()
        self.lookback_hours = lookback_hours
        self.alert_store = alert_store or AlertStore(db_path=config.ALERT_DB_PATH)
        self.processed_cultures: set[str] = set()  # In-memory cache

    def _parse_patient(self, patient_resource: dict) -> Patient:
        """Parse FHIR Patient resource into model."""
        # Extract MRN
        mrn = "Unknown"
        for identifier in patient_resource.get("identifier", []):
            if "mrn" in identifier.get("system", "").lower():
                mrn = identifier.get("value", mrn)
                break
            mrn = identifier.get("value", mrn)

        # Extract name
        name = "Unknown"
        for name_entry in patient_resource.get("name", []):
            given = " ".join(name_entry.get("given", []))
            family = name_entry.get("family", "")
            name = f"{given} {family}".strip() or name
            break

        return Patient(
            fhir_id=patient_resource.get("id", ""),
            mrn=mrn,
            name=name,
            birth_date=patient_resource.get("birthDate"),
            gender=patient_resource.get("gender"),
        )

    def _parse_culture(self, report: dict) -> CultureResult:
        """Parse FHIR DiagnosticReport into CultureResult model."""
        organism = None
        gram_stain = None

        # Extract organism from conclusion
        conclusion = report.get("conclusion", "")
        if conclusion:
            # Check for gram stain in conclusion
            if "gram" in conclusion.lower():
                parts = conclusion.split(".")
                for part in parts:
                    if "gram" in part.lower():
                        gram_stain = part.strip()
                    else:
                        organism = part.strip() if part.strip() else organism
            else:
                organism = conclusion

        # Also check conclusionCode
        for code_entry in report.get("conclusionCode", []):
            text = code_entry.get("text", "")
            if text and text != "Pending identification":
                organism = text
            for coding in code_entry.get("coding", []):
                if not organism or organism == "Pending identification":
                    organism = coding.get("display")

        # Extract patient reference
        patient_ref = report.get("subject", {}).get("reference", "")
        patient_id = patient_ref.replace("Patient/", "") if patient_ref else ""

        # Parse dates
        collected_date = None
        resulted_date = None
        if report.get("effectiveDateTime"):
            try:
                collected_date = datetime.fromisoformat(
                    report["effectiveDateTime"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass
        if report.get("issued"):
            try:
                resulted_date = datetime.fromisoformat(
                    report["issued"].replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                pass

        return CultureResult(
            fhir_id=report.get("id", ""),
            patient_id=patient_id,
            organism=organism,
            gram_stain=gram_stain,
            status=report.get("status", "final"),
            collected_date=collected_date,
            resulted_date=resulted_date,
        )

    def _parse_medication_request(self, med_request: dict) -> Antibiotic:
        """Parse FHIR MedicationRequest into Antibiotic model."""
        medication_name = "Unknown"
        rxnorm_code = None

        # Extract medication info
        med_concept = med_request.get("medicationCodeableConcept", {})
        medication_name = med_concept.get("text", medication_name)

        for coding in med_concept.get("coding", []):
            if "rxnorm" in coding.get("system", "").lower():
                rxnorm_code = coding.get("code")
                if not medication_name or medication_name == "Unknown":
                    medication_name = coding.get("display", medication_name)

        # Extract route
        route = None
        for dosage in med_request.get("dosageInstruction", []):
            route_info = dosage.get("route", {})
            for coding in route_info.get("coding", []):
                route = coding.get("display")
                break

        return Antibiotic(
            fhir_id=med_request.get("id", ""),
            medication_name=medication_name,
            rxnorm_code=rxnorm_code,
            route=route,
            status=med_request.get("status", "active"),
        )

    def check_culture(self, culture_report: dict) -> tuple[bool, str | None]:
        """
        Check a single culture result for coverage issues.

        Returns:
            Tuple of (alert_generated, alert_id)
        """
        culture = self._parse_culture(culture_report)

        # Skip if already processed in memory
        if culture.fhir_id in self.processed_cultures:
            return False, None

        # Check persistent store
        if self.alert_store.check_if_alerted(AlertType.BACTEREMIA, culture.fhir_id):
            self.processed_cultures.add(culture.fhir_id)
            return False, None

        self.processed_cultures.add(culture.fhir_id)

        # Skip if no organism or gram stain info
        if not culture.organism and not culture.gram_stain:
            return False, None

        # Get patient info
        if not culture.patient_id:
            print(f"  Warning: Culture {culture.fhir_id} has no patient reference")
            return False, None

        patient_resource = self.fhir.get_patient(culture.patient_id)
        if not patient_resource:
            print(f"  Warning: Patient {culture.patient_id} not found")
            return False, None

        patient = self._parse_patient(patient_resource)

        # Get active antibiotics
        med_requests = self.fhir.get_active_medication_requests(culture.patient_id)
        antibiotics = [self._parse_medication_request(mr) for mr in med_requests]

        # Assess coverage
        assessment = assess_coverage(patient, culture, antibiotics)

        # Generate alert if needed
        if should_alert(assessment):
            # Create alert in store
            alert_id = None
            try:
                stored_alert = self.alert_store.save_alert(
                    alert_type=AlertType.BACTEREMIA,
                    source_id=culture.fhir_id,
                    severity=assessment.coverage_status.value,
                    patient_id=patient.fhir_id,
                    patient_mrn=patient.mrn,
                    patient_name=patient.name,
                    title=f"Bacteremia Alert: {culture.organism or 'Unknown organism'}",
                    summary=f"Coverage: {assessment.coverage_status.value}",
                    content={
                        "organism": culture.organism,
                        "gram_stain": culture.gram_stain,
                        "coverage_status": assessment.coverage_status.value,
                        "recommendation": assessment.recommendation,
                        "current_antibiotics": [a.medication_name for a in antibiotics],
                        "location": patient.location,
                    },
                )
                alert_id = stored_alert.id
            except Exception as e:
                print(f"  Warning: Failed to save alert to store: {e}")

            # Send alert
            if self.alerter.send_alert(assessment, alert_id=alert_id):
                # Mark as sent
                if alert_id:
                    self.alert_store.mark_sent(alert_id)
                return True, alert_id

        return False, None

    def run_once(self) -> int:
        """
        Run a single check cycle.

        Returns the number of alerts generated.
        """
        print(f"\n[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Checking for new blood cultures...")

        # Get recent blood culture results
        cultures = self.fhir.get_recent_blood_cultures(
            hours_back=self.lookback_hours,
        )

        print(f"  Found {len(cultures)} blood culture(s) in the last {self.lookback_hours} hours")

        alerts_generated = 0
        for culture in cultures:
            try:
                alerted, alert_id = self.check_culture(culture)
                if alerted:
                    alerts_generated += 1
            except Exception as e:
                print(f"  Error processing culture {culture.get('id', 'unknown')}: {e}")

        if alerts_generated:
            print(f"  Generated {alerts_generated} alert(s)")
        else:
            print("  No coverage issues detected")

        return alerts_generated

    def run_continuous(self, interval_seconds: int | None = None):
        """
        Run continuous monitoring loop.

        Args:
            interval_seconds: Seconds between checks (default from config)
        """
        interval = interval_seconds or config.POLL_INTERVAL
        print("=" * 60)
        print("ASP Bacteremia Monitor - Starting")
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
            print(f"Total alerts generated: {self.alerter.get_alert_count()}")


def main():
    """Main entry point."""
    monitor = BacteremiaMonitor()

    # For testing, run once with short lookback
    # For production, use run_continuous()
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == "--continuous":
        monitor.run_continuous()
    else:
        # Single run for testing
        monitor.run_once()

        # Print summary
        if isinstance(monitor.alerter, MultiChannelAlerter):
            monitor.alerter.print_summary()
        else:
            print(f"\nTotal alerts: {monitor.alerter.get_alert_count()}")


if __name__ == "__main__":
    main()
