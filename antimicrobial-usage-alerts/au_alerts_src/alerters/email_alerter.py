"""Email alerter for broad-spectrum antibiotic usage alerts."""

from common.channels.email import EmailChannel, EmailMessage

from ..config import config
from ..models import UsageAssessment, AlertSeverity


class EmailAlerter:
    """Send usage alerts via email."""

    def __init__(self, channel: EmailChannel | None = None):
        """Initialize with email channel from config or provided channel."""
        if channel:
            self.channel = channel
        else:
            self.channel = EmailChannel(
                smtp_server=config.SMTP_SERVER or "",
                smtp_port=config.SMTP_PORT,
                smtp_username=config.SMTP_USERNAME,
                smtp_password=config.SMTP_PASSWORD,
                from_address=config.ALERT_EMAIL_FROM,
                to_addresses=config.ALERT_EMAIL_TO,
            )
        self.dashboard_base_url = config.DASHBOARD_BASE_URL

    def is_configured(self) -> bool:
        """Check if email alerting is configured."""
        return self.channel.is_configured()

    def send_alert(self, assessment: UsageAssessment, alert_id: str | None = None) -> bool:
        """Send an email alert for a usage assessment."""
        subject = self._build_subject(assessment)
        text_body = self._build_text_body(assessment, alert_id)
        html_body = self._build_html_body(assessment, alert_id)

        message = EmailMessage(
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )

        return self.channel.send(message)

    def send_alerts(self, assessments: list[UsageAssessment]) -> int:
        """Send alerts for multiple assessments.

        Returns:
            Number of alerts successfully sent.
        """
        sent = 0
        for assessment in assessments:
            if self.send_alert(assessment):
                sent += 1
        return sent

    def _build_subject(self, assessment: UsageAssessment) -> str:
        """Build email subject line."""
        severity = assessment.severity
        if severity == AlertSeverity.CRITICAL:
            prefix = "[CRITICAL]"
        elif severity == AlertSeverity.WARNING:
            prefix = "[Warning]"
        else:
            prefix = "[Info]"

        return (
            f"{prefix} Broad-Spectrum Alert: {assessment.medication.medication_name} "
            f"> {assessment.threshold_hours}h - {assessment.patient.name}"
        )

    def _build_text_body(self, assessment: UsageAssessment, alert_id: str | None = None) -> str:
        """Build plain text email body."""
        p = assessment.patient
        m = assessment.medication

        lines = [
            f"ANTIMICROBIAL USAGE ALERT",
            f"Severity: {assessment.severity.value.upper()}",
            "",
            f"Patient: {p.name}",
            f"MRN: {p.mrn}",
        ]

        if p.location:
            lines.append(f"Location: {p.location}")
        if p.department:
            lines.append(f"Department: {p.department}")

        lines.extend([
            "",
            f"Medication: {m.medication_name}",
            f"Duration: {assessment.duration_hours:.1f} hours ({assessment.duration_hours/24:.1f} days)",
            f"Threshold: {assessment.threshold_hours} hours",
        ])

        if m.dose:
            lines.append(f"Dose: {m.dose}")
        if m.route:
            lines.append(f"Route: {m.route}")
        if m.start_date:
            lines.append(f"Started: {m.start_date.strftime('%Y-%m-%d %H:%M')}")

        lines.extend([
            "",
            "RECOMMENDATION:",
            assessment.recommendation,
        ])

        # Add dashboard link if available
        if alert_id and self.dashboard_base_url:
            alert_url = f"{self.dashboard_base_url}/asp-alerts/alerts/{alert_id}"
            lines.extend([
                "",
                f"View in Dashboard: {alert_url}",
            ])

        lines.extend([
            "",
            "---",
            "ASP Antimicrobial Usage Alerts",
            f"Generated: {assessment.assessed_at.strftime('%Y-%m-%d %H:%M:%S')}",
        ])

        return "\n".join(lines)

    def _build_html_body(self, assessment: UsageAssessment, alert_id: str | None = None) -> str:
        """Build HTML email body."""
        p = assessment.patient
        m = assessment.medication

        severity_colors = {
            AlertSeverity.CRITICAL: "#dc3545",
            AlertSeverity.WARNING: "#ffc107",
            AlertSeverity.INFO: "#17a2b8",
        }
        color = severity_colors.get(assessment.severity, "#ffc107")

        location_html = ""
        if p.location:
            location_html += f"<tr><td><strong>Location:</strong></td><td>{p.location}</td></tr>"
        if p.department:
            location_html += f"<tr><td><strong>Department:</strong></td><td>{p.department}</td></tr>"

        dose_html = ""
        if m.dose:
            dose_html += f"<tr><td><strong>Dose:</strong></td><td>{m.dose}</td></tr>"
        if m.route:
            dose_html += f"<tr><td><strong>Route:</strong></td><td>{m.route}</td></tr>"

        # Build dashboard link button if available
        dashboard_button = ""
        if alert_id and self.dashboard_base_url:
            alert_url = f"{self.dashboard_base_url}/asp-alerts/alerts/{alert_id}"
            dashboard_button = f'<a href="{alert_url}" style="display: inline-block; background-color: #1976d2; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; margin: 15px 0;">View Alert in Dashboard</a>'

        return f"""
        <html>
        <body style="font-family: Arial, sans-serif; margin: 0; padding: 20px;">
            <div style="max-width: 600px; margin: 0 auto;">
                <div style="background-color: {color}; color: white; padding: 15px; border-radius: 5px 5px 0 0;">
                    <h2 style="margin: 0;">Antimicrobial Usage Alert</h2>
                    <p style="margin: 5px 0 0 0;">Severity: {assessment.severity.value.upper()}</p>
                </div>

                <div style="border: 1px solid #ddd; border-top: none; padding: 20px; border-radius: 0 0 5px 5px;">
                    <h3 style="color: #333; margin-top: 0;">Patient Information</h3>
                    <table style="border-collapse: collapse; width: 100%;">
                        <tr><td style="padding: 5px 10px 5px 0;"><strong>Name:</strong></td><td>{p.name}</td></tr>
                        <tr><td style="padding: 5px 10px 5px 0;"><strong>MRN:</strong></td><td>{p.mrn}</td></tr>
                        {location_html}
                    </table>

                    <h3 style="color: #333;">Medication Details</h3>
                    <table style="border-collapse: collapse; width: 100%;">
                        <tr><td style="padding: 5px 10px 5px 0;"><strong>Medication:</strong></td><td>{m.medication_name}</td></tr>
                        <tr><td style="padding: 5px 10px 5px 0;"><strong>Duration:</strong></td><td><strong style="color: {color};">{assessment.duration_hours:.1f} hours ({assessment.duration_hours/24:.1f} days)</strong></td></tr>
                        <tr><td style="padding: 5px 10px 5px 0;"><strong>Threshold:</strong></td><td>{assessment.threshold_hours} hours</td></tr>
                        {dose_html}
                    </table>

                    <h3 style="color: #333;">Recommendation</h3>
                    <p style="background-color: #f8f9fa; padding: 15px; border-radius: 5px; border-left: 4px solid {color};">
                        {assessment.recommendation}
                    </p>

                    {dashboard_button}

                    <hr style="border: none; border-top: 1px solid #ddd; margin: 20px 0;">
                    <p style="color: #888; font-size: 12px; margin: 0;">
                        ASP Antimicrobial Usage Alerts<br>
                        Generated: {assessment.assessed_at.strftime('%Y-%m-%d %H:%M:%S')}
                    </p>
                </div>
            </div>
        </body>
        </html>
        """
