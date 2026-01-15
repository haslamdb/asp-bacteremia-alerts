"""SMS alerter using Twilio.

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
from ..config import config


class SMSAlerter(BaseAlerter):
    """Send SMS alerts via Twilio."""

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
        self.account_sid = account_sid or config.TWILIO_ACCOUNT_SID
        self.auth_token = auth_token or config.TWILIO_AUTH_TOKEN
        self.from_number = from_number or config.TWILIO_FROM_NUMBER
        self.to_numbers = to_numbers or config.ALERT_SMS_TO_NUMBERS
        self.include_phi = include_phi

        self.alert_count = 0
        self.alerts: list[dict] = []
        self._client = None

    @property
    def client(self):
        """Lazy-load Twilio client."""
        if self._client is None:
            try:
                from twilio.rest import Client
                self._client = Client(self.account_sid, self.auth_token)
            except ImportError:
                raise ImportError(
                    "Twilio package not installed. Run: pip install twilio"
                )
        return self._client

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
        if not self.to_numbers:
            print("  SMS: No recipient numbers configured")
            return False

        if not all([self.account_sid, self.auth_token, self.from_number]):
            print("  SMS: Twilio credentials not configured")
            return False

        message_body = self._format_message(assessment)

        alert_record = {
            "timestamp": datetime.now().isoformat(),
            "mrn": assessment.patient.mrn,
            "recipients": self.to_numbers,
            "message_preview": message_body[:50] + "...",
        }

        success = True
        for phone in self.to_numbers:
            try:
                self.client.messages.create(
                    body=message_body,
                    from_=self.from_number,
                    to=phone,
                )
                print(f"  SMS sent to {phone[-4:].rjust(len(phone), '*')}")
            except Exception as e:
                print(f"  SMS failed to {phone[-4:].rjust(len(phone), '*')}: {e}")
                success = False

        if success:
            self.alert_count += 1
            self.alerts.append(alert_record)

        return success

    def get_alert_count(self) -> int:
        """Return number of alerts sent."""
        return self.alert_count

    def is_configured(self) -> bool:
        """Check if SMS alerting is properly configured."""
        return all([
            self.account_sid,
            self.auth_token,
            self.from_number,
            self.to_numbers,
        ])
