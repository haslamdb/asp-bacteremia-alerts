"""Routes for Antibiotic Indications module.

This module provides ICD-10 based antibiotic appropriateness classification
following Chua et al. methodology with pediatric inpatient modifications.
"""

import logging
import sys
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify

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
        recent_candidates = db.list_candidates(limit=50)

        # Get override stats
        override_stats = db.get_override_stats(days=30)

        # Get usage summary for analytics section
        usage_summary = db.get_usage_summary(days=30)

    except Exception as e:
        logger.error(f"Error loading indication data: {e}")
        counts = {}
        recent_candidates = []
        override_stats = {}
        usage_summary = {}

    return render_template(
        "abx_indications_dashboard.html",
        counts=counts,
        recent_candidates=recent_candidates,
        override_stats=override_stats,
        usage_summary=usage_summary,
    )


@abx_indications_bp.route("/candidate/<candidate_id>")
def candidate_detail(candidate_id: str):
    """Render the candidate detail page for review."""
    try:
        db = _get_indication_db()
        candidate = db.get_candidate(candidate_id)

        if not candidate:
            return render_template(
                "abx_indication_not_found.html",
                candidate_id=candidate_id,
            ), 404

        # Get extraction history for this candidate (if we have it)
        extraction = None
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM indication_extractions
                WHERE candidate_id = ?
                ORDER BY created_at DESC LIMIT 1
                """,
                (candidate_id,),
            )
            row = cursor.fetchone()
            if row:
                import json
                extraction = {
                    "model_used": row["model_used"],
                    "prompt_version": row["prompt_version"],
                    "indications": json.loads(row["extracted_indications"]) if row["extracted_indications"] else [],
                    "supporting_quotes": json.loads(row["supporting_quotes"]) if row["supporting_quotes"] else [],
                    "confidence": row["confidence"],
                    "tokens_used": row["tokens_used"],
                    "response_time_ms": row["response_time_ms"],
                    "created_at": row["created_at"],
                }

        # Get review history
        reviews = []
        with db._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM indication_reviews
                WHERE candidate_id = ?
                ORDER BY reviewed_at DESC
                """,
                (candidate_id,),
            )
            for row in cursor.fetchall():
                reviews.append({
                    "reviewer": row["reviewer"],
                    "decision": row["reviewer_decision"],
                    "is_override": row["is_override"],
                    "override_reason": row["override_reason"],
                    "notes": row["notes"],
                    "reviewed_at": row["reviewed_at"],
                })

        return render_template(
            "abx_indication_detail.html",
            candidate=candidate,
            extraction=extraction,
            reviews=reviews,
        )

    except Exception as e:
        logger.error(f"Error loading candidate {candidate_id}: {e}")
        return render_template(
            "abx_indication_not_found.html",
            candidate_id=candidate_id,
            error=str(e),
        ), 500


