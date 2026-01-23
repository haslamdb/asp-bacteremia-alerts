"""HAI detection routes for the dashboard."""

import sys
from pathlib import Path

# CRITICAL: Add hai-detection to the FRONT of sys.path before any other imports
# This ensures hai-detection's src package is found instead of nhsn-reporting's
_hai_path = Path(__file__).parent.parent.parent / "hai-detection"
_hai_src_path = str(_hai_path)

# Remove any cached 'src' module to force reload from hai-detection
# This is needed because au_ar.py may have already imported nhsn-reporting's src
if 'src' in sys.modules:
    del sys.modules['src']
if 'src.models' in sys.modules:
    del sys.modules['src.models']
if 'src.db' in sys.modules:
    del sys.modules['src.db']
if 'src.config' in sys.modules:
    del sys.modules['src.config']

# Insert hai-detection at the front of sys.path
if _hai_src_path in sys.path:
    sys.path.remove(_hai_src_path)
sys.path.insert(0, _hai_src_path)

from flask import Blueprint, render_template, request, jsonify, current_app

# Now import from hai-detection's src (this will cache it)
from src.db import HAIDatabase
from src.config import Config as HAIConfig
from src.models import (
    HAIType, CandidateStatus, ClassificationDecision,
    ReviewQueueType, ReviewerDecision, HAICandidate
)

hai_detection_bp = Blueprint("hai_detection", __name__, url_prefix="/hai-detection")


def get_hai_db():
    """Get or create HAI database instance."""
    if not hasattr(current_app, "hai_db"):
        current_app.hai_db = HAIDatabase(HAIConfig.HAI_DB_PATH)
    return current_app.hai_db


