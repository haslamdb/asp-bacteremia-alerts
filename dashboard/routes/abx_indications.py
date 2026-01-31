"""Routes for Antibiotic Indications module.

This module provides ICD-10 based antibiotic appropriateness classification
following Chua et al. methodology with pediatric inpatient modifications.
"""

import logging
import sys
from pathlib import Path

from flask import Blueprint, render_template, request, jsonify, current_app

from dashboard.services.user import get_user_from_request
from dashboard.services.fhir import FHIRService

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

        # Get counts by classification (last 7 days) - for pending only
        pending_candidates = db.list_candidates(status="pending", limit=100)
        counts = {}
        for c in pending_candidates:
            cls = c.final_classification or "U"
            counts[cls] = counts.get(cls, 0) + 1

        # Get override stats
        override_stats = db.get_override_stats(days=30)

        # Get usage summary for analytics section
        usage_summary = db.get_usage_summary(days=30)

        # Count reviewed for display
        reviewed_count = db.get_reviewed_candidates_count()

    except Exception as e:
        logger.error(f"Error loading indication data: {e}")
        counts = {}
        pending_candidates = []
        override_stats = {}
        usage_summary = {}
        reviewed_count = 0

    return render_template(
        "abx_indications_dashboard.html",
        counts=counts,
        recent_candidates=pending_candidates,  # Only show pending
        override_stats=override_stats,
        usage_summary=usage_summary,
        reviewed_count=reviewed_count,
    )


