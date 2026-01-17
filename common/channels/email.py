"""Generic email channel using SMTP."""

import smtplib
import ssl
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText


@dataclass
class EmailMessage:
    """Email message content."""
    subject: str
    text_body: str
    html_body: str | None = None


class EmailChannel:
    """Send emails via SMTP."""

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int = 587,
        smtp_username: str | None = None,
        smtp_password: str | None = None,
        from_address: str | None = None,
        to_addresses: list[str] | None = None,
        use_tls: bool = True,
    ):
        """
        Initialize SMTP email channel.

        Args:
            smtp_server: SMTP server hostname
            smtp_port: SMTP server port (587 for TLS, 465 for SSL, 25 for plain)
            smtp_username: SMTP authentication username
            smtp_password: SMTP authentication password
            from_address: Sender email address
            to_addresses: Default recipient email addresses
            use_tls: Whether to use STARTTLS (for port 587)
        """
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.smtp_username = smtp_username
        self.smtp_password = smtp_password
        self.from_address = from_address or f"asp-alerts@{smtp_server}"
        self.to_addresses = to_addresses or []
        self.use_tls = use_tls

    def send(
        self,
        message: EmailMessage,
        to_addresses: list[str] | None = None,
    ) -> bool:
        """
        Send an email.

        Args:
            message: The email message content
            to_addresses: Override default recipients

        Returns:
            True if sent successfully, False otherwise
        """
        recipients = to_addresses or self.to_addresses
        if not recipients:
            print("  Email: No recipient addresses configured")
            return False

        # Create message
        msg = MIMEMultipart("alternative")
        msg["Subject"] = message.subject
        msg["From"] = self.from_address
        msg["To"] = ", ".join(recipients)

        # Attach text version (required)
        text_part = MIMEText(message.text_body, "plain")
        msg.attach(text_part)

        # Attach HTML version if provided
        if message.html_body:
            html_part = MIMEText(message.html_body, "html")
            msg.attach(html_part)

        try:
            if self.smtp_port == 465:
                # SSL connection
                context = ssl.create_default_context()
                with smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, context=context) as server:
                    if self.smtp_username and self.smtp_password:
                        server.login(self.smtp_username, self.smtp_password)
                    server.sendmail(self.from_address, recipients, msg.as_string())
            else:
                # Plain or STARTTLS connection
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    if self.use_tls:
                        server.starttls()
                    if self.smtp_username and self.smtp_password:
                        server.login(self.smtp_username, self.smtp_password)
                    server.sendmail(self.from_address, recipients, msg.as_string())

            print(f"  Email sent to {len(recipients)} recipient(s)")
            return True

        except Exception as e:
            print(f"  Email failed: {e}")
            return False

    def is_configured(self) -> bool:
        """Check if email channel is properly configured."""
        return bool(self.smtp_server and self.to_addresses)
