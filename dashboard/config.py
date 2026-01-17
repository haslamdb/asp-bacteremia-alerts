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

    # Alert Store
    ALERT_DB_PATH = os.environ.get(
        "ALERT_DB_PATH",
        os.path.expanduser("~/.asp-alerts/alerts.db")
    )

    # Pagination
    ALERTS_PER_PAGE = int(os.environ.get("ALERTS_PER_PAGE", "50"))


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
