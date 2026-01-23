"""Dashboard routes."""

from .main import main_bp
from .views import asp_alerts_bp
from .api import api_bp
from .hai import hai_detection_bp
from .au_ar import nhsn_reporting_bp
from .dashboards import dashboards_bp

__all__ = [
    "main_bp",
    "asp_alerts_bp",
    "api_bp",
    "hai_detection_bp",
    "nhsn_reporting_bp",
    "dashboards_bp",
]
