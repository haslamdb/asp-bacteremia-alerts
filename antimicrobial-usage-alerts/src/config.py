"""Configuration management for Antimicrobial Usage Alerts."""

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent  # antimicrobial-usage-alerts/
ASP_ALERTS_ROOT = PROJECT_ROOT.parent  # asp-alerts/

# Add common module to path
if str(ASP_ALERTS_ROOT) not in sys.path:
    sys.path.insert(0, str(ASP_ALERTS_ROOT))

# Load environment variables from .env file
env_path = PROJECT_ROOT / ".env"
if env_path.exists():
    load_dotenv(env_path)
else:
    # Fall back to template for defaults
    template_path = PROJECT_ROOT / ".env.template"
    if template_path.exists():
        load_dotenv(template_path)


class Config:
    """Application configuration."""

    # FHIR Server settings
    FHIR_BASE_URL: str = os.getenv("FHIR_BASE_URL", "http://localhost:8081/fhir")

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

    # Teams webhook settings
    TEAMS_WEBHOOK_URL: str | None = os.getenv("TEAMS_WEBHOOK_URL")

    # Dashboard/Alert Store settings
    DASHBOARD_BASE_URL: str = os.getenv("DASHBOARD_BASE_URL", "http://localhost:5000")
    DASHBOARD_API_KEY: str | None = os.getenv("DASHBOARD_API_KEY")
    ALERT_DB_PATH: str | None = os.getenv("ALERT_DB_PATH")

    # Broad-spectrum monitoring settings
    ALERT_THRESHOLD_HOURS: int = int(os.getenv("ALERT_THRESHOLD_HOURS", "72"))

    # Medications to monitor (RxNorm codes)
    # Default: Meropenem (29561) and Vancomycin (11124)
    MONITORED_MEDICATIONS: dict[str, str] = {
        "29561": "Meropenem",
        "11124": "Vancomycin",
    }

    # Optional: Add more medications via environment
    _extra_meds = os.getenv("EXTRA_MONITORED_MEDICATIONS", "")
    if _extra_meds:
        for entry in _extra_meds.split(","):
            if ":" in entry:
                code, name = entry.strip().split(":", 1)
                MONITORED_MEDICATIONS[code.strip()] = name.strip()

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
