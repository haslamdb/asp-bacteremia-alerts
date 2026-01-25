"""Routes for Guideline Adherence module.

This module tracks adherence to evidence-based clinical guidelines/bundles
at the population level for quality improvement and JC reporting.
"""

import sys
from pathlib import Path
from flask import Blueprint, render_template, current_app, request

# Add paths for guideline adherence imports
GUIDELINE_PATH = Path(__file__).parent.parent.parent / "guideline-adherence"
if str(GUIDELINE_PATH) not in sys.path:
    sys.path.insert(0, str(GUIDELINE_PATH))

try:
    from guideline_adherence import GUIDELINE_BUNDLES
    from guideline_src.adherence_db import AdherenceDatabase
    from guideline_src.config import config as adherence_config
except ImportError:
    GUIDELINE_BUNDLES = {}
    AdherenceDatabase = None
    adherence_config = None


guideline_adherence_bp = Blueprint(
    "guideline_adherence", __name__, url_prefix="/guideline-adherence"
)


def get_adherence_db():
    """Get adherence database instance."""
    if AdherenceDatabase is None:
        return None
    return AdherenceDatabase()


@guideline_adherence_bp.route("/")
def dashboard():
    """Render the Guideline Adherence dashboard with real data."""
    db = get_adherence_db()

    # Get metrics
    metrics = None
    active_episodes = []
    bundle_stats = []

    if db:
        try:
            # Get overall metrics
            metrics = db.get_compliance_metrics(days=30)

            # Get active episodes
            active_episodes = db.get_active_episodes()[:10]  # Top 10

            # Get per-bundle stats
            for bundle_id, bundle in GUIDELINE_BUNDLES.items():
                bundle_metrics = db.get_compliance_metrics(bundle_id=bundle_id, days=30)
                element_rates = bundle_metrics.get("element_rates", [])
                avg_rate = 0
                if element_rates:
                    avg_rate = sum(e["compliance_rate"] for e in element_rates) / len(element_rates)

                bundle_stats.append({
                    "bundle_id": bundle_id,
                    "bundle_name": bundle.name,
                    "total_episodes": bundle_metrics.get("episode_counts", {}).get("total", 0),
                    "active_episodes": bundle_metrics.get("episode_counts", {}).get("active", 0),
                    "avg_compliance": round(avg_rate, 1),
                    "element_count": len(bundle.elements),
                })
        except Exception as e:
            current_app.logger.error(f"Error loading adherence data: {e}")

    return render_template(
        "guideline_adherence_dashboard.html",
        metrics=metrics,
        active_episodes=active_episodes,
        bundle_stats=bundle_stats,
        bundles=GUIDELINE_BUNDLES,
    )


@guideline_adherence_bp.route("/active")
def active_episodes():
    """Show patients with active bundles being monitored."""
    db = get_adherence_db()
    bundle_filter = request.args.get("bundle")

    episodes = []
    if db:
        try:
            episodes = db.get_active_episodes(bundle_id=bundle_filter)

            # Enrich with latest results
            for episode in episodes:
                results = db.get_episode_results(episode["id"])
                episode["results"] = results

                # Calculate current adherence
                met = sum(1 for r in results if r.get("status") == "met")
                not_met = sum(1 for r in results if r.get("status") == "not_met")
                total = met + not_met
                episode["adherence_pct"] = round((met / total) * 100, 1) if total > 0 else 100

        except Exception as e:
            current_app.logger.error(f"Error loading active episodes: {e}")

    return render_template(
        "guideline_adherence_active.html",
        episodes=episodes,
        bundles=GUIDELINE_BUNDLES,
        current_bundle=bundle_filter,
    )


@guideline_adherence_bp.route("/episode/<episode_id>")
def episode_detail(episode_id):
    """Show element timeline for a specific episode."""
    db = get_adherence_db()

    episode = None
    results = []
    bundle = None

    if db:
        try:
            episode = db.get_episode(episode_id)
            if episode:
                results = db.get_episode_results(episode_id)
                bundle = GUIDELINE_BUNDLES.get(episode.get("bundle_id"))
        except Exception as e:
            current_app.logger.error(f"Error loading episode {episode_id}: {e}")

    if not episode:
        return render_template("guideline_adherence_episode_not_found.html", episode_id=episode_id), 404

    return render_template(
        "guideline_adherence_episode.html",
        episode=episode,
        results=results,
        bundle=bundle,
    )


@guideline_adherence_bp.route("/metrics")
def compliance_metrics():
    """Show aggregate compliance rates and trends."""
    db = get_adherence_db()
    bundle_filter = request.args.get("bundle")
    days = request.args.get("days", 30, type=int)

    metrics = None
    bundle_metrics = []

    if db:
        try:
            # Overall metrics
            metrics = db.get_compliance_metrics(bundle_id=bundle_filter, days=days)

            # Per-bundle breakdown
            for bundle_id, bundle in GUIDELINE_BUNDLES.items():
                bm = db.get_compliance_metrics(bundle_id=bundle_id, days=days)
                bundle_metrics.append({
                    "bundle_id": bundle_id,
                    "bundle_name": bundle.name,
                    "metrics": bm,
                })
        except Exception as e:
            current_app.logger.error(f"Error loading metrics: {e}")

    return render_template(
        "guideline_adherence_metrics.html",
        metrics=metrics,
        bundle_metrics=bundle_metrics,
        bundles=GUIDELINE_BUNDLES,
        current_bundle=bundle_filter,
        current_days=days,
    )


@guideline_adherence_bp.route("/bundle/<bundle_id>")
def bundle_detail(bundle_id):
    """Show details and element compliance for a specific bundle."""
    bundle = GUIDELINE_BUNDLES.get(bundle_id)
    if not bundle:
        return render_template("guideline_adherence_bundle_not_found.html", bundle_id=bundle_id), 404

    db = get_adherence_db()
    metrics = None
    recent_episodes = []

    if db:
        try:
            metrics = db.get_compliance_metrics(bundle_id=bundle_id, days=30)
            recent_episodes = [
                e for e in db.get_active_episodes(bundle_id=bundle_id)
            ][:10]
        except Exception as e:
            current_app.logger.error(f"Error loading bundle data: {e}")

    return render_template(
        "guideline_adherence_bundle.html",
        bundle=bundle,
        metrics=metrics,
        recent_episodes=recent_episodes,
    )


@guideline_adherence_bp.route("/help")
def help_page():
    """Render the help page for Guideline Adherence."""
    return render_template(
        "guideline_adherence_help.html",
        bundles=GUIDELINE_BUNDLES,
    )
