"""Dashboard configuration."""

import os


class Config:
    """Base configuration."""

    # Flask
    SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-in-production")
    DEBUG = os.environ.get("FLASK_DEBUG", "false").lower() == "true"

    # Dashboard
    DASHBOARD_BASE_URL = os.environ.get("DASHBOARD_BASE_URL", "http://localhost:5000")
    DASHBOARD_API_KEY = os.environ.get("DASHBOARD_API_KEY", "")

    # FHIR Server
    FHIR_BASE_URL = os.environ.get("FHIR_BASE_URL", "http://localhost:8081/fhir")

    # Alert Store
    ALERT_DB_PATH = os.environ.get(
        "ALERT_DB_PATH",
        os.path.expanduser("~/.aegis/alerts.db")
    )

    # Pagination
    ALERTS_PER_PAGE = int(os.environ.get("ALERTS_PER_PAGE", "50"))

    # Email Notifications
    SMTP_SERVER = os.environ.get("SMTP_SERVER", "")
    SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
    SMTP_USERNAME = os.environ.get("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD", "")
    SENDER_EMAIL = os.environ.get("SENDER_EMAIL", "aegis@example.com")
    SENDER_NAME = os.environ.get("SENDER_NAME", "AEGIS")

    # HAI Detection Module
    HAI_NOTIFICATION_EMAIL = os.environ.get("HAI_NOTIFICATION_EMAIL", "")

    # NHSN Reporting Module
    NHSN_NOTIFICATION_EMAIL = os.environ.get("NHSN_NOTIFICATION_EMAIL", "")

    # Teams Notifications (for status updates when alerts are acknowledged/resolved)
    TEAMS_WEBHOOK_URL = os.environ.get("TEAMS_WEBHOOK_URL", "")


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False


def get_config():
    """Get configuration based on environment."""
    env = os.environ.get("FLASK_ENV", "development")
    if env == "production":
        return ProductionConfig()
    return DevelopmentConfig()
