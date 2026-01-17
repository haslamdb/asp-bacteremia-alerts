"""SMS alerter using carrier email-to-SMS gateways via shared channel.

No Twilio registration needed! Just send email to carrier gateway.

Carrier gateways:
- AT&T: number@txt.att.net
- Verizon: number@vtext.com
- T-Mobile: number@tmomail.net
- Sprint: number@messaging.sprintpcs.com
- US Cellular: number@email.uscc.net
"""

from datetime import datetime

from .base import BaseAlerter
from ..models import CoverageAssessment
from ..config import config  # This adds common to sys.path
from common.channels import SMSEmailChannel


class SMSEmailAlerter(BaseAlerter):
    """Send SMS via carrier email gateways using shared channel."""

    def __init__(
        self,
        smtp_server: str | None = None,
        smtp_port: int | None = None,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
        recipients: list[dict] | None = None,
        include_phi: bool = True,
    ):
        """
        Initialize SMS-via-email alerter.

        Args:
            smtp_server: SMTP server hostname
            smtp_port: SMTP server port
            smtp_username: SMTP auth username
            smtp_password: SMTP auth password
            from_address: Sender email
            recipients: List of {"phone": "xxx", "carrier": "att"} dicts
            include_phi: Include MRN/organism in message
        """
        server = smtp_server or config.SMTP_SERVER

        self.channel = SMSEmailChannel(
            smtp_server=server,
            smtp_port=smtp_port or config.SMTP_PORT,
            smtp_username=smtp_username or config.SMTP_USERNAME,
            smtp_password=smtp_password or config.SMTP_PASSWORD,
            from_address=from_address or config.ALERT_EMAIL_FROM or "alerts@localhost",
            recipients=recipients or [],
        ) if server else None

        self.include_phi = include_phi
        self.alert_count = 0
        self.alerts: list[dict] = []

    def add_recipient(self, phone: str, carrier: str):
        """Add a recipient by phone and carrier."""
        if self.channel:
            self.channel.add_recipient(phone, carrier)

    def _format_message(self, assessment: CoverageAssessment) -> str:
        """Format short SMS message."""
        if self.include_phi:
            current_abx = [a.medication_name.split()[0] for a in assessment.current_antibiotics]
            abx_short = ", ".join(current_abx[:2]) if current_abx else "None"

            # Keep it short for SMS
            return (
                f"ASP Alert: {assessment.patient.mrn}\n"
                f"{assessment.culture.organism or 'Pending'}\n"
                f"Abx: {abx_short}\n"
                f"Action needed"
            )
        else:
            return "ASP Alert: Bacteremia coverage concern. Check Epic."

    def send_alert(self, assessment: CoverageAssessment) -> bool:
        """Send SMS via email gateway."""
        if not self.channel:
            print("  SMS-Email: SMTP server not configured")
            return False

        message = self._format_message(assessment)

        if self.channel.send(message, subject="ASP Alert"):
            self.alert_count += 1
            self.alerts.append({
                "timestamp": datetime.now().isoformat(),
                "mrn": assessment.patient.mrn,
            })
            return True
        return False

    def get_alert_count(self) -> int:
        """Return number of alerts sent."""
        return self.alert_count

    def is_configured(self) -> bool:
        """Check if alerter is configured."""
        return self.channel is not None and self.channel.is_configured()
