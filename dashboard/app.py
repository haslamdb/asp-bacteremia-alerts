"""Flask application factory for AEGIS Dashboard."""

import os
import sys
from flask import Flask

# Add parent directory to path for common module access
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from .config import get_config


def create_app(config=None):
    """Create and configure the Flask application.

    Args:
        config: Optional configuration object or dict

    Returns:
        Configured Flask application
    """
    app = Flask(__name__)

    # Load configuration
    if config is None:
        config = get_config()

    if isinstance(config, dict):
        app.config.update(config)
    else:
        app.config.from_object(config)

    # Initialize alert store
    from common.alert_store import AlertStore
    app.alert_store = AlertStore(db_path=app.config.get("ALERT_DB_PATH"))

    # Register blueprints
    from .routes.main import main_bp
    from .routes.views import asp_alerts_bp
    from .routes.api import api_bp
    from .routes.hai import hai_detection_bp
    from .routes.au_ar import nhsn_reporting_bp
    from .routes.dashboards import dashboards_bp

    app.register_blueprint(main_bp)  # Landing page at /
    app.register_blueprint(asp_alerts_bp)  # ASP Alerts at /asp-alerts
    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(hai_detection_bp)  # HAI Detection at /hai-detection
    app.register_blueprint(nhsn_reporting_bp)  # NHSN Reporting at /nhsn-reporting
    app.register_blueprint(dashboards_bp)  # Dashboards at /dashboards

    # Context processor for templates
    @app.context_processor
    def inject_globals():
        return {
            "app_name": "AEGIS",
            "base_url": app.config.get("DASHBOARD_BASE_URL", ""),
        }

    return app


def run_dev_server():
    """Run development server."""
    app = create_app()
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", 5000)),
        debug=True,
    )


if __name__ == "__main__":
    run_dev_server()
