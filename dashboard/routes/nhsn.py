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
        # Only show active candidates (not confirmed/rejected)
        recent = db.get_active_candidates(limit=10)
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
    """List active CLABSI candidates (pending review)."""
    try:
        db = get_nhsn_db()

        # Get filter parameters
        status_filter = request.args.get("status")
        hai_type = request.args.get("type", "clabsi")

        # Get candidates
        from src.models import CandidateStatus, HAIType

        if status_filter:
            # Specific status filter requested
            try:
                status = CandidateStatus(status_filter)
                candidates = db.get_candidates_by_status(
                    status, HAIType(hai_type) if hai_type else None
                )
            except ValueError:
                candidates = db.get_active_candidates(limit=100)
        else:
            # Default: show only active candidates (not confirmed/rejected)
            candidates = db.get_active_candidates(
                limit=100, hai_type=HAIType(hai_type) if hai_type else None
            )

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


@nhsn_bp.route("/history")
def history():
    """Show resolved candidates (confirmed CLABSI or rejected)."""
    try:
        db = get_nhsn_db()

        # Get filter parameters
        status_filter = request.args.get("status")  # confirmed or rejected
        hai_type = request.args.get("type", "clabsi")

        from src.models import CandidateStatus, HAIType

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
            "nhsn_history.html",
            candidates=candidates,
            stats=stats,
            current_status=status_filter,
            current_type=hai_type,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading history: {e}")
        return render_template(
            "nhsn_history.html",
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

        # Save the review with override tracking
        is_final_decision = decision in ["confirmed", "rejected", "mbi_lcbi", "secondary"]
        db.save_review(
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


@nhsn_bp.route("/api/override-stats")
def api_override_stats():
    """Get LLM classification override statistics."""
    try:
        db = get_nhsn_db()
        stats = db.get_override_stats()
        return jsonify(stats)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@nhsn_bp.route("/api/recent-overrides")
def api_recent_overrides():
    """Get recent override details."""
    try:
        db = get_nhsn_db()
        limit = request.args.get("limit", 20, type=int)
        overrides = db.get_recent_overrides(limit=limit)
        return jsonify(overrides)
    except Exception as e:
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


@nhsn_bp.route("/reports")
def reports():
    """Show HAI reports and analytics."""
    try:
        db = get_nhsn_db()
        from src.models import HAIType

        # Get filter parameters
        hai_type_str = request.args.get("type")
        days = request.args.get("days", 30, type=int)

        # Validate days
        if days < 1:
            days = 1
        elif days > 365:
            days = 365

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
            "nhsn_reports.html",
            report_data=report_data,
            confirmed_hais=confirmed_hais,
            hai_types=hai_types,
            current_type=hai_type_str or "",
            current_days=days,
            override_stats=override_stats,
            recent_overrides=recent_overrides,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading NHSN reports: {e}")
        return render_template(
            "nhsn_reports.html",
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
            current_days=30,
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


@nhsn_bp.route("/submission")
def submission():
    """NHSN data submission page."""
    try:
        db = get_nhsn_db()
        from datetime import datetime, timedelta

        # Get date range parameters
        from_date_str = request.args.get("from_date")
        to_date_str = request.args.get("to_date")
        preparer_name = request.args.get("preparer_name", "")

        # Default to current quarter if no dates provided
        today = datetime.now()
        if not from_date_str or not to_date_str:
            quarter = (today.month - 1) // 3
            quarter_start_month = quarter * 3 + 1
            from_date = datetime(today.year, quarter_start_month, 1)
            # End of quarter
            if quarter == 3:  # Q4
                to_date = datetime(today.year, 12, 31)
            else:
                to_date = datetime(today.year, quarter_start_month + 3, 1) - timedelta(days=1)
        else:
            from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
            to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

        # Get confirmed events in date range
        events = []
        if from_date_str and to_date_str:  # Only fetch if user submitted form
            events = db.get_confirmed_hai_in_date_range(from_date, to_date)

        # Get audit log
        audit_log = db.get_submission_audit_log(limit=10)

        # Get last submission info
        last_submission = db.get_last_submission()

        # Check DIRECT configuration
        from src.config import Config
        direct_configured = Config.is_direct_configured()
        direct_config = None
        if direct_configured:
            direct_config = {
                "facility_id": Config.NHSN_FACILITY_ID,
                "facility_name": Config.NHSN_FACILITY_NAME,
                "sender_address": Config.NHSN_SENDER_DIRECT_ADDRESS,
                "nhsn_address": Config.NHSN_DIRECT_ADDRESS,
            }

        return render_template(
            "nhsn_submission.html",
            events=events,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
            preparer_name=preparer_name,
            audit_log=audit_log,
            last_submission=last_submission,
            direct_configured=direct_configured,
            direct_config=direct_config,
        )
    except Exception as e:
        current_app.logger.error(f"Error loading NHSN submission page: {e}")
        from datetime import datetime
        today = datetime.now()
        return render_template(
            "nhsn_submission.html",
            events=[],
            from_date=today.strftime("%Y-%m-%d"),
            to_date=today.strftime("%Y-%m-%d"),
            preparer_name="",
            audit_log=[],
            last_submission=None,
            direct_configured=False,
            direct_config=None,
            error=str(e),
        )


@nhsn_bp.route("/submission/export", methods=["POST"])
def export_submission():
    """Export NHSN submission data as CSV or PDF."""
    try:
        db = get_nhsn_db()
        from datetime import datetime
        import csv
        import io

        from_date_str = request.form.get("from_date")
        to_date_str = request.form.get("to_date")
        preparer_name = request.form.get("preparer_name", "Unknown")
        export_format = request.form.get("format", "csv")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

        events = db.get_confirmed_hai_in_date_range(from_date, to_date)

        # Log the export
        db.log_submission_action(
            action="exported",
            user_name=preparer_name,
            period_start=from_date_str,
            period_end=to_date_str,
            event_count=len(events),
            notes=f"Exported as {export_format.upper()}",
        )

        if export_format == "csv":
            # Generate CSV
            output = io.StringIO()
            writer = csv.writer(output)

            # NHSN-compatible header
            writer.writerow([
                "Event_Date",
                "Patient_ID",
                "Patient_Name",
                "DOB",
                "Gender",
                "HAI_Type",
                "Event_Type",
                "Organism",
                "Device_Days",
                "Location_Code",
                "Central_Line_Type",
                "Notes",
            ])

            for event in events:
                writer.writerow([
                    event.culture.collection_date.strftime("%Y-%m-%d"),
                    event.patient.mrn,
                    event.patient.name or "",
                    event.patient.dob.strftime("%Y-%m-%d") if hasattr(event.patient, 'dob') and event.patient.dob else "",
                    event.patient.gender if hasattr(event.patient, 'gender') else "",
                    event.hai_type.value.upper(),
                    "BSI" if event.hai_type.value == "clabsi" else event.hai_type.value.upper(),
                    event.culture.organism or "",
                    event.device_days_at_culture if event.device_days_at_culture is not None else "",
                    event.location_code if hasattr(event, 'location_code') else "",
                    event.central_line_type if hasattr(event, 'central_line_type') else "",
                    "",  # Notes
                ])

            output.seek(0)
            from flask import Response
            filename = f"nhsn_submission_{from_date_str}_to_{to_date_str}.csv"
            return Response(
                output.getvalue(),
                mimetype="text/csv",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

        else:
            # Generate PDF summary (simple text for now)
            from flask import Response
            content = f"""NHSN HAI Submission Report
Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}
Prepared by: {preparer_name}
Period: {from_date_str} to {to_date_str}

Total Events: {len(events)}

Event Details:
"""
            for i, event in enumerate(events, 1):
                content += f"""
{i}. {event.hai_type.value.upper()} - {event.culture.collection_date.strftime('%Y-%m-%d')}
   Patient: {event.patient.mrn} ({event.patient.name or 'Unknown'})
   Organism: {event.culture.organism or 'Unknown'}
   Device Days: {event.device_days_at_culture if event.device_days_at_culture is not None else 'N/A'}
"""

            filename = f"nhsn_submission_{from_date_str}_to_{to_date_str}.txt"
            return Response(
                content,
                mimetype="text/plain",
                headers={"Content-Disposition": f"attachment; filename={filename}"}
            )

    except Exception as e:
        current_app.logger.error(f"Error exporting NHSN data: {e}")
        from flask import redirect, url_for, flash
        return redirect(url_for("nhsn.submission", error=str(e)))


@nhsn_bp.route("/submission/mark-submitted", methods=["POST"])
def mark_submitted():
    """Mark events as submitted to NHSN."""
    try:
        db = get_nhsn_db()
        from datetime import datetime
        from flask import redirect, url_for

        from_date_str = request.form.get("from_date")
        to_date_str = request.form.get("to_date")
        preparer_name = request.form.get("preparer_name", "Unknown")
        notes = request.form.get("notes", "")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

        # Get events and mark as submitted
        events = db.get_confirmed_hai_in_date_range(from_date, to_date)
        event_ids = [e.id for e in events]

        db.mark_events_as_submitted(event_ids)

        # Log the submission
        db.log_submission_action(
            action="submitted",
            user_name=preparer_name,
            period_start=from_date_str,
            period_end=to_date_str,
            event_count=len(events),
            notes=notes,
        )

        return redirect(url_for(
            "nhsn.submission",
            from_date=from_date_str,
            to_date=to_date_str,
            preparer_name=preparer_name,
            success_message=f"Marked {len(events)} events as submitted to NHSN."
        ))

    except Exception as e:
        current_app.logger.error(f"Error marking events as submitted: {e}")
        from flask import redirect, url_for
        return redirect(url_for("nhsn.submission", error=str(e)))


@nhsn_bp.route("/submission/direct", methods=["POST"])
def direct_submission():
    """Submit HAI events directly to NHSN via DIRECT protocol."""
    try:
        db = get_nhsn_db()
        from datetime import datetime
        from flask import redirect, url_for

        from_date_str = request.form.get("from_date")
        to_date_str = request.form.get("to_date")
        preparer_name = request.form.get("preparer_name", "Unknown")

        from_date = datetime.strptime(from_date_str, "%Y-%m-%d")
        to_date = datetime.strptime(to_date_str, "%Y-%m-%d")

        # Check if DIRECT is configured
        from src.config import Config
        if not Config.is_direct_configured():
            return redirect(url_for(
                "nhsn.submission",
                from_date=from_date_str,
                to_date=to_date_str,
                preparer_name=preparer_name,
                error="DIRECT protocol not configured. Please configure HISP credentials."
            ))

        # Get events
        events = db.get_confirmed_hai_in_date_range(from_date, to_date)
        if not events:
            return redirect(url_for(
                "nhsn.submission",
                from_date=from_date_str,
                to_date=to_date_str,
                preparer_name=preparer_name,
                error="No events to submit for the selected period."
            ))

        # Generate CDA documents
        from src.cda import CDAGenerator, create_bsi_document_from_candidate
        from src.direct import DirectClient

        direct_config = Config.get_direct_config()
        generator = CDAGenerator(
            facility_id=direct_config.facility_id,
            facility_name=direct_config.facility_name,
        )

        cda_documents = []
        for event in events:
            bsi_doc = create_bsi_document_from_candidate(
                event,
                facility_id=direct_config.facility_id,
                facility_name=direct_config.facility_name,
                author_name=preparer_name,
            )
            cda_xml = generator.generate_bsi_document(bsi_doc)
            cda_documents.append(cda_xml)

        # Submit via DIRECT
        client = DirectClient(direct_config)
        result = client.submit_cda_documents(
            cda_documents=cda_documents,
            submission_type="HAI-BSI",
            preparer_name=preparer_name,
        )

        if result.success:
            # Log the submission
            db.log_submission_action(
                action="direct_submitted",
                user_name=preparer_name,
                period_start=from_date_str,
                period_end=to_date_str,
                event_count=len(events),
                notes=f"DIRECT submission. Message ID: {result.message_id}",
            )

            # Mark events as submitted
            event_ids = [e.id for e in events]
            db.mark_events_as_submitted(event_ids)

            return redirect(url_for(
                "nhsn.submission",
                from_date=from_date_str,
                to_date=to_date_str,
                preparer_name=preparer_name,
                success_message=f"Successfully submitted {len(events)} events to NHSN via DIRECT. Message ID: {result.message_id}"
            ))
        else:
            return redirect(url_for(
                "nhsn.submission",
                from_date=from_date_str,
                to_date=to_date_str,
                preparer_name=preparer_name,
                error=f"DIRECT submission failed: {result.error_message}"
            ))

    except Exception as e:
        current_app.logger.error(f"Error in DIRECT submission: {e}")
        from flask import redirect, url_for
        return redirect(url_for("nhsn.submission", error=str(e)))


@nhsn_bp.route("/submission/test-direct", methods=["POST"])
def test_direct_connection():
    """Test the DIRECT protocol connection."""
    try:
        from src.config import Config
        from src.direct import DirectClient

        if not Config.is_direct_configured():
            return jsonify({
                "success": False,
                "message": "DIRECT protocol not configured",
            })

        direct_config = Config.get_direct_config()
        client = DirectClient(direct_config)
        success, message = client.test_connection()

        return jsonify({
            "success": success,
            "message": message,
        })

    except Exception as e:
        return jsonify({
            "success": False,
            "message": str(e),
        })
