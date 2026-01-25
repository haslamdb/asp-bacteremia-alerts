"""Routes for Antibiotic Indications module.

This module provides ICD-10 based antibiotic appropriateness classification
following Chua et al. methodology with pediatric inpatient modifications.
"""

import logging
import sys
from pathlib import Path

from flask import Blueprint, render_template

logger = logging.getLogger(__name__)

# Add antimicrobial-usage-alerts to path for au_alerts_src package
_au_alerts_path = Path(__file__).parent.parent.parent / "antimicrobial-usage-alerts"
if str(_au_alerts_path) not in sys.path:
    sys.path.insert(0, str(_au_alerts_path))

from au_alerts_src.indication_db import IndicationDatabase


def _get_indication_db():
    """Get IndicationDatabase instance."""
    return IndicationDatabase()

abx_indications_bp = Blueprint(
    "abx_indications", __name__, url_prefix="/abx-indications"
)


@abx_indications_bp.route("/")
def dashboard():
    """Render the Antibiotic Indications dashboard."""
    try:
        db = _get_indication_db()

        # Get counts by classification (last 7 days)
        counts = db.get_candidate_count_by_classification(days=7)

        # Get recent candidates for the table
        recent_candidates = db.list_candidates(limit=20)

        # Get override stats
        override_stats = db.get_override_stats(days=30)

    except Exception as e:
        logger.error(f"Error loading indication data: {e}")
        counts = {}
        recent_candidates = []
        override_stats = {}

    return render_template(
        "abx_indications_dashboard.html",
        counts=counts,
        recent_candidates=recent_candidates,
        override_stats=override_stats,
    )


@abx_indications_bp.route("/help")
def help_page():
    """Render the help page for Antibiotic Indications."""
    return render_template("abx_indications_help.html")