@abx_indications_bp.route("/candidate/<candidate_id>/review", methods=["POST"])
def submit_review(candidate_id: str):
    """Submit a review decision for a candidate."""
    try:
        db = _get_indication_db()
        data = request.get_json()

        reviewer = data.get("reviewer", "").strip()
        decision = data.get("decision", "").strip()
        notes = data.get("notes", "").strip()

        if not reviewer:
            return jsonify({"success": False, "error": "Reviewer name required"}), 400

        if not decision:
            return jsonify({"success": False, "error": "Decision required"}), 400

        # Get current candidate to check for override
        candidate = db.get_candidate(candidate_id)
        if not candidate:
            return jsonify({"success": False, "error": "Candidate not found"}), 404

        # Determine if this is an override
        # Map decision to classification
        decision_to_classification = {
            "confirm_appropriate": "A",
            "confirm_sometimes": "S",
            "confirm_inappropriate": "N",
            "override_to_appropriate": "A",
            "override_to_sometimes": "S",
            "override_to_inappropriate": "N",
            "override_to_prophylaxis": "P",
        }

        new_classification = decision_to_classification.get(decision)
        is_override = new_classification and new_classification != candidate.final_classification

        # Require override reason if overriding
        override_reason = data.get("override_reason", "").strip() if is_override else None

        # Save the review
        review_id = db.save_review(
            candidate_id=candidate_id,
            reviewer=reviewer,
            decision=decision,
            is_override=is_override,
            override_reason=override_reason,
            llm_decision=candidate.llm_classification,
            notes=notes,
        )

        return jsonify({
            "success": True,
            "review_id": review_id,
            "is_override": is_override,
            "message": "Review submitted successfully",
        })

    except Exception as e:
        logger.error(f"Error submitting review for {candidate_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@abx_indications_bp.route("/analytics")
def analytics():
    """Render analytics dashboard."""
    try:
        db = _get_indication_db()

        summary = db.get_usage_summary(days=30)
        by_antibiotic = db.get_usage_by_antibiotic(days=30)
        by_location = db.get_usage_by_location(days=30)
        by_service = db.get_usage_by_service(days=30)
        daily_trend = db.get_daily_usage_trend(days=30)
        override_stats = db.get_override_stats(days=30)

        return render_template(
            "abx_indications_analytics.html",
            summary=summary,
            by_antibiotic=by_antibiotic,
            by_location=by_location,
            by_service=by_service,
            daily_trend=daily_trend,
            override_stats=override_stats,
        )

    except Exception as e:
        logger.error(f"Error loading analytics: {e}")
        return render_template(
            "abx_indications_analytics.html",
            error=str(e),
        )


@abx_indications_bp.route("/help")
def help_page():
    """Render the help page for Antibiotic Indications."""
    return render_template("abx_indications_help.html")


@abx_indications_bp.route("/candidate/<candidate_id>/acknowledge", methods=["POST"])
def acknowledge_candidate(candidate_id: str):
    """Quick acknowledge/dismiss a candidate without full review.

    This marks the candidate as reviewed but doesn't require all the
    review fields. Used for quickly clearing the queue.
    """
    try:
        db = _get_indication_db()
        data = request.get_json() or {}

        reviewer = data.get("reviewer", "system").strip()
        notes = data.get("notes", "Acknowledged without detailed review").strip()

        candidate = db.get_candidate(candidate_id)
        if not candidate:
            return jsonify({"success": False, "error": "Candidate not found"}), 404

        # Save as a simple acknowledgment (not an override)
        review_id = db.save_review(
            candidate_id=candidate_id,
            reviewer=reviewer,
            decision="acknowledged",
            is_override=False,
            notes=notes,
        )

        return jsonify({
            "success": True,
            "review_id": review_id,
            "message": "Candidate acknowledged",
        })

    except Exception as e:
        logger.error(f"Error acknowledging candidate {candidate_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@abx_indications_bp.route("/acknowledge-all", methods=["POST"])
def acknowledge_all():
    """Acknowledge all pending candidates at once.

    Useful for clearing the queue when doing bulk review.
    """
    try:
        db = _get_indication_db()
        data = request.get_json() or {}

        reviewer = data.get("reviewer", "system").strip()
        notes = data.get("notes", "Bulk acknowledged").strip()

        # Get all pending candidates
        pending = db.list_candidates(status="pending", limit=1000)

        count = 0
        for candidate in pending:
            db.save_review(
                candidate_id=candidate.id,
                reviewer=reviewer,
                decision="acknowledged",
                is_override=False,
                notes=notes,
            )
            count += 1

        return jsonify({
            "success": True,
            "acknowledged_count": count,
            "message": f"Acknowledged {count} pending candidates",
        })

    except Exception as e:
        logger.error(f"Error in bulk acknowledge: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@abx_indications_bp.route("/pending")
def pending_list():
    """Show only pending candidates that need review."""
    try:
        db = _get_indication_db()

        # Get only pending candidates
        pending_candidates = db.list_candidates(status="pending", limit=100)

        # Get counts by classification for pending only
        counts = {}
        for c in pending_candidates:
            cls = c.final_classification or "U"
            counts[cls] = counts.get(cls, 0) + 1

        return render_template(
            "abx_indications_pending.html",
            candidates=pending_candidates,
            counts=counts,
            total_pending=len(pending_candidates),
        )

    except Exception as e:
        logger.error(f"Error loading pending candidates: {e}")
        return render_template(
            "abx_indications_pending.html",
            candidates=[],
            counts={},
            total_pending=0,
            error=str(e),
        )
