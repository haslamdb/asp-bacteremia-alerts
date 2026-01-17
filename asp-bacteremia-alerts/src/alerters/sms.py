"""SMS alerter using Twilio via shared channel.

HIPAA Considerations:
- Standard SMS is not encrypted
- Option A (safest): Alert without PHI - just notify to check Epic
- Option B (common practice): Minimal PHI (MRN + location)
- Option C: Use HIPAA-compliant service (TigerConnect, Imprivata Cortext)

This implementation uses Option B (minimal PHI) by default.
Configure ALERT_SMS_INCLUDE_PHI=false for Option A.
"""

from datetime import datetime

from .base import BaseAlerter
from ..models import CoverageAssessment
from ..config import config  # This adds common to sys.path
from common.channels import SMSChannel


class SMSAlerter(BaseAlerter):
    """Send SMS alerts via Twilio using shared channel."""

    def __init__(
        self,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        to_numbers: list[str] | None = None,
        include_phi: bool = True,
    ):
        """
        Initialize Twilio SMS alerter.

        Args:
            account_sid: Twilio account SID (or from env TWILIO_ACCOUNT_SID)
            auth_token: Twilio auth token (or from env TWILIO_AUTH_TOKEN)
            from_number: Twilio phone number to send from (or from env TWILIO_FROM_NUMBER)
            to_numbers: List of phone numbers to alert (or from env ALERT_SMS_TO_NUMBERS)
            include_phi: Whether to include minimal PHI (MRN, location, organism)
        """
        sid = account_sid or config.TWILIO_ACCOUNT_SID
        token = auth_token or config.TWILIO_AUTH_TOKEN
        from_num = from_number or config.TWILIO_FROM_NUMBER

        self.channel = SMSChannel(
            account_sid=sid,
            auth_token=token,
            from_number=from_num,
            to_numbers=to_numbers or config.ALERT_SMS_TO_NUMBERS,
        ) if all([sid, token, from_num]) else None

        self.include_phi = include_phi
        self.alert_count = 0
        self.alerts: list[dict] = []

    def _format_message(self, assessment: CoverageAssessment) -> str:
        """Format alert message for SMS."""
        if self.include_phi:
            # Minimal PHI version - MRN, location, organism
            current_abx = [a.medication_name for a in assessment.current_antibiotics]
            return (
                f"ASP Bacteremia Alert\n"
                f"MRN: {assessment.patient.mrn}\n"
                f"Loc: {assessment.patient.location or 'Unknown'}\n"
                f"Organism: {assessment.culture.organism or 'Pending'}\n"
                f"Abx: {', '.join(current_abx) if current_abx else 'None'}\n"
                f"Action: {assessment.recommendation}"
            )
        else:
            # No PHI version - just notification
            return (
                "ASP Alert: New bacteremia coverage concern detected. "
                "Check Epic In Basket for details."
            )

    def send_alert(self, assessment: CoverageAssessment) -> bool:
        """Send SMS alert to configured numbers."""
        if not self.channel:
            print("  SMS: Twilio credentials not configured")
            return False

        message = self._format_message(assessment)

        if self.channel.send(message):
            self.alert_count += 1
            self.alerts.append({
                "timestamp": datetime.now().isoformat(),
                "mrn": assessment.patient.mrn,
                "message_preview": message[:50] + "...",
            })
            return True
        return False

    def get_alert_count(self) -> int:
        """Return number of alerts sent."""
        return self.alert_count

    def is_configured(self) -> bool:
        """Check if SMS alerting is properly configured."""
        return self.channel is not None and self.channel.is_configured()
