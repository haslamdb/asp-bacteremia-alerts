"""Configuration for NHSN reporting module."""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

# Find and load .env file
_env_candidates = [
    Path(__file__).parent.parent / ".env",
    Path(__file__).parent.parent / ".env.template",
]

for env_path in _env_candidates:
    if env_path.exists():
        load_dotenv(env_path)
        break

# Add common module to path
_project_root = Path(__file__).parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))


class Config:
    """NHSN reporting configuration."""

    # --- Data Sources ---
    NOTE_SOURCE: str = os.getenv("NOTE_SOURCE", "fhir")  # fhir, clarity, or both
    FHIR_BASE_URL: str = os.getenv("FHIR_BASE_URL", "http://localhost:8081/fhir")
    CLARITY_CONNECTION_STRING: str | None = os.getenv("CLARITY_CONNECTION_STRING")

    # --- LLM Backend ---
    LLM_BACKEND: str = os.getenv("LLM_BACKEND", "ollama")  # ollama or claude
    OLLAMA_BASE_URL: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    OLLAMA_MODEL: str = os.getenv("OLLAMA_MODEL", "llama3.1:70b")
    CLAUDE_API_KEY: str | None = os.getenv("CLAUDE_API_KEY")
    CLAUDE_MODEL: str = os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    # --- Classification Thresholds ---
    # Above this confidence: auto-classify as HAI (no review needed)
    AUTO_CLASSIFY_THRESHOLD: float = float(
        os.getenv("AUTO_CLASSIFY_THRESHOLD", "0.85")
    )
    # Above this confidence: route to IP review
    # Below this: requires manual review
    IP_REVIEW_THRESHOLD: float = float(os.getenv("IP_REVIEW_THRESHOLD", "0.60"))

    # --- CLABSI Criteria ---
    # Minimum device days before culture for CLABSI eligibility
    MIN_DEVICE_DAYS: int = int(os.getenv("MIN_DEVICE_DAYS", "2"))
    # Days after line removal that BSI can still be attributed
    POST_REMOVAL_WINDOW_DAYS: int = int(os.getenv("POST_REMOVAL_WINDOW_DAYS", "1"))

    # --- Database ---
    NHSN_DB_PATH: str = os.getenv(
        "NHSN_DB_PATH",
        str(Path.home() / ".asp-alerts" / "nhsn.db"),
    )
    ALERT_DB_PATH: str = os.getenv(
        "ALERT_DB_PATH",
        str(Path.home() / ".asp-alerts" / "alerts.db"),
    )
    MOCK_CLARITY_DB_PATH: str = os.getenv(
        "MOCK_CLARITY_DB_PATH",
        str(Path.home() / ".asp-alerts" / "mock_clarity.db"),
    )

    # --- Monitoring ---
    POLL_INTERVAL: int = int(os.getenv("POLL_INTERVAL", "300"))  # seconds
    LOOKBACK_HOURS: int = int(os.getenv("LOOKBACK_HOURS", "24"))

    # --- Notifications ---
    TEAMS_WEBHOOK_URL: str | None = os.getenv("TEAMS_WEBHOOK_URL")
    DASHBOARD_BASE_URL: str = os.getenv("DASHBOARD_BASE_URL", "http://localhost:5000")

    # --- Email Notifications ---
    SMTP_SERVER: str | None = os.getenv("SMTP_SERVER")
    SMTP_PORT: int = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME: str | None = os.getenv("SMTP_USERNAME")
    SMTP_PASSWORD: str | None = os.getenv("SMTP_PASSWORD")
    SENDER_EMAIL: str = os.getenv("SENDER_EMAIL", "nhsn-alerts@example.com")
    SENDER_NAME: str = os.getenv("SENDER_NAME", "NHSN HAI Alerts")
    NHSN_NOTIFICATION_EMAIL: str | None = os.getenv("NHSN_NOTIFICATION_EMAIL")

    # --- Note Processing ---
    # Maximum note length to send to LLM (in characters)
    MAX_NOTE_LENGTH: int = int(os.getenv("MAX_NOTE_LENGTH", "50000"))
    # Maximum notes to retrieve per patient
    MAX_NOTES_PER_PATIENT: int = int(os.getenv("MAX_NOTES_PER_PATIENT", "20"))

    # --- Epic FHIR (if using Epic) ---
    EPIC_CLIENT_ID: str | None = os.getenv("EPIC_CLIENT_ID")
    EPIC_PRIVATE_KEY_PATH: str | None = os.getenv("EPIC_PRIVATE_KEY_PATH")
    EPIC_FHIR_BASE_URL: str | None = os.getenv("EPIC_FHIR_BASE_URL")

    # --- NHSN DIRECT Protocol Submission ---
    # HISP (Health Information Service Provider) settings
    NHSN_HISP_SMTP_SERVER: str | None = os.getenv("NHSN_HISP_SMTP_SERVER")
    NHSN_HISP_SMTP_PORT: int = int(os.getenv("NHSN_HISP_SMTP_PORT", "587"))
    NHSN_HISP_SMTP_USERNAME: str | None = os.getenv("NHSN_HISP_SMTP_USERNAME")
    NHSN_HISP_SMTP_PASSWORD: str | None = os.getenv("NHSN_HISP_SMTP_PASSWORD")
    NHSN_HISP_USE_TLS: bool = os.getenv("NHSN_HISP_USE_TLS", "true").lower() == "true"

    # DIRECT addresses
    NHSN_SENDER_DIRECT_ADDRESS: str | None = os.getenv("NHSN_SENDER_DIRECT_ADDRESS")
    NHSN_DIRECT_ADDRESS: str | None = os.getenv("NHSN_DIRECT_ADDRESS")

    # Facility info for NHSN reporting
    NHSN_FACILITY_ID: str | None = os.getenv("NHSN_FACILITY_ID")
    NHSN_FACILITY_NAME: str | None = os.getenv("NHSN_FACILITY_NAME")

    # Optional certificates for S/MIME (if required by HISP)
    NHSN_SENDER_CERT_PATH: str | None = os.getenv("NHSN_SENDER_CERT_PATH")
    NHSN_SENDER_KEY_PATH: str | None = os.getenv("NHSN_SENDER_KEY_PATH")
    NHSN_CERT_PATH: str | None = os.getenv("NHSN_CERT_PATH")

    @classmethod
    def get_fhir_base_url(cls) -> str:
        """Get the FHIR base URL (Epic if configured, otherwise default)."""
        if cls.EPIC_FHIR_BASE_URL and cls.EPIC_CLIENT_ID:
            return cls.EPIC_FHIR_BASE_URL
        return cls.FHIR_BASE_URL

    @classmethod
    def is_ollama_configured(cls) -> bool:
        """Check if Ollama is configured."""
        return cls.LLM_BACKEND == "ollama" and bool(cls.OLLAMA_BASE_URL)

    @classmethod
    def is_claude_configured(cls) -> bool:
        """Check if Claude API is configured."""
        return cls.LLM_BACKEND == "claude" and bool(cls.CLAUDE_API_KEY)

    @classmethod
    def is_clarity_configured(cls) -> bool:
        """Check if Clarity database is configured (real or mock)."""
        return bool(cls.CLARITY_CONNECTION_STRING) or Path(cls.MOCK_CLARITY_DB_PATH).exists()

    @classmethod
    def get_clarity_connection_string(cls) -> str | None:
        """Get Clarity connection - real DB for prod, mock SQLite for dev.

        Priority order:
        1. CLARITY_CONNECTION_STRING env var (production Clarity)
        2. MOCK_CLARITY_DB_PATH if file exists (development mock)
        3. None if neither configured

        Returns:
            SQLAlchemy connection string or None if not configured.
        """
        if cls.CLARITY_CONNECTION_STRING:
            return cls.CLARITY_CONNECTION_STRING
        if Path(cls.MOCK_CLARITY_DB_PATH).exists():
            return f"sqlite:///{cls.MOCK_CLARITY_DB_PATH}"
        return None

    @classmethod
    def is_teams_configured(cls) -> bool:
        """Check if Teams webhook is configured."""
        return bool(cls.TEAMS_WEBHOOK_URL)

    @classmethod
    def is_email_configured(cls) -> bool:
        """Check if email notifications are configured."""
        return bool(cls.SMTP_SERVER) and bool(cls.NHSN_NOTIFICATION_EMAIL)

    @classmethod
    def is_direct_configured(cls) -> bool:
        """Check if NHSN DIRECT protocol submission is configured."""
        return all([
            cls.NHSN_HISP_SMTP_SERVER,
            cls.NHSN_HISP_SMTP_USERNAME,
            cls.NHSN_HISP_SMTP_PASSWORD,
            cls.NHSN_SENDER_DIRECT_ADDRESS,
            cls.NHSN_DIRECT_ADDRESS,
        ])

    @classmethod
    def get_direct_config(cls):
        """Get DIRECT configuration for submission client.

        Returns:
            DirectConfig object or None if not configured
        """
        from .direct import DirectConfig
        return DirectConfig(
            hisp_smtp_server=cls.NHSN_HISP_SMTP_SERVER or "",
            hisp_smtp_port=cls.NHSN_HISP_SMTP_PORT,
            hisp_smtp_username=cls.NHSN_HISP_SMTP_USERNAME or "",
            hisp_smtp_password=cls.NHSN_HISP_SMTP_PASSWORD or "",
            hisp_use_tls=cls.NHSN_HISP_USE_TLS,
            sender_direct_address=cls.NHSN_SENDER_DIRECT_ADDRESS or "",
            nhsn_direct_address=cls.NHSN_DIRECT_ADDRESS or "",
            facility_id=cls.NHSN_FACILITY_ID or "",
            facility_name=cls.NHSN_FACILITY_NAME or "",
            sender_cert_path=cls.NHSN_SENDER_CERT_PATH or "",
            sender_key_path=cls.NHSN_SENDER_KEY_PATH or "",
            nhsn_cert_path=cls.NHSN_CERT_PATH or "",
        )


# Module-level convenience instance
config = Config()
