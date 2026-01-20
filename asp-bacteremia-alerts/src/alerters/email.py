"""Email alerter using shared email channel."""

from datetime import datetime

from .base import BaseAlerter
from ..models import CoverageAssessment
from ..config import config  # This adds common to sys.path
from common.channels import EmailChannel
from common.channels.email import EmailMessage


class EmailAlerter(BaseAlerter):
    """Send email alerts via SMTP using shared channel."""

    def __init__(
        self,
        smtp_server: str | None = None,
        smtp_port: int | None = None,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
        to_addresses: list[str] | None = None,
        use_tls: bool = True,
    ):
        """
        Initialize email alerter.

        Args:
            smtp_server: SMTP server hostname
            smtp_port: SMTP server port (587 for TLS, 465 for SSL, 25 for plain)
            smtp_username: SMTP authentication username
            smtp_password: SMTP authentication password
            from_address: Sender email address
            to_addresses: List of recipient email addresses
            use_tls: Whether to use STARTTLS
        """
        server = smtp_server or config.SMTP_SERVER
        self.channel = EmailChannel(
            smtp_server=server,
            smtp_port=smtp_port or config.SMTP_PORT,
            smtp_username=smtp_username or config.SMTP_USERNAME,
            smtp_password=smtp_password or config.SMTP_PASSWORD,
            from_address=from_address or config.ALERT_EMAIL_FROM,
            to_addresses=to_addresses or config.ALERT_EMAIL_TO,
            use_tls=use_tls,
        ) if server else None

        self.dashboard_base_url = config.DASHBOARD_BASE_URL
        self.alert_count = 0
        self.alerts: list[dict] = []

    def _format_subject(self, assessment: CoverageAssessment) -> str:
        """Format email subject line."""
        organism = assessment.culture.organism or "Unknown organism"
        if len(organism) > 40:
            organism = organism[:37] + "..."
        return f"[ASP Alert] Bacteremia Coverage - {assessment.patient.mrn} - {organism}"

    def _format_html_body(self, assessment: CoverageAssessment, alert_id: str | None = None) -> str:
        """Format email body as HTML."""
        current_abx = [a.medication_name for a in assessment.current_antibiotics]
        abx_list = ", ".join(current_abx) if current_abx else "<em>None</em>"

        # Build clinical data links
        clinical_links = ""
        if self.dashboard_base_url:
            culture_url = f"{self.dashboard_base_url}/asp-alerts/culture/{assessment.culture.fhir_id}"
            meds_url = f"{self.dashboard_base_url}/asp-alerts/patient/{assessment.patient.fhir_id}/medications"
            clinical_links = f'''
                <div style="margin-top: 15px;">
                    <a href="{culture_url}" style="display: inline-block; background-color: #0d9488; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px; margin-right: 10px;">View Culture Results</a>
                    <a href="{meds_url}" style="display: inline-block; background-color: #0d9488; color: white; padding: 8px 16px; text-decoration: none; border-radius: 4px;">View Medications</a>
                </div>
            '''

        # Build alert link if we have an alert_id and dashboard URL
        alert_link = ""
        if alert_id and self.dashboard_base_url:
            alert_url = f"{self.dashboard_base_url}/asp-alerts/alerts/{alert_id}"
            alert_link = f'<a href="{alert_url}" style="display: inline-block; background-color: #1976d2; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; margin-top: 15px;">View Alert in Dashboard</a>'

        html = f"""
        <html>
        <head>
            <style>
                body {{ font-family: Arial, sans-serif; }}
                .alert-box {{
                    border: 2px solid #d32f2f;
                    border-radius: 8px;
                    padding: 20px;
                    max-width: 600px;
                    background-color: #ffebee;
                }}
                .header {{
                    color: #d32f2f;
                    font-size: 20px;
                    font-weight: bold;
                    margin-bottom: 15px;
                }}
                .field {{ margin: 8px 0; }}
                .label {{ font-weight: bold; color: #333; }}
                .value {{ color: #555; }}
                .recommendation {{
                    background-color: #fff3e0;
                    border-left: 4px solid #ff9800;
                    padding: 10px;
                    margin-top: 15px;
                }}
                .footer {{
                    margin-top: 20px;
                    font-size: 12px;
                    color: #888;
                }}
            </style>
        </head>
        <body>
            <div class="alert-box">
                <div class="header">Bacteremia Coverage Alert</div>

                <div class="field">
                    <span class="label">Patient:</span>
                    <span class="value">{assessment.patient.name} ({assessment.patient.mrn})</span>
                </div>

                <div class="field">
                    <span class="label">Location:</span>
                    <span class="value">{assessment.patient.location or 'Unknown'}</span>
                </div>

                <div class="field">
                    <span class="label">Organism:</span>
                    <span class="value">{assessment.culture.organism or 'Pending identification'}</span>
                </div>

                {"<div class='field'><span class='label'>Gram Stain:</span> <span class='value'>" + assessment.culture.gram_stain + "</span></div>" if assessment.culture.gram_stain else ""}

                <div class="field">
                    <span class="label">Current Antibiotics:</span>
                    <span class="value">{abx_list}</span>
                </div>

                <div class="field">
                    <span class="label">Coverage Status:</span>
                    <span class="value" style="color: #d32f2f; font-weight: bold;">
                        {assessment.coverage_status.value.upper()}
                    </span>
                </div>

                <div class="recommendation">
                    <span class="label">Recommendation:</span><br>
                    {assessment.recommendation}
                </div>

                {clinical_links}

                {alert_link}

                <div class="footer">
                    Alert generated at {assessment.assessed_at.strftime('%Y-%m-%d %H:%M:%S')}<br>
                    Culture ID: {assessment.culture.fhir_id}<br>
                    <em>This is an automated alert from ASP Bacteremia Monitor</em>
                </div>
            </div>
        </body>
        </html>
        """
        return html

    def _format_text_body(self, assessment: CoverageAssessment, alert_id: str | None = None) -> str:
        """Format email body as plain text."""
        current_abx = [a.medication_name for a in assessment.current_antibiotics]
        abx_list = ", ".join(current_abx) if current_abx else "None"

        # Build clinical data links
        clinical_links = ""
        if self.dashboard_base_url:
            culture_url = f"{self.dashboard_base_url}/asp-alerts/culture/{assessment.culture.fhir_id}"
            meds_url = f"{self.dashboard_base_url}/asp-alerts/patient/{assessment.patient.fhir_id}/medications"
            clinical_links = f"\nView Culture Results: {culture_url}\nView Medications: {meds_url}\n"

        # Build alert link if we have an alert_id and dashboard URL
        alert_link = ""
        if alert_id and self.dashboard_base_url:
            alert_url = f"{self.dashboard_base_url}/asp-alerts/alerts/{alert_id}"
            alert_link = f"\nView in Dashboard: {alert_url}\n"

        text = f"""
BACTEREMIA COVERAGE ALERT
{'=' * 50}

Patient:     {assessment.patient.name} ({assessment.patient.mrn})
Location:    {assessment.patient.location or 'Unknown'}
Organism:    {assessment.culture.organism or 'Pending identification'}
{"Gram Stain:  " + assessment.culture.gram_stain if assessment.culture.gram_stain else ""}
Current Abx: {abx_list}
Status:      {assessment.coverage_status.value.upper()}

RECOMMENDATION:
{assessment.recommendation}
{clinical_links}{alert_link}
{'=' * 50}
Alert generated at {assessment.assessed_at.strftime('%Y-%m-%d %H:%M:%S')}
Culture ID: {assessment.culture.fhir_id}
This is an automated alert from ASP Bacteremia Monitor
        """.strip()
        return text

    def send_alert(
        self,
        assessment: CoverageAssessment,
        alert_id: str | None = None,
    ) -> bool:
        """Send email alert to configured addresses."""
        if not self.channel:
            print("  Email: SMTP server not configured")
            return False

        message = EmailMessage(
            subject=self._format_subject(assessment),
            text_body=self._format_text_body(assessment, alert_id),
            html_body=self._format_html_body(assessment, alert_id),
        )

        if self.channel.send(message):
            self.alert_count += 1
            self.alerts.append({
                "timestamp": datetime.now().isoformat(),
                "alert_id": alert_id,
                "mrn": assessment.patient.mrn,
                "subject": message.subject,
            })
            return True
        return False

    def get_alert_count(self) -> int:
        """Return number of alerts sent."""
        return self.alert_count

    def is_configured(self) -> bool:
        """Check if email alerting is properly configured."""
        return self.channel is not None and self.channel.is_configured()
