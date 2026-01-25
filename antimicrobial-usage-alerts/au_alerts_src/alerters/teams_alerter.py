"""Teams alerter for broad-spectrum antibiotic usage alerts."""

from common.channels.teams import TeamsWebhookChannel, TeamsMessage, build_teams_actions

from ..config import config
from ..models import UsageAssessment, AlertSeverity


class TeamsAlerter:
    """Send usage alerts via Microsoft Teams."""

    def __init__(
        self,
        channel: TeamsWebhookChannel | None = None,
        include_actions: bool = True,
    ):
        """Initialize with Teams channel from config or provided channel.

        Args:
            channel: Optional pre-configured Teams channel
            include_actions: Whether to include action buttons (default True)
        """
        if channel:
            self.channel = channel
        else:
            self.channel = TeamsWebhookChannel(
                webhook_url=config.TEAMS_WEBHOOK_URL or "",
            )
        self.include_actions = include_actions
        self.dashboard_base_url = config.DASHBOARD_BASE_URL
        self.dashboard_api_key = config.DASHBOARD_API_KEY

    def is_configured(self) -> bool:
        """Check if Teams alerting is configured."""
        return self.channel.is_configured()

    def send_alert(
        self,
        assessment: UsageAssessment,
        alert_id: str | None = None,
    ) -> bool:
        """Send a Teams alert for a usage assessment.

        Args:
            assessment: The usage assessment to alert on
            alert_id: Optional alert ID for action buttons

        Returns:
            True if sent successfully
        """
        message = self._build_message(assessment, alert_id=alert_id)
        return self.channel.send(message)

    def send_alerts(
        self,
        assessments: list[tuple[UsageAssessment, str | None]],
    ) -> int:
        """Send alerts for multiple assessments.

        Args:
            assessments: List of (UsageAssessment, alert_id) tuples

        Returns:
            Number of alerts successfully sent.
        """
        sent = 0
        for assessment, alert_id in assessments:
            if self.send_alert(assessment, alert_id=alert_id):
                sent += 1
        return sent

    def _build_message(
        self,
        assessment: UsageAssessment,
        alert_id: str | None = None,
    ) -> TeamsMessage:
        """Build Teams message from assessment."""
        p = assessment.patient
        m = assessment.medication

        # Map severity to Teams color
        color_map = {
            AlertSeverity.CRITICAL: "Attention",
            AlertSeverity.WARNING: "Warning",
            AlertSeverity.INFO: "Default",
        }
        color = color_map.get(assessment.severity, "Warning")

        # Build title
        severity_emoji = {
            AlertSeverity.CRITICAL: "🔴",
            AlertSeverity.WARNING: "🟡",
            AlertSeverity.INFO: "🔵",
        }
        emoji = severity_emoji.get(assessment.severity, "🟡")

        title = f"{emoji} Broad-Spectrum Alert: {m.medication_name} > {assessment.threshold_hours}h"

        # Build facts
        facts = [
            ("Patient", p.name),
            ("MRN", p.mrn),
        ]

        if p.location:
            facts.append(("Location", p.location))
        if p.department:
            facts.append(("Department", p.department))

        facts.extend([
            ("Medication", m.medication_name),
            ("Duration", f"{assessment.duration_hours:.1f} hours ({assessment.duration_hours/24:.1f} days)"),
            ("Threshold", f"{assessment.threshold_hours} hours"),
            ("Severity", assessment.severity.value.upper()),
        ])

        if m.dose:
            facts.append(("Dose", m.dose))
        if m.start_date:
            facts.append(("Started", m.start_date.strftime('%Y-%m-%d %H:%M')))

        # Build action buttons if alert_id is provided
        actions = []
        if self.include_actions and alert_id and self.dashboard_base_url:
            actions = build_teams_actions(
                alert_id=alert_id,
                base_url=self.dashboard_base_url,
                api_key=self.dashboard_api_key,
            )

        return TeamsMessage(
            title=title,
            facts=facts,
            text=f"**Recommendation:** {assessment.recommendation}",
            color=color,
            alert_id=alert_id,
            actions=actions,
        )
