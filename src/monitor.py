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


class BacteremiaMonitor:
    """Monitors blood cultures and checks antibiotic coverage."""

    def __init__(self, alerter=None, lookback_hours: int = 24):
        self.fhir = get_fhir_client()
        self.alerter = alerter or create_alerter_from_config()
        self.lookback_hours = lookback_hours
        self.processed_cultures: set[str] = set()

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

    def check_culture(self, culture_report: dict) -> bool:
        """
        Check a single culture result for coverage issues.

        Returns True if an alert was generated.
        """
        culture = self._parse_culture(culture_report)

        # Skip if already processed
        if culture.fhir_id in self.processed_cultures:
            return False

        self.processed_cultures.add(culture.fhir_id)

        # Skip if no organism or gram stain info
        if not culture.organism and not culture.gram_stain:
            return False

        # Get patient info
        if not culture.patient_id:
            print(f"  Warning: Culture {culture.fhir_id} has no patient reference")
            return False

        patient_resource = self.fhir.get_patient(culture.patient_id)
        if not patient_resource:
            print(f"  Warning: Patient {culture.patient_id} not found")
            return False

        patient = self._parse_patient(patient_resource)

        # Get active antibiotics
        med_requests = self.fhir.get_active_medication_requests(culture.patient_id)
        antibiotics = [self._parse_medication_request(mr) for mr in med_requests]

        # Assess coverage
        assessment = assess_coverage(patient, culture, antibiotics)

        # Generate alert if needed
        if should_alert(assessment):
            self.alerter.send_alert(assessment)
            return True

        return False

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
                if self.check_culture(culture):
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
