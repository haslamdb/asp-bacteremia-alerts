"""Configuration management for ASP Bacteremia Alerts."""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from .env file
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Fall back to template for defaults
    template_path = Path(__file__).parent.parent / ".env.template"
    if template_path.exists():
        load_dotenv(template_path)


class Config:
    """Application configuration."""

    # FHIR Server settings
    FHIR_BASE_URL: str = os.getenv("FHIR_BASE_URL", "http://localhost:8080/fhir")

    # Epic FHIR settings (for production)
    EPIC_FHIR_BASE_URL: str | None = os.getenv("EPIC_FHIR_BASE_URL")
    EPIC_CLIENT_ID: str | None = os.getenv("EPIC_CLIENT_ID")
    EPIC_PRIVATE_KEY_PATH: str | None = os.getenv("EPIC_PRIVATE_KEY_PATH")

    # Email settings
    SMTP_SERVER: str | None = os.getenv("SMTP_SERVER")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str | None = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD: str | None = os.getenv("SMTP_PASSWORD")
    ALERT_EMAIL_FROM: str | None = os.getenv("ALERT_EMAIL_FROM")
    ALERT_EMAIL_TO: list[str] = [
        e.strip() for e in os.getenv("ALERT_EMAIL_TO", "").split(",") if e.strip()
    ]

    # Twilio SMS settings
    TWILIO_ACCOUNT_SID: str | None = os.getenv("TWILIO_ACCOUNT_SID")
    TWILIO_AUTH_TOKEN: str | None = os.getenv("TWILIO_AUTH_TOKEN")
    TWILIO_FROM_NUMBER: str | None = os.getenv("TWILIO_FROM_NUMBER")
    ALERT_SMS_TO_NUMBERS: list[str] = [
        n.strip() for n in os.getenv("ALERT_SMS_TO_NUMBERS", "").split(",") if n.strip()
    ]
    ALERT_SMS_INCLUDE_PHI: bool = os.getenv("ALERT_SMS_INCLUDE_PHI", "true").lower() == "true"

    # SMS via Email gateway settings (alternative to Twilio)
    # Format: "phone:carrier,phone:carrier" e.g. "3145551234:att,5135559876:verizon"
    SMS_EMAIL_RECIPIENTS: list[dict] = []
    _sms_email_raw = os.getenv("SMS_EMAIL_RECIPIENTS", "")
    if _sms_email_raw:
        for entry in _sms_email_raw.split(","):
            if ":" in entry:
                phone, carrier = entry.strip().split(":", 1)
                SMS_EMAIL_RECIPIENTS.append({"phone": phone.strip(), "carrier": carrier.strip()})

    # Polling settings
    POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "300"))

    @classmethod
    def is_epic_configured(cls) -> bool:
        """Check if Epic FHIR credentials are configured."""
        return bool(cls.EPIC_FHIR_BASE_URL and cls.EPIC_CLIENT_ID)

    @classmethod
    def get_fhir_base_url(cls) -> str:
        """Get the appropriate FHIR base URL."""
        if cls.is_epic_configured():
            return cls.EPIC_FHIR_BASE_URL
        return cls.FHIR_BASE_URL


config = Config()
