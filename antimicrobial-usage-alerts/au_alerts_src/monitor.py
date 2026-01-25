"""Broad-spectrum antibiotic usage monitor.

Monitors active medication orders for meropenem and vancomycin,
alerting when usage exceeds the configured threshold (default 72 hours).
"""

import logging
from datetime import datetime

from .config import config
from .fhir_client import FHIRClient, get_fhir_client
from .models import Patient, MedicationOrder, UsageAssessment, AlertSeverity

from common.alert_store import AlertStore, AlertType, AlertStatus

logger = logging.getLogger(__name__)


class BroadSpectrumMonitor:
    """Monitors broad-spectrum antibiotic usage duration."""

    def __init__(
        self,
        fhir_client: FHIRClient | None = None,
        alert_store: AlertStore | None = None,
    ):
        self.fhir_client = fhir_client or get_fhir_client()
        self.threshold_hours = config.ALERT_THRESHOLD_HOURS
        self.alert_store = alert_store or AlertStore(db_path=config.ALERT_DB_PATH)
        self._alerted_orders: set[str] = set()  # In-memory fallback cache

    def check_all_patients(self) -> list[UsageAssessment]:
        """Check all patients with monitored medications.

        Returns:
            List of UsageAssessment objects for orders exceeding threshold.
        """
        assessments = []

        # Get all active orders for monitored medications
        orders = self.fhir_client.get_monitored_medications()
        logger.info(f"Found {len(orders)} active monitored medication orders")

        for order in orders:
            assessment = self._assess_order(order)
            if assessment and assessment.exceeds_threshold:
                assessments.append(assessment)

        logger.info(f"Found {len(assessments)} orders exceeding {self.threshold_hours}h threshold")
        return assessments

    def check_new_alerts(self) -> list[tuple[UsageAssessment, str]]:
        """Check for new alerts (orders not previously alerted).

        Returns:
            List of (UsageAssessment, alert_id) tuples for new alerts only.
        """
        all_assessments = self.check_all_patients()

        new_alerts = []
        for assessment in all_assessments:
            order_id = assessment.medication.fhir_id

            # Check persistent store first (include resolved to prevent re-alerting)
            if self.alert_store.check_if_alerted(
                AlertType.BROAD_SPECTRUM_USAGE,
                order_id,
                include_resolved=True,
            ):
                continue

            # Also check in-memory cache (for same-session duplicates)
            if order_id in self._alerted_orders:
                continue

            # Create alert in store
            try:
                stored_alert = self.alert_store.save_alert(
                    alert_type=AlertType.BROAD_SPECTRUM_USAGE,
                    source_id=order_id,
                    severity=assessment.severity.value,
                    patient_id=assessment.patient.fhir_id,
                    patient_mrn=assessment.patient.mrn,
                    patient_name=assessment.patient.name,
                    title=f"Broad-Spectrum Alert: {assessment.medication.medication_name}",
                    summary=f"{assessment.medication.medication_name} > {assessment.threshold_hours}h",
                    content={
                        "medication_name": assessment.medication.medication_name,
                        "duration_hours": assessment.duration_hours,
                        "threshold_hours": assessment.threshold_hours,
                        "recommendation": assessment.recommendation,
                        "location": assessment.patient.location,
                        "department": assessment.patient.department,
                    },
                )
                new_alerts.append((assessment, stored_alert.id))
                self._alerted_orders.add(order_id)
            except Exception as e:
                logger.error(f"Failed to save alert for order {order_id}: {e}")
                # Still include in alerts but without stored ID
                new_alerts.append((assessment, None))
                self._alerted_orders.add(order_id)

        logger.info(f"Found {len(new_alerts)} new alerts")
        return new_alerts

    def mark_alert_sent(self, alert_id: str) -> bool:
        """Mark an alert as successfully sent."""
        if alert_id:
            return self.alert_store.mark_sent(alert_id)
        return False

    def clear_alert_history(self) -> None:
        """Clear the set of alerted orders (useful for testing)."""
        self._alerted_orders.clear()

    def _assess_order(self, order: MedicationOrder) -> UsageAssessment | None:
        """Assess a single medication order.

        Args:
            order: The medication order to assess.

        Returns:
            UsageAssessment if order can be assessed, None if missing data.
        """
        duration_hours = order.duration_hours
        if duration_hours is None:
            logger.warning(f"Order {order.fhir_id} has no start date, skipping")
            return None

        # Get patient info
        patient = self.fhir_client.get_patient(order.patient_id)
        if not patient:
            logger.warning(f"Could not find patient {order.patient_id} for order {order.fhir_id}")
            # Create minimal patient record
            patient = Patient(
                fhir_id=order.patient_id,
                mrn="Unknown",
                name="Unknown Patient",
            )

        exceeds = duration_hours >= self.threshold_hours

        # Determine severity based on how much threshold is exceeded
        if duration_hours >= self.threshold_hours * 2:  # 144+ hours
            severity = AlertSeverity.CRITICAL
        elif exceeds:
            severity = AlertSeverity.WARNING
        else:
            severity = AlertSeverity.INFO

        # Generate recommendation
        recommendation = self._generate_recommendation(order, duration_hours)

        return UsageAssessment(
            patient=patient,
            medication=order,
            duration_hours=duration_hours,
            threshold_hours=self.threshold_hours,
            exceeds_threshold=exceeds,
            recommendation=recommendation,
            severity=severity,
        )

    def _generate_recommendation(
        self,
        order: MedicationOrder,
        duration_hours: float,
    ) -> str:
        """Generate a recommendation based on the medication and duration."""
        days = duration_hours / 24
        med_name = order.medication_name

        if duration_hours >= self.threshold_hours * 2:
            return (
                f"{med_name} has been active for {days:.1f} days ({duration_hours:.0f} hours). "
                f"Urgent: Please review for de-escalation or discontinuation. "
                f"Consider culture results and clinical response."
            )
        else:
            return (
                f"{med_name} has exceeded {self.threshold_hours} hours (currently {days:.1f} days). "
                f"Consider reviewing antibiotic necessity and potential de-escalation based on "
                f"culture and sensitivity results."
            )


def run_monitor() -> list[UsageAssessment]:
    """Convenience function to run a single monitoring check.

    Returns:
        List of UsageAssessment objects for orders exceeding threshold.
    """
    monitor = BroadSpectrumMonitor()
    return monitor.check_all_patients()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("Running broad-spectrum antibiotic usage monitor...")
    print(f"Threshold: {config.ALERT_THRESHOLD_HOURS} hours")
    print(f"Monitored medications: {list(config.MONITORED_MEDICATIONS.values())}")
    print()

    assessments = run_monitor()

    if not assessments:
        print("No patients found exceeding threshold.")
    else:
        print(f"Found {len(assessments)} patient(s) exceeding threshold:\n")
        for assessment in assessments:
            print(f"Patient: {assessment.patient.name} (MRN: {assessment.patient.mrn})")
            print(f"  Location: {assessment.patient.location or 'Unknown'}")
            print(f"  Medication: {assessment.medication.medication_name}")
            print(f"  Duration: {assessment.duration_hours:.1f} hours ({assessment.duration_hours/24:.1f} days)")
            print(f"  Severity: {assessment.severity.value}")
            print(f"  Recommendation: {assessment.recommendation}")
            print()
