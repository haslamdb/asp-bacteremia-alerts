"""Teams alerter for bacteremia alerts using shared webhook channel.

Uses the Workflows / Power Automate webhook format with Adaptive Cards.
"""

from datetime import datetime

from .base import BaseAlerter
from ..models import CoverageAssessment
from ..config import config  # This adds common to sys.path
from common.channels import TeamsWebhookChannel, TeamsMessage, build_teams_actions


class TeamsAlerter(BaseAlerter):
    """Send bacteremia alerts to Microsoft Teams via Workflows webhook."""

    def __init__(
        self,
        webhook_url: str | None = None,
        include_phi: bool = True,
        include_actions: bool = True,
    ):
        """
        Initialize Teams alerter.

        Args:
            webhook_url: Teams Workflow webhook URL (or from env TEAMS_WEBHOOK_URL)
            include_phi: Whether to include patient details in message
            include_actions: Whether to include action buttons (default True)
        """
        url = webhook_url or config.TEAMS_WEBHOOK_URL

        self.channel = TeamsWebhookChannel(webhook_url=url) if url else None
        self.include_phi = include_phi
        self.include_actions = include_actions
        self.dashboard_base_url = config.DASHBOARD_BASE_URL
        self.dashboard_api_key = config.DASHBOARD_API_KEY
        self.alert_count = 0
        self.alerts: list[dict] = []

    def _build_facts(self, assessment: CoverageAssessment) -> list[tuple[str, str]]:
        """Build facts list for the Teams card."""
        current_abx = [a.medication_name for a in assessment.current_antibiotics]
        abx_text = ", ".join(current_abx) if current_abx else "None"

        if self.include_phi:
            facts = [
                ("Patient", f"{assessment.patient.name} ({assessment.patient.mrn})"),
                ("Location", assessment.patient.location or "Unknown"),
                ("Organism", assessment.culture.organism or "Pending identification"),
            ]

            if assessment.culture.gram_stain:
                facts.append(("Gram Stain", assessment.culture.gram_stain))

            facts.extend([
                ("Current Abx", abx_text),
                ("Status", f"⚠️ {assessment.coverage_status.value.upper()}"),
            ])
        else:
            facts = [
                ("Alert Type", "Bacteremia Coverage Concern"),
                ("Status", "⚠️ Action Required"),
            ]

        return facts

    def send_alert(
        self,
        assessment: CoverageAssessment,
        alert_id: str | None = None,
    ) -> bool:
        """Send alert to Teams channel via Workflows webhook.

        Args:
            assessment: The coverage assessment to alert on
            alert_id: Optional alert ID for action buttons

        Returns:
            True if sent successfully
        """
        if not self.channel:
            print("  Teams: Webhook URL not configured")
            return False

        facts = self._build_facts(assessment)
        recommendation_text = f"**Recommendation:** {assessment.recommendation}"

        # Build action buttons if alert_id is provided
        actions = []
        if self.include_actions and alert_id and self.dashboard_base_url:
            actions = build_teams_actions(
                alert_id=alert_id,
                base_url=self.dashboard_base_url,
                api_key=self.dashboard_api_key,
            )

        message = TeamsMessage(
            title="🔴 BACTEREMIA COVERAGE ALERT",
            facts=facts,
            text=recommendation_text,
            color="Attention",
            alert_id=alert_id,
            actions=actions,
        )

        if self.channel.send(message):
            self.alert_count += 1
            self.alerts.append({
                "timestamp": datetime.now().isoformat(),
                "alert_id": alert_id,
                "mrn": assessment.patient.mrn if self.include_phi else "redacted",
                "organism": assessment.culture.organism if self.include_phi else "redacted",
            })
            return True
        return False

    def get_alert_count(self) -> int:
        """Return number of alerts sent."""
        return self.alert_count

    def is_configured(self) -> bool:
        """Check if Teams alerting is properly configured."""
        return self.channel is not None and self.channel.is_configured()


def test_webhook(webhook_url: str | None = None) -> bool:
    """
    Send a test message to verify webhook configuration.

    Usage:
        python -c "from src.alerters.teams import test_webhook; test_webhook('YOUR_URL')"

    Or without URL to use configured TEAMS_WEBHOOK_URL:
        python -c "from src.alerters.teams import test_webhook; test_webhook()"
    """
    url = webhook_url or config.TEAMS_WEBHOOK_URL
    if not url:
        print("❌ No webhook URL provided and TEAMS_WEBHOOK_URL not set")
        return False

    channel = TeamsWebhookChannel(url)

    print("Sending test to Workflows webhook...")

    message = TeamsMessage(
        title="✅ ASP Bacteremia Alerts - Test Message",
        facts=[
            ("Patient", "Test Patient (TEST000)"),
            ("Location", "Test Unit"),
            ("Organism", "Test Organism"),
            ("Status", "✅ TEST"),
        ],
        text="If you see this, your webhook is configured correctly!",
        color="Good",
    )

    success = channel.send(message)

    if success:
        print("✅ SUCCESS! Check your Teams channel for the test message.")
    else:
        print("❌ FAILED - see error above")

    return success
