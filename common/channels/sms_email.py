"""SMS channel using carrier email-to-SMS gateways.

No Twilio registration needed - just send email to carrier gateway.

Carrier gateways:
- AT&T: number@txt.att.net
- Verizon: number@vtext.com
- T-Mobile: number@tmomail.net
- Sprint: number@messaging.sprintpcs.com
- US Cellular: number@email.uscc.net
"""

import smtplib
from email.mime.text import MIMEText


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


class SMSEmailChannel:
    """Send SMS via carrier email gateways."""

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int = 587,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
        recipients: list[dict] | None = None,
    ):
        """
        Initialize SMS-via-email channel.

        Args:
            smtp_server: SMTP server hostname
            smtp_port: SMTP server port
            smtp_username: SMTP auth username
            smtp_password: SMTP auth password
            from_address: Sender email
            recipients: List of {"phone": "xxx", "carrier": "att"} dicts
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.from_address = from_address or "alerts@localhost"
        self.recipients = recipients or []

    def add_recipient(self, phone: str, carrier: str):
        """Add a recipient by phone and carrier."""
        self.recipients.append({"phone": phone, "carrier": carrier})

    def send(
        self,
        message: str,
        subject: str = "Alert",
        recipients: list[dict] | None = None,
    ) -> bool:
        """
        Send SMS via email gateway.

        Args:
            message: The message text
            subject: Email subject (often shown in SMS)
            recipients: Override default recipients

        Returns:
            True if sent successfully, False otherwise
        """
        target_recipients = recipients or self.recipients
        if not target_recipients:
            print("  SMS-Email: No recipients configured")
            return False

        # Build gateway email addresses
        gateway_addresses = []
        for r in target_recipients:
            try:
                addr = phone_to_gateway(r["phone"], r["carrier"])
                gateway_addresses.append(addr)
            except ValueError as e:
                print(f"  SMS-Email: {e}")

        if not gateway_addresses:
            return False

        # Create simple plain text email (SMS gateways don't need HTML)
        msg = MIMEText(message)
        msg["Subject"] = subject
        msg["From"] = self.from_address
        msg["To"] = ", ".join(gateway_addresses)

        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                if self.smtp_port == 587:
                    server.starttls()
                if self.smtp_username and self.smtp_password:
                    server.login(self.smtp_username, self.smtp_password)
                server.sendmail(self.from_address, gateway_addresses, msg.as_string())

            print(f"  SMS sent via email to {len(gateway_addresses)} recipient(s)")
            return True

        except Exception as e:
            print(f"  SMS-Email failed: {e}")
            return False

    def is_configured(self) -> bool:
        """Check if channel is configured."""
        return bool(self.smtp_server and self.recipients)