@abx_indications_bp.route("/candidate/<candidate_id>")
def candidate_detail(candidate_id: str):
    """Render the candidate detail page for review."""
    try:
        import json

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
                # Parse evidence sources (new v2 format)
                evidence_sources = []
                row_keys = row.keys()
                if "evidence_sources" in row_keys and row["evidence_sources"]:
                    try:
                        raw_sources = json.loads(row["evidence_sources"])
                        for src in raw_sources:
                            evidence_sources.append({
                                "note_type": src.get("note_type", "UNKNOWN"),
                                "note_date": src.get("note_date"),
                                "author": src.get("author"),
                                "quotes": src.get("quotes", []),
                                "relevance": src.get("relevance"),
                            })
                    except json.JSONDecodeError:
                        pass

                # Get note counts (new v2 fields)
                notes_filtered_count = row["notes_filtered_count"] if "notes_filtered_count" in row_keys else None
                notes_total_count = row["notes_total_count"] if "notes_total_count" in row_keys else None

                extraction = {
                    "model_used": row["model_used"],
                    "prompt_version": row["prompt_version"],
                    "indications": json.loads(row["extracted_indications"]) if row["extracted_indications"] else [],
                    "supporting_quotes": json.loads(row["supporting_quotes"]) if row["supporting_quotes"] else [],
                    "confidence": row["confidence"],
                    "tokens_used": row["tokens_used"],
                    "response_time_ms": row["response_time_ms"],
                    "created_at": row["created_at"],
                    # New v2 fields
                    "evidence_sources": evidence_sources,
                    "notes_filtered_count": notes_filtered_count,
                    "notes_total_count": notes_total_count,
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

        # Get clinical context if patient_id is available
        clinical_context = None
        if candidate.patient and candidate.patient.fhir_id:
            fhir_url = current_app.config.get("FHIR_SERVER_URL")
            if fhir_url:
                fhir = FHIRService(fhir_url)
                try:
                    clinical_context = fhir.get_clinical_context(candidate.patient.fhir_id)
                except Exception:
                    pass  # Clinical context is optional enhancement

        return render_template(
            "abx_indication_detail.html",
            candidate=candidate,
            extraction=extraction,
            reviews=reviews,
            clinical_context=clinical_context,
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
    """Submit a review decision for a candidate.

    Supports both legacy (A/S/N/P) and new JC-compliant (syndrome) review workflows.
    The new workflow focuses on syndrome verification and optional agent appropriateness.
    """
    try:
        db = _get_indication_db()
        data = request.get_json()

        reviewer = get_user_from_request()
        notes = data.get("notes", "").strip()

        if not reviewer:
            return jsonify({"success": False, "error": "Reviewer name required"}), 400

        # Get current candidate
        candidate = db.get_candidate(candidate_id)
        if not candidate:
            return jsonify({"success": False, "error": "Candidate not found"}), 404

        # Check for new syndrome-based review (JC-compliant)
        syndrome_decision = (data.get("syndrome_decision") or "").strip()
        agent_decision = (data.get("agent_decision") or "").strip() or None
        agent_notes = (data.get("agent_notes") or "").strip() or None

        if syndrome_decision:
            # New JC-compliant syndrome review workflow
            confirmed_syndrome = (data.get("confirmed_syndrome") or "").strip() or None
            confirmed_syndrome_display = (data.get("confirmed_syndrome_display") or "").strip() or None

            # Determine if syndrome was corrected
            is_override = (
                syndrome_decision == "correct_syndrome"
                or syndrome_decision == "no_indication"
                or syndrome_decision == "viral_illness"
            )

            # Map to legacy decision for backward compatibility
            legacy_decision = {
                "confirm_syndrome": "confirm_appropriate",
                "correct_syndrome": "override_to_appropriate",
                "no_indication": "confirm_inappropriate",
                "viral_illness": "confirm_inappropriate",
                "asymptomatic_bacteriuria": "confirm_inappropriate",
            }.get(syndrome_decision, syndrome_decision)

            review_id = db.save_review(
                candidate_id=candidate_id,
                reviewer=reviewer,
                decision=legacy_decision,
                is_override=is_override,
                override_reason=f"Syndrome: {syndrome_decision}" if is_override else None,
                llm_decision=candidate.clinical_syndrome,
                notes=notes,
                # v2 fields
                syndrome_decision=syndrome_decision,
                confirmed_syndrome=confirmed_syndrome or candidate.clinical_syndrome,
                confirmed_syndrome_display=confirmed_syndrome_display or candidate.clinical_syndrome_display,
                agent_decision=agent_decision,
                agent_notes=agent_notes,
            )

            # Log to training collector if available
            try:
                from abx_indications.training_collector import get_abx_training_collector
                collector = get_abx_training_collector()
                collector.log_human_review(
                    candidate_id=candidate_id,
                    reviewer=reviewer,
                    syndrome_decision=syndrome_decision,
                    confirmed_syndrome=confirmed_syndrome,
                    confirmed_syndrome_display=confirmed_syndrome_display,
                    agent_decision=agent_decision,
                    agent_notes=agent_notes,
                )
            except Exception as e:
                logger.debug(f"Training collector not available: {e}")

            return jsonify({
                "success": True,
                "review_id": review_id,
                "is_override": is_override,
                "syndrome_confirmed": confirmed_syndrome or candidate.clinical_syndrome,
                "agent_decision": agent_decision,
                "message": "Review submitted successfully",
            })

        # Legacy A/S/N/P review workflow (backward compatibility)
        decision = data.get("decision", "").strip()
        if not decision:
            return jsonify({"success": False, "error": "Decision required"}), 400

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
        override_reason = data.get("override_reason", "").strip() if is_override else None

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

        reviewer = get_user_from_request(default="system")
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

        reviewer = get_user_from_request(default="system")
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


@abx_indications_bp.route("/reviewed")
def reviewed_list():
    """Show reviewed candidates (for reference/audit)."""
    try:
        db = _get_indication_db()

        # Get reviewed candidates
        reviewed_candidates = db.list_candidates(status="reviewed", limit=100)

        # Get counts by classification for reviewed only
        counts = {}
        for c in reviewed_candidates:
            cls = c.final_classification or "U"
            counts[cls] = counts.get(cls, 0) + 1

        return render_template(
            "abx_indications_reviewed.html",
            candidates=reviewed_candidates,
            counts=counts,
            total_reviewed=len(reviewed_candidates),
        )

    except Exception as e:
        logger.error(f"Error loading reviewed candidates: {e}")
        return render_template(
            "abx_indications_reviewed.html",
            candidates=[],
            counts={},
            total_reviewed=0,
            error=str(e),
        )


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


@abx_indications_bp.route("/candidate/<candidate_id>/delete", methods=["POST"])
def delete_candidate(candidate_id: str):
    """Delete a single reviewed candidate.

    Only candidates that have been reviewed can be deleted.
    """
    try:
        db = _get_indication_db()
        data = request.get_json() or {}

        deleted_by = get_user_from_request(json_key="deleted_by")
        reason = data.get("reason", "").strip()

        if not deleted_by:
            return jsonify({"success": False, "error": "deleted_by is required"}), 400

        success = db.delete_candidate(
            candidate_id=candidate_id,
            deleted_by=deleted_by,
            reason=reason or None,
        )

        if success:
            return jsonify({
                "success": True,
                "message": f"Candidate {candidate_id} deleted successfully",
            })
        else:
            return jsonify({
                "success": False,
                "error": "Candidate not found or not reviewed (only reviewed candidates can be deleted)",
            }), 400

    except Exception as e:
        logger.error(f"Error deleting candidate {candidate_id}: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@abx_indications_bp.route("/reviewed/delete", methods=["POST"])
def delete_reviewed():
    """Delete all reviewed candidates.

    Optionally filter by age to only delete candidates reviewed more than
    N days ago.
    """
    try:
        db = _get_indication_db()
        data = request.get_json() or {}

        deleted_by = get_user_from_request(json_key="deleted_by")
        older_than_days = data.get("older_than_days")
        reason = data.get("reason", "").strip()

        if not deleted_by:
            return jsonify({"success": False, "error": "deleted_by is required"}), 400

        # Convert older_than_days to int if provided
        if older_than_days is not None:
            try:
                older_than_days = int(older_than_days)
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": "older_than_days must be an integer",
                }), 400

        count = db.delete_reviewed_candidates(
            deleted_by=deleted_by,
            older_than_days=older_than_days,
            reason=reason or None,
        )

        return jsonify({
            "success": True,
            "deleted_count": count,
            "message": f"Deleted {count} reviewed candidates",
        })

    except Exception as e:
        logger.error(f"Error deleting reviewed candidates: {e}")
        return jsonify({"success": False, "error": str(e)}), 500


@abx_indications_bp.route("/reviewed/count")
def reviewed_count():
    """Get count of reviewed candidates that can be deleted.

    Optionally filter by age with ?older_than_days=N query parameter.
    """
    try:
        db = _get_indication_db()

        older_than_days = request.args.get("older_than_days")
        if older_than_days is not None:
            try:
                older_than_days = int(older_than_days)
            except (ValueError, TypeError):
                return jsonify({
                    "success": False,
                    "error": "older_than_days must be an integer",
                }), 400

        count = db.get_reviewed_candidates_count(older_than_days=older_than_days)

        return jsonify({
            "success": True,
            "count": count,
            "older_than_days": older_than_days,
        })

    except Exception as e:
        logger.error(f"Error getting reviewed count: {e}")
        return jsonify({"success": False, "error": str(e)}), 500
