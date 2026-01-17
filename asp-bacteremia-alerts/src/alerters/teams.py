"""Teams alerter using shared webhook channel."""

from datetime import datetime

from .base import BaseAlerter
from ..models import CoverageAssessment
from ..config import config  # This adds common to sys.path
from common.channels import TeamsWebhookChannel


class TeamsAlerter(BaseAlerter):
    """Send alerts to Microsoft Teams via webhook."""

    def __init__(
        self,
        webhook_url: str | None = None,
        include_phi: bool = True,
    ):
        """
        Initialize Teams alerter.

        Args:
            webhook_url: Teams incoming webhook URL (or from env TEAMS_WEBHOOK_URL)
            include_phi: Whether to include patient details in message
        """
        url = webhook_url or config.TEAMS_WEBHOOK_URL

        self.channel = TeamsWebhookChannel(webhook_url=url) if url else None
        self.include_phi = include_phi
        self.alert_count = 0
        self.alerts: list[dict] = []

    def send_alert(self, assessment: CoverageAssessment) -> bool:
        """Send alert to Teams channel."""
        if not self.channel:
            print("  Teams: Webhook URL not configured")
            return False

        # Build facts for the card
        current_abx = [a.medication_name for a in assessment.current_antibiotics]
        abx_list = ", ".join(current_abx) if current_abx else "None"

        if self.include_phi:
            facts = [
                ("Patient", f"{assessment.patient.name} ({assessment.patient.mrn})"),
                ("Location", assessment.patient.location or "Unknown"),
                ("Organism", assessment.culture.organism or "Pending identification"),
                ("Current Antibiotics", abx_list),
                ("Coverage Status", assessment.coverage_status.value.upper()),
            ]
            if assessment.culture.gram_stain:
                facts.insert(3, ("Gram Stain", assessment.culture.gram_stain))
        else:
            facts = [
                ("Alert Type", "Bacteremia Coverage Concern"),
                ("Status", "Action Required"),
            ]

        title = "Bacteremia Coverage Alert"
        text = f"**Recommendation:** {assessment.recommendation}"

        # Use red theme for alerts
        if self.channel.send_card(
            title=title,
            facts=facts,
            text=text,
            theme_color="d63333",
        ):
            self.alert_count += 1
            self.alerts.append({
                "timestamp": datetime.now().isoformat(),
                "mrn": assessment.patient.mrn if self.include_phi else "redacted",
            })
            return True
        return False

    def get_alert_count(self) -> int:
        """Return number of alerts sent."""
        return self.alert_count

    def is_configured(self) -> bool:
        """Check if Teams alerting is properly configured."""
        return self.channel is not None and self.channel.is_configured()
