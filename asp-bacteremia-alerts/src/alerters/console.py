"""Console alerter for development and testing."""

from datetime import datetime
from .base import BaseAlerter
from ..models import CoverageAssessment


class ConsoleAlerter(BaseAlerter):
    """Prints alerts to console - useful for development."""

    def __init__(self):
        self.alert_count = 0
        self.alerts: list[dict] = []

    def send_alert(
        self,
        assessment: CoverageAssessment,
        alert_id: str | None = None,
    ) -> bool:
        """Print alert to console."""
        self.alert_count += 1

        current_abx = [a.medication_name for a in assessment.current_antibiotics]

        alert_record = {
            "timestamp": datetime.now().isoformat(),
            "alert_id": alert_id,
            "patient_name": assessment.patient.name,
            "mrn": assessment.patient.mrn,
            "location": assessment.patient.location,
            "organism": assessment.culture.organism,
            "gram_stain": assessment.culture.gram_stain,
            "current_antibiotics": current_abx,
            "recommendation": assessment.recommendation,
            "missing_coverage": assessment.missing_coverage,
        }
        self.alerts.append(alert_record)

        print("\n" + "=" * 70)
        print("BACTEREMIA COVERAGE ALERT")
        if alert_id:
            print(f"  Alert ID:    {alert_id}")
        print("=" * 70)
        print(f"  Patient:     {assessment.patient.name} ({assessment.patient.mrn})")
        print(f"  Location:    {assessment.patient.location or 'Unknown'}")
        print(f"  Organism:    {assessment.culture.organism or 'Pending'}")
        if assessment.culture.gram_stain:
            print(f"  Gram Stain:  {assessment.culture.gram_stain}")
        print(f"  Current Abx: {', '.join(current_abx) if current_abx else 'None'}")
        print(f"  Status:      {assessment.coverage_status.value.upper()}")
        print(f"  Recommend:   {assessment.recommendation}")
        if assessment.missing_coverage:
            print(f"  Missing:     {', '.join(assessment.missing_coverage)}")
        print("=" * 70 + "\n")

        return True

    def get_alert_count(self) -> int:
        """Return number of alerts sent."""
        return self.alert_count

    def get_alerts(self) -> list[dict]:
        """Return all alerts sent (for testing)."""
        return self.alerts.copy()
