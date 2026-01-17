"""Generic SMS channel using Twilio.

HIPAA Considerations:
- Standard SMS is not encrypted
- Consider limiting PHI in messages
- For full HIPAA compliance, use TigerConnect, Imprivata Cortext, etc.
"""


class SMSChannel:
    """Send SMS via Twilio."""

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        from_number: str,
        to_numbers: list[str] | None = None,
    ):
        """
        Initialize Twilio SMS channel.

        Args:
            account_sid: Twilio account SID
            auth_token: Twilio auth token
            from_number: Twilio phone number to send from
            to_numbers: Default recipient phone numbers
        """
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.to_numbers = to_numbers or []
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

    def send(
        self,
        message: str,
        to_numbers: list[str] | None = None,
    ) -> bool:
        """
        Send an SMS message.

        Args:
            message: The message text
            to_numbers: Override default recipients

        Returns:
            True if all messages sent successfully, False otherwise
        """
        recipients = to_numbers or self.to_numbers
        if not recipients:
            print("  SMS: No recipient numbers configured")
            return False

        success = True
        for phone in recipients:
            try:
                self.client.messages.create(
                    body=message,
                    from_=self.from_number,
                    to=phone,
                )
                # Mask phone number in output
                masked = phone[-4:].rjust(len(phone), '*')
                print(f"  SMS sent to {masked}")
            except Exception as e:
                masked = phone[-4:].rjust(len(phone), '*')
                print(f"  SMS failed to {masked}: {e}")
                success = False

        return success

    def is_configured(self) -> bool:
        """Check if SMS channel is properly configured."""
        return all([
            self.account_sid,
            self.auth_token,
            self.from_number,
            self.to_numbers,
        ])
