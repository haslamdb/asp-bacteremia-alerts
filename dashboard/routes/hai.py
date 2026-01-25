"""HAI detection routes for the dashboard."""

import sys
from pathlib import Path

# Add hai-detection to path for hai_src package
_hai_path = Path(__file__).parent.parent.parent / "hai-detection"
if str(_hai_path) not in sys.path:
    sys.path.insert(0, str(_hai_path))

from flask import Blueprint, render_template, request, jsonify, current_app

from hai_src.db import HAIDatabase
from hai_src.config import Config as HAIConfig
from hai_src.models import (
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

        # Extract SSI-specific data if available
        ssi_data = None
        if candidate.hai_type == HAIType.SSI and hasattr(candidate, "_ssi_data"):
            ssi_candidate = candidate._ssi_data
            if ssi_candidate and hasattr(ssi_candidate, "procedure"):
                proc = ssi_candidate.procedure
                ssi_data = {
                    "procedure_name": proc.procedure_name,
                    "procedure_code": proc.procedure_code,
                    "nhsn_category": proc.nhsn_category or "Unknown",
                    "procedure_date": proc.procedure_date,
                    "wound_class": proc.wound_class,
                    "implant_used": proc.implant_used,
                    "implant_type": proc.implant_type,
                    "days_post_op": ssi_candidate.days_post_op,
                    "surveillance_days": proc.get_surveillance_days(),
                    "ssi_type": getattr(ssi_candidate, "ssi_type", None),
                }

        return render_template(
            "hai_candidate_detail.html",
            candidate=candidate,
            classifications=classifications,
            ssi_data=ssi_data,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading candidate {candidate_id}: {e}")
        return render_template(
            "hai_candidate_detail.html",
            candidate=None,
            classifications=None,
            ssi_data=None,
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
            # SSI-specific type decisions (all confirm as SSI)
            "superficial_ssi": ReviewerDecision.CONFIRMED,
            "deep_ssi": ReviewerDecision.CONFIRMED,
            "organ_space_ssi": ReviewerDecision.CONFIRMED,
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
            # LLM said not HAI but reviewer confirms (confirmed or SSI type)
            confirm_decisions = ["confirmed", "superficial_ssi", "deep_ssi", "organ_space_ssi"]
            reject_decisions = ["rejected", "mbi_lcbi", "secondary"]
            if llm_decision == "hai_confirmed" and decision in reject_decisions:
                is_override = True
            elif llm_decision == "not_hai" and decision in confirm_decisions:
                is_override = True
            # pending_review from LLM is not considered an override either way

        # Update candidate status based on decision
        if decision == "confirmed":
            new_status = CandidateStatus.CONFIRMED
            if notes:
                notes = f"HAI confirmed. {notes}"
            else:
                notes = "HAI confirmed by IP review."
        # SSI-specific type confirmations
        elif decision == "superficial_ssi":
            new_status = CandidateStatus.CONFIRMED
            notes = f"SSI confirmed - Superficial Incisional. {notes}" if notes else "SSI confirmed - Superficial Incisional SSI."
        elif decision == "deep_ssi":
            new_status = CandidateStatus.CONFIRMED
            notes = f"SSI confirmed - Deep Incisional. {notes}" if notes else "SSI confirmed - Deep Incisional SSI."
        elif decision == "organ_space_ssi":
            new_status = CandidateStatus.CONFIRMED
            notes = f"SSI confirmed - Organ/Space. {notes}" if notes else "SSI confirmed - Organ/Space SSI."
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
        is_final_decision = decision in [
            "confirmed", "rejected", "mbi_lcbi", "secondary",
            "superficial_ssi", "deep_ssi", "organ_space_ssi"
        ]
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
            "superficial_ssi": "SSI Confirmed - Superficial Incisional",
            "deep_ssi": "SSI Confirmed - Deep Incisional",
            "organ_space_ssi": "SSI Confirmed - Organ/Space",
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
