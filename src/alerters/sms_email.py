"""SMS alerter using carrier email-to-SMS gateways.

No Twilio registration needed! Just send email to carrier gateway.

Carrier gateways:
- AT&T: number@txt.att.net
- Verizon: number@vtext.com
- T-Mobile: number@tmomail.net
- Sprint: number@messaging.sprintpcs.com
- US Cellular: number@email.uscc.net
"""

import smtplib
from datetime import datetime
from email.mime.text import MIMEText

from .base import BaseAlerter
from ..models import CoverageAssessment
from ..config import config


# Carrier gateway domains
CARRIER_GATEWAYS = {
    "att": "txt.att.net",
    "verizon": "vtext.com",
    "tmobile": "tmomail.net",
    "sprint": "messaging.sprintpcs.com",
    "uscellular": "email.uscc.net",
}


def phone_to_gateway(phone: str, carrier: str) -> str:
    """
    Convert phone number and carrier to gateway email.

    Args:
        phone: Phone number (any format, digits extracted)
        carrier: Carrier name (att, verizon, tmobile, sprint, uscellular)

    Returns:
        Gateway email address
    """
    # Extract digits only
    digits = "".join(c for c in phone if c.isdigit())

    # Remove leading 1 if present (US country code)
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]

    gateway = CARRIER_GATEWAYS.get(carrier.lower())
    if not gateway:
        raise ValueError(f"Unknown carrier: {carrier}. Use: {list(CARRIER_GATEWAYS.keys())}")

    return f"{digits}@{gateway}"


class SMSEmailAlerter(BaseAlerter):
    """Send SMS via carrier email gateways."""

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
        self.smtp_server = smtp_server or config.SMTP_SERVER
        self.smtp_port = smtp_port or config.SMTP_PORT
        self.smtp_username = smtp_username or config.SMTP_USERNAME
        self.smtp_password = smtp_password or config.SMTP_PASSWORD
        self.from_address = from_address or config.ALERT_EMAIL_FROM or "alerts@localhost"
        self.recipients = recipients or []
        self.include_phi = include_phi

        self.alert_count = 0
        self.alerts: list[dict] = []

    def add_recipient(self, phone: str, carrier: str):
        """Add a recipient by phone and carrier."""
        self.recipients.append({"phone": phone, "carrier": carrier})

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
        if not self.recipients:
            print("  SMS-Email: No recipients configured")
            return False

        if not self.smtp_server:
            print("  SMS-Email: SMTP server not configured")
            return False

        message_body = self._format_message(assessment)

        # Build gateway email addresses
        gateway_addresses = []
        for r in self.recipients:
            try:
                addr = phone_to_gateway(r["phone"], r["carrier"])
                gateway_addresses.append(addr)
            except ValueError as e:
                print(f"  SMS-Email: {e}")

        if not gateway_addresses:
            return False

        # Create simple plain text email (SMS gateways don't need HTML)
        msg = MIMEText(message_body)
        msg["Subject"] = "ASP Alert"
        msg["From"] = self.from_address
        msg["To"] = ", ".join(gateway_addresses)

        alert_record = {
            "timestamp": datetime.now().isoformat(),
            "mrn": assessment.patient.mrn,
            "recipients": gateway_addresses,
        }

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.smtp_port == 587:
                    server.starttls()
                if self.smtp_username and self.smtp_password:
                    server.login(self.smtp_username, self.smtp_password)
                server.sendmail(self.from_address, gateway_addresses, msg.as_string())

            self.alert_count += 1
            self.alerts.append(alert_record)
            print(f"  SMS sent via email to {len(gateway_addresses)} recipient(s)")
            return True

        except Exception as e:
            print(f"  SMS-Email failed: {e}")
            return False

    def get_alert_count(self) -> int:
        """Return number of alerts sent."""
        return self.alert_count

    def is_configured(self) -> bool:
        """Check if alerter is configured."""
        return bool(self.smtp_server and self.recipients)
