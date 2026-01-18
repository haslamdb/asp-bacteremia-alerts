"""NHSN HAI reporting routes for the dashboard."""

import sys
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, current_app

# Add nhsn-reporting to path
nhsn_path = Path(__file__).parent.parent.parent / "nhsn-reporting"
if str(nhsn_path) not in sys.path:
    sys.path.insert(0, str(nhsn_path))

nhsn_bp = Blueprint("nhsn", __name__, url_prefix="/nhsn")


def get_nhsn_db():
    """Get or create NHSN database instance."""
    if not hasattr(current_app, "nhsn_db"):
        from src.db import NHSNDatabase
        from src.config import Config

        current_app.nhsn_db = NHSNDatabase(Config.NHSN_DB_PATH)
    return current_app.nhsn_db


@nhsn_bp.route("/")
def dashboard():
    """NHSN reporting dashboard overview."""
    try:
        db = get_nhsn_db()
        stats = db.get_summary_stats()
        recent = db.get_recent_candidates(limit=10)
        pending_reviews = db.get_pending_reviews()

        return render_template(
            "nhsn_dashboard.html",
            stats=stats,
            recent_candidates=recent,
            pending_reviews=pending_reviews,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading NHSN dashboard: {e}")
        return render_template(
            "nhsn_dashboard.html",
            stats={
                "total_candidates": 0,
                "pending_classification": 0,
                "pending_review": 0,
                "confirmed_hai": 0,
                "total_events": 0,
                "unreported_events": 0,
            },
            recent_candidates=[],
            pending_reviews=[],
            error=str(e),
        )


@nhsn_bp.route("/candidates")
def candidates():
    """List all CLABSI candidates."""
    try:
        db = get_nhsn_db()

        # Get filter parameters
        status_filter = request.args.get("status")
        hai_type = request.args.get("type", "clabsi")

        # Get candidates
        from src.models import CandidateStatus, HAIType

        if status_filter:
            try:
                status = CandidateStatus(status_filter)
                candidates = db.get_candidates_by_status(
                    status, HAIType(hai_type) if hai_type else None
                )
            except ValueError:
                candidates = db.get_recent_candidates(limit=100)
        else:
            candidates = db.get_recent_candidates(limit=100)

        # Get stats
        stats = db.get_summary_stats()

        return render_template(
            "nhsn_candidates.html",
            candidates=candidates,
            stats=stats,
            current_status=status_filter,
            current_type=hai_type,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading candidates: {e}")
        return render_template(
            "nhsn_candidates.html",
            candidates=[],
            stats={},
            error=str(e),
        )


@nhsn_bp.route("/candidates/<candidate_id>")
def candidate_detail(candidate_id):
    """Show candidate details."""
    try:
        db = get_nhsn_db()

        candidate = db.get_candidate(candidate_id)
        if not candidate:
            return render_template(
                "nhsn_candidate_not_found.html", candidate_id=candidate_id
            ), 404

        classifications = db.get_classifications_for_candidate(candidate_id)

        return render_template(
            "nhsn_candidate_detail.html",
            candidate=candidate,
            classifications=classifications,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading candidate {candidate_id}: {e}")
        return render_template(
            "nhsn_candidate_detail.html",
            candidate=None,
            error=str(e),
        ), 500


@nhsn_bp.route("/reviews")
def reviews():
    """List pending IP reviews."""
    try:
        db = get_nhsn_db()

        queue_type = request.args.get("queue")
        from src.models import ReviewQueueType

        if queue_type:
            try:
                pending = db.get_pending_reviews(ReviewQueueType(queue_type))
            except ValueError:
                pending = db.get_pending_reviews()
        else:
            pending = db.get_pending_reviews()

        return render_template(
            "nhsn_reviews.html",
            reviews=pending,
            current_queue=queue_type,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading reviews: {e}")
        return render_template(
            "nhsn_reviews.html",
            reviews=[],
            error=str(e),
        )


# API endpoints for NHSN
@nhsn_bp.route("/api/stats")
def api_stats():
    """Get NHSN statistics as JSON."""
    try:
        db = get_nhsn_db()
        stats = db.get_summary_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_bp.route("/api/candidates")
def api_candidates():
    """Get candidates as JSON."""
    try:
        db = get_nhsn_db()
        limit = request.args.get("limit", 100, type=int)
        candidates = db.get_recent_candidates(limit=limit)

        return jsonify([
            {
                "id": c.id,
                "hai_type": c.hai_type.value,
                "patient_mrn": c.patient.mrn,
                "patient_name": c.patient.name,
                "organism": c.culture.organism,
                "culture_date": c.culture.collection_date.isoformat(),
                "device_days": c.device_days_at_culture,
                "meets_criteria": c.meets_initial_criteria,
                "status": c.status.value,
                "created_at": c.created_at.isoformat(),
            }
            for c in candidates
        ])
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_bp.route("/api/reviews/<review_id>/complete", methods=["POST"])
def api_complete_review(review_id):
    """Complete an IP review."""
    try:
        db = get_nhsn_db()
        from src.models import ReviewerDecision

        data = request.json or {}
        reviewer = data.get("reviewer", "dashboard_user")
        decision = data.get("decision")
        notes = data.get("notes")

        if not decision:
            return jsonify({"error": "decision is required"}), 400

        try:
            decision_enum = ReviewerDecision(decision)
        except ValueError:
            return jsonify({"error": f"Invalid decision: {decision}"}), 400

        db.complete_review(review_id, reviewer, decision_enum, notes)

        return jsonify({"success": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_bp.route("/api/candidates/<candidate_id>/review", methods=["POST"])
def api_submit_review(candidate_id):
    """Submit IP review for a candidate."""
    try:
        db = get_nhsn_db()
        from src.models import ReviewerDecision, CandidateStatus
        from datetime import datetime
        import uuid

        data = request.json or {}
        reviewer = data.get("reviewer")
        decision = data.get("decision")
        notes = data.get("notes", "")

        if not reviewer:
            return jsonify({"error": "reviewer is required"}), 400
        if not decision:
            return jsonify({"error": "decision is required"}), 400

        # Map form decision to ReviewerDecision enum
        decision_map = {
            "confirmed": ReviewerDecision.CONFIRMED,
            "rejected": ReviewerDecision.REJECTED,
            "mbi_lcbi": ReviewerDecision.REJECTED,  # MBI-LCBI is Not CLABSI
            "secondary": ReviewerDecision.REJECTED,  # Secondary source is Not CLABSI
            "needs_more_info": ReviewerDecision.NEEDS_MORE_INFO,
        }

        if decision not in decision_map:
            return jsonify({"error": f"Invalid decision: {decision}"}), 400

        decision_enum = decision_map[decision]

        # Get the candidate
        candidate = db.get_candidate(candidate_id)
        if not candidate:
            return jsonify({"error": "Candidate not found"}), 404

        # Create or update review record
        review_id = str(uuid.uuid4())

        # Update candidate status based on decision
        if decision == "confirmed":
            new_status = CandidateStatus.CONFIRMED
            if notes:
                notes = f"CLABSI confirmed. {notes}"
            else:
                notes = "CLABSI confirmed by IP review."
        elif decision == "mbi_lcbi":
            new_status = CandidateStatus.REJECTED
            notes = f"Not CLABSI - MBI-LCBI. {notes}" if notes else "Not CLABSI - classified as MBI-LCBI."
        elif decision == "secondary":
            new_status = CandidateStatus.REJECTED
            notes = f"Not CLABSI - Secondary to another infection. {notes}" if notes else "Not CLABSI - secondary to another infection source."
        elif decision == "rejected":
            new_status = CandidateStatus.REJECTED
            if notes:
                notes = f"Not CLABSI. {notes}"
            else:
                notes = "Not CLABSI."
        elif decision == "needs_more_info":
            # Keep in pending_review status so it stays in active list
            new_status = CandidateStatus.PENDING_REVIEW
            notes = f"Needs more information. {notes}" if notes else "Additional review required."
        else:
            new_status = candidate.status  # Keep current status

        # Save the review (but mark as not completed for needs_more_info)
        is_final_decision = decision in ["confirmed", "rejected", "mbi_lcbi", "secondary"]
        db.save_review(
            candidate_id=candidate_id,
            reviewer=reviewer,
            decision=decision_enum,
            notes=notes,
            is_completed=is_final_decision,
        )

        # Only update candidate status for final decisions
        if is_final_decision:
            db.update_candidate_status(candidate_id, new_status)

        # Send email notification if configured
        try:
            _send_review_notification(candidate, decision, reviewer, notes)
        except Exception as e:
            current_app.logger.warning(f"Failed to send review notification: {e}")

        return jsonify({
            "success": True,
            "new_status": new_status.value,
        })

    except Exception as e:
        current_app.logger.error(f"Error submitting review: {e}")
        return jsonify({"error": str(e)}), 500


def _send_review_notification(candidate, decision, reviewer, notes):
    """Send email notification about completed review."""
    from ..config import Config

    if not Config.SMTP_SERVER or not Config.NHSN_NOTIFICATION_EMAIL:
        return  # Email not configured

    try:
        import sys
        from pathlib import Path
        common_path = Path(__file__).parent.parent.parent / "common"
        if str(common_path) not in sys.path:
            sys.path.insert(0, str(common_path))

        from channels.email import EmailChannel, EmailMessage

        # Parse recipient list (can be comma-separated)
        recipients = [
            email.strip()
            for email in Config.NHSN_NOTIFICATION_EMAIL.split(',')
            if email.strip()
        ]

        channel = EmailChannel(
            smtp_server=Config.SMTP_SERVER,
            smtp_port=Config.SMTP_PORT,
            smtp_username=Config.SMTP_USERNAME or None,
            smtp_password=Config.SMTP_PASSWORD or None,
            from_address=f"{Config.SENDER_NAME} <{Config.SENDER_EMAIL}>",
            to_addresses=recipients,
        )

        decision_text = {
            "confirmed": "CLABSI Confirmed",
            "rejected": "Not CLABSI",
            "mbi_lcbi": "Not CLABSI - MBI-LCBI",
            "secondary": "Not CLABSI - Secondary",
            "needs_more_info": "Needs More Information",
        }.get(decision, decision)

        subject = f"NHSN Review Complete: {candidate.patient.mrn} - {decision_text}"
        body = f"""
NHSN HAI Review Completed

Patient: {candidate.patient.name} ({candidate.patient.mrn})
Organism: {candidate.culture.organism}
Culture Date: {candidate.culture.collection_date.strftime('%Y-%m-%d')}

Decision: {decision_text}
Reviewer: {reviewer}
Notes: {notes or 'None'}

View in Dashboard: {Config.DASHBOARD_BASE_URL}/nhsn/candidates/{candidate.id}
"""

        message = EmailMessage(subject=subject, text_body=body)
        channel.send(message)

    except Exception as e:
        raise Exception(f"Email send failed: {e}")


@nhsn_bp.route("/help")
def help_page():
    """Show NHSN help and demo workflow documentation."""
    return render_template("nhsn_help.html")