@hai_detection_bp.route("/")
def dashboard():
    """HAI detection dashboard overview."""
    try:
        db = get_hai_db()

        stats = db.get_summary_stats()
        # Only show active candidates (not confirmed/rejected)
        recent = db.get_active_candidates(limit=10)
        pending_reviews = db.get_pending_reviews()

        return render_template(
            "hai_dashboard.html",
            stats=stats,
            recent_candidates=recent,
            pending_reviews=pending_reviews,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading HAI dashboard: {e}")
        return render_template(
            "hai_dashboard.html",
            stats={
                "total_candidates": 0,
                "pending_classification": 0,
                "pending_review": 0,
                "confirmed_hai": 0,
                "rejected_hai": 0,
            },
            recent_candidates=[],
            pending_reviews=[],
            error=str(e),
        )


@hai_detection_bp.route("/history")
def history():
    """Show resolved candidates (confirmed HAI or rejected)."""
    try:
        db = get_hai_db()

        # Get filter parameters
        status_filter = request.args.get("status")  # confirmed or rejected
        hai_type = request.args.get("type", "clabsi")

        if status_filter:
            # Specific status filter (confirmed or rejected only)
            try:
                status = CandidateStatus(status_filter)
                if status in (CandidateStatus.CONFIRMED, CandidateStatus.REJECTED):
                    candidates = db.get_candidates_by_status(
                        status, HAIType(hai_type) if hai_type else None
                    )
                else:
                    # Invalid filter for history, show all resolved
                    candidates = db.get_resolved_candidates(limit=100)
            except ValueError:
                candidates = db.get_resolved_candidates(limit=100)
        else:
            # Default: show all resolved candidates
            candidates = db.get_resolved_candidates(
                limit=100, hai_type=HAIType(hai_type) if hai_type else None
            )

        # Get stats
        stats = db.get_summary_stats()

        return render_template(
            "hai_history.html",
            candidates=candidates,
            stats=stats,
            current_status=status_filter,
            current_type=hai_type,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading history: {e}")
        return render_template(
            "hai_history.html",
            candidates=[],
            stats={},
            error=str(e),
        )


@hai_detection_bp.route("/candidates/<candidate_id>")
def candidate_detail(candidate_id):
    """Show candidate details."""
    try:
        db = get_hai_db()

        candidate = db.get_candidate(candidate_id)
        if not candidate:
            return render_template(
                "hai_candidate_not_found.html", candidate_id=candidate_id
            ), 404

        classifications = db.get_classifications_for_candidate(candidate_id)

        return render_template(
            "hai_candidate_detail.html",
            candidate=candidate,
            classifications=classifications,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading candidate {candidate_id}: {e}")
        return render_template(
            "hai_candidate_detail.html",
            candidate=None,
            error=str(e),
        ), 500


# API endpoints for HAI Detection
@hai_detection_bp.route("/api/stats")
def api_stats():
    """Get HAI statistics as JSON."""
    try:
        db = get_hai_db()
        stats = db.get_summary_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@hai_detection_bp.route("/api/candidates")
def api_candidates():
    """Get candidates as JSON."""
    try:
        db = get_hai_db()
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


@hai_detection_bp.route("/api/reviews/<review_id>/complete", methods=["POST"])
def api_complete_review(review_id):
    """Complete an IP review."""
    try:
        db = get_hai_db()

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


@hai_detection_bp.route("/api/candidates/<candidate_id>/review", methods=["POST"])
def api_submit_review(candidate_id):
    """Submit IP review for a candidate."""
    try:
        db = get_hai_db()
        from datetime import datetime
        import uuid

        data = request.json or {}
        reviewer = data.get("reviewer")
        decision = data.get("decision")
        notes = data.get("notes", "")
        override_reason = data.get("override_reason")  # Optional categorized reason

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

        # Get the LLM classification to determine if this is an override
        classifications = db.get_classifications_for_candidate(candidate_id)
        llm_decision = None
        classification_id = None
        is_override = False

        if classifications:
            latest_classification = classifications[0]  # Most recent
            classification_id = latest_classification.id
            llm_decision = latest_classification.decision.value

            # Determine if reviewer is overriding the LLM
            # LLM said HAI but reviewer says not HAI (rejected/mbi_lcbi/secondary)
            # LLM said not HAI but reviewer says confirmed
            if llm_decision == "hai_confirmed" and decision in ["rejected", "mbi_lcbi", "secondary"]:
                is_override = True
            elif llm_decision == "not_hai" and decision == "confirmed":
                is_override = True
            # pending_review from LLM is not considered an override either way

        # Update candidate status based on decision
        if decision == "confirmed":
            new_status = CandidateStatus.CONFIRMED
            if notes:
                notes = f"HAI confirmed. {notes}"
            else:
                notes = "HAI confirmed by IP review."
        elif decision == "mbi_lcbi":
            new_status = CandidateStatus.REJECTED
            notes = f"Not CLABSI - MBI-LCBI. {notes}" if notes else "Not CLABSI - classified as MBI-LCBI."
        elif decision == "secondary":
            new_status = CandidateStatus.REJECTED
            notes = f"Not CLABSI - Secondary to another infection. {notes}" if notes else "Not CLABSI - secondary to another infection source."
        elif decision == "rejected":
            new_status = CandidateStatus.REJECTED
            if notes:
                notes = f"Not HAI. {notes}"
            else:
                notes = "Not HAI."
        elif decision == "needs_more_info":
            # Keep in pending_review status so it stays in active list
            new_status = CandidateStatus.PENDING_REVIEW
            notes = f"Needs more information. {notes}" if notes else "Additional review required."
        else:
            new_status = candidate.status  # Keep current status

        # Save the review with override tracking
        is_final_decision = decision in ["confirmed", "rejected", "mbi_lcbi", "secondary"]
        review_id = db.save_review(
            candidate_id=candidate_id,
            reviewer=reviewer,
            decision=decision_enum,
            notes=notes,
            classification_id=classification_id,
            is_completed=is_final_decision,
            llm_decision=llm_decision,
            is_override=is_override,
            override_reason=override_reason,
        )

        # Only update candidate status for final decisions
        if is_final_decision:
            db.update_candidate_status(candidate_id, new_status)
            # Supersede any prior incomplete reviews (e.g., "needs_more_info")
            superseded_count = db.supersede_old_reviews(candidate_id, review_id)
            if superseded_count > 0:
                current_app.logger.info(
                    f"Superseded {superseded_count} prior incomplete review(s) for candidate {candidate_id}"
                )

        # Send email notification if configured
        try:
            _send_review_notification(candidate, decision, reviewer, notes)
        except Exception as e:
            current_app.logger.warning(f"Failed to send review notification: {e}")

        return jsonify({
            "success": True,
            "new_status": new_status.value,
            "is_override": is_override,
            "llm_decision": llm_decision,
        })

    except Exception as e:
        current_app.logger.error(f"Error submitting review: {e}")
        return jsonify({"error": str(e)}), 500


@hai_detection_bp.route("/api/override-stats")
def api_override_stats():
    """Get LLM classification override statistics."""
    try:
        db = get_hai_db()
        stats = db.get_override_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@hai_detection_bp.route("/api/recent-overrides")
def api_recent_overrides():
    """Get recent override details."""
    try:
        db = get_hai_db()
        limit = request.args.get("limit", 20, type=int)
        overrides = db.get_recent_overrides(limit=limit)
        return jsonify(overrides)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _send_review_notification(candidate, decision, reviewer, notes):
    """Send email notification about completed review."""
    from ..config import Config

    if not Config.SMTP_SERVER or not Config.HAI_NOTIFICATION_EMAIL:
        return  # Email not configured

    try:
        common_path = Path(__file__).parent.parent.parent / "common"
        if str(common_path) not in sys.path:
            sys.path.insert(0, str(common_path))

        from channels.email import EmailChannel, EmailMessage

        # Parse recipient list (can be comma-separated)
        recipients = [
            email.strip()
            for email in Config.HAI_NOTIFICATION_EMAIL.split(',')
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
            "confirmed": "HAI Confirmed",
            "rejected": "Not HAI",
            "mbi_lcbi": "Not CLABSI - MBI-LCBI",
            "secondary": "Not CLABSI - Secondary",
            "needs_more_info": "Needs More Information",
        }.get(decision, decision)

        subject = f"HAI Review Complete: {candidate.patient.mrn} - {decision_text}"
        body = f"""
HAI Review Completed

Patient: {candidate.patient.name} ({candidate.patient.mrn})
Organism: {candidate.culture.organism}
Culture Date: {candidate.culture.collection_date.strftime('%Y-%m-%d')}

Decision: {decision_text}
Reviewer: {reviewer}
Notes: {notes or 'None'}

View in Dashboard: {Config.DASHBOARD_BASE_URL}/hai-detection/candidates/{candidate.id}
"""

        message = EmailMessage(subject=subject, text_body=body)
        channel.send(message)

    except Exception as e:
        raise Exception(f"Email send failed: {e}")


@hai_detection_bp.route("/help")
def help_page():
    """Show HAI detection help and demo workflow documentation."""
    return render_template("hai_help.html")


@hai_detection_bp.route("/reports")
def reports():
    """Show HAI reports and analytics."""
    try:
        db = get_hai_db()

        # Get filter parameters
        hai_type_str = request.args.get("type")
        days_param = request.args.get("days", "30")

        # Handle numeric days
        try:
            days = int(days_param)
            if days < 1:
                days = 1
            elif days > 365:
                days = 365
        except ValueError:
            days = 30

        # Parse HAI type
        hai_type = None
        if hai_type_str:
            try:
                hai_type = HAIType(hai_type_str)
            except ValueError:
                hai_type = None

        # Get report data
        report_data = db.get_hai_report_data(days)

        # Get confirmed HAIs for the list
        confirmed_hais = db.get_confirmed_hai_in_period(days, hai_type)

        # Build HAI type options for filter
        hai_types = [
            ("", "All HAI Types"),
            ("clabsi", "CLABSI"),
            ("cauti", "CAUTI"),
            ("ssi", "SSI"),
            ("vae", "VAE"),
        ]

        # Get override statistics
        override_stats = db.get_override_stats()
        recent_overrides = db.get_recent_overrides(limit=10)

        return render_template(
            "hai_reports.html",
            report_data=report_data,
            confirmed_hais=confirmed_hais,
            hai_types=hai_types,
            current_type=hai_type_str or "",
            current_days=days_param,
            override_stats=override_stats,
            recent_overrides=recent_overrides,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading HAI reports: {e}")
        return render_template(
            "hai_reports.html",
            report_data={
                "total_confirmed": 0,
                "total_rejected": 0,
                "total_reviewed": 0,
                "confirmation_rate": 0,
                "by_type": {},
                "by_day": [],
                "review_breakdown": [],
            },
            confirmed_hais=[],
            hai_types=[("", "All HAI Types")],
            current_type="",
            current_days="30",
            override_stats={
                "total_reviews": 0,
                "completed_reviews": 0,
                "total_overrides": 0,
                "accepted_classifications": 0,
                "acceptance_rate_pct": None,
                "override_rate_pct": None,
                "by_llm_decision": {},
            },
            recent_overrides=[],
            error=str(e),
        )


# Redirect to NHSN Reporting for submission
@hai_detection_bp.route("/submission")
def submission():
    """Redirect to NHSN Reporting submission page."""
    from flask import redirect, url_for
    return redirect(url_for("nhsn_reporting.submission", type="hai", **request.args))
