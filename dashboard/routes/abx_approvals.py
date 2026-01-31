"""Antibiotic Approvals routes for the dashboard.

Handles phone-based antibiotic approval requests from prescribers.
"""

import json
import logging
from datetime import datetime

from flask import Blueprint, render_template, current_app, request, jsonify, redirect, url_for

from common.abx_approvals import AbxApprovalStore, ApprovalDecision, ApprovalStatus
from common.allergy_recommendations import filter_recommendations_by_allergies
from dashboard.services.fhir import FHIRService
from dashboard.services.user import get_user_from_request

logger = logging.getLogger(__name__)

abx_approvals_bp = Blueprint("abx_approvals", __name__, url_prefix="/abx-approvals")


def _get_approval_store() -> AbxApprovalStore:
    """Get the approval store, initializing if needed."""
    if not hasattr(current_app, "abx_approval_store"):
        current_app.abx_approval_store = AbxApprovalStore(
            db_path=current_app.config.get("ABX_APPROVALS_DB_PATH")
        )
    return current_app.abx_approval_store


def _get_fhir_service() -> FHIRService | None:
    """Get the FHIR service from config."""
    fhir_url = current_app.config.get("FHIR_BASE_URL")
    if fhir_url:
        return FHIRService(fhir_url)
    return None


@abx_approvals_bp.route("/")
def index():
    """Redirect to dashboard."""
    return redirect(url_for("abx_approvals.dashboard"))


@abx_approvals_bp.route("/dashboard")
def dashboard():
    """Main dashboard with pending requests and statistics."""
    store = _get_approval_store()

    # Get pending requests
    pending = store.list_pending()

    # Get stats
    stats = store.get_stats(days=30)

    # Get recent completed (today)
    today_completed = [
        r for r in store.list_requests(status=ApprovalStatus.COMPLETED, days_back=1)
    ]

    return render_template(
        "abx_approvals/dashboard.html",
        pending_requests=pending,
        stats=stats,
        today_completed=today_completed,
        ApprovalDecision=ApprovalDecision,
    )


@abx_approvals_bp.route("/new")
def new_request():
    """Patient search form for new approval request."""
    return render_template("abx_approvals/patient_search.html")


@abx_approvals_bp.route("/search")
def search_patients():
    """Search for patients by MRN or name."""
    mrn = request.args.get("mrn", "").strip()
    name = request.args.get("name", "").strip()

    if not mrn and not name:
        return render_template(
            "abx_approvals/patient_search.html",
            error="Please enter an MRN or patient name to search."
        )

    fhir = _get_fhir_service()
    patients = []
    error = None

    if fhir:
        try:
            patients = fhir.search_patients(mrn=mrn if mrn else None, name=name if name else None)
        except Exception as e:
            logger.error(f"Patient search failed: {e}")
            error = f"Search failed: {e}"
    else:
        error = "FHIR server not configured"

    return render_template(
        "abx_approvals/patient_search.html",
        patients=patients,
        search_mrn=mrn,
        search_name=name,
        error=error,
    )


@abx_approvals_bp.route("/patient/<patient_id>")
def patient_detail(patient_id: str):
    """Patient detail page with clinical data and approval form."""
    fhir = _get_fhir_service()
    store = _get_approval_store()

    if not fhir:
        return render_template(
            "abx_approvals/approval_form.html",
            error="FHIR server not configured",
        )

    # Get patient info
    patient = fhir.get_patient(patient_id)
    if not patient:
        return render_template(
            "abx_approvals/approval_form.html",
            error=f"Patient {patient_id} not found",
        ), 404

    # Get clinical context (MDR history, allergies, renal status)
    clinical_context = None
    try:
        clinical_context = fhir.get_clinical_context(patient_id)
    except Exception as e:
        logger.error(f"Failed to get clinical context: {e}")

    # Get current antibiotics
    try:
        medications = fhir.get_patient_medications(patient_id, antibiotics_only=True)
    except Exception as e:
        logger.error(f"Failed to get medications: {e}")
        medications = []

    # Get recent cultures
    try:
        cultures = fhir.get_patient_cultures(patient_id, days_back=30)
    except Exception as e:
        logger.error(f"Failed to get cultures: {e}")
        cultures = []

    # Get recent approvals for this patient
    recent_approvals = store.list_requests(patient_mrn=patient.mrn, days_back=30)

    # Compute allergy-safe susceptibilities for each culture
    allergy_info = None
    if clinical_context and clinical_context.allergies:
        allergy_dicts = [
            {"substance": a.substance, "severity": a.severity}
            for a in clinical_context.allergies
        ]
        # For each culture, determine which susceptible options are safe
        for culture in cultures:
            susceptible_names = [s.antibiotic for s in culture.susceptibilities if s.result == "S"]
            if susceptible_names:
                filtered = filter_recommendations_by_allergies(susceptible_names, allergy_dicts)
                # Attach allergy info to culture (as a temporary attribute)
                culture._allergy_safe = filtered.safe_recommendations
                culture._allergy_excluded = [c.antibiotic for c in filtered.excluded_antibiotics]
                culture._has_allergy_conflicts = filtered.has_conflicts
        allergy_info = allergy_dicts

    # Common antibiotics for autocomplete
    common_antibiotics = [
        "Meropenem", "Piperacillin-Tazobactam", "Cefepime", "Vancomycin",
        "Ceftriaxone", "Ampicillin-Sulbactam", "Levofloxacin", "Ciprofloxacin",
        "Metronidazole", "Clindamycin", "Azithromycin", "Doxycycline",
        "Linezolid", "Daptomycin", "Ceftazidime-Avibactam", "Aztreonam",
        "Cefazolin", "Gentamicin", "Tobramycin", "Amikacin",
        "Fluconazole", "Micafungin", "Voriconazole", "Amphotericin B",
    ]

    return render_template(
        "abx_approvals/approval_form.html",
        patient=patient,
        clinical_context=clinical_context,
        medications=medications,
        cultures=cultures,
        recent_approvals=recent_approvals,
        common_antibiotics=common_antibiotics,
        ApprovalDecision=ApprovalDecision,
    )


@abx_approvals_bp.route("/approval/<approval_id>")
def approval_detail(approval_id: str):
    """View existing approval detail."""
    store = _get_approval_store()

    approval = store.get_request(approval_id)
    if not approval:
        return render_template(
            "abx_approvals/approval_detail.html",
            error=f"Approval {approval_id} not found",
        ), 404

    # Get audit log
    audit_log = store.get_audit_log(approval_id)

    return render_template(
        "abx_approvals/approval_detail.html",
        approval=approval,
        audit_log=audit_log,
        ApprovalDecision=ApprovalDecision,
    )


@abx_approvals_bp.route("/history")
def history():
    """List of past approvals with filters."""
    store = _get_approval_store()

    # Get filter parameters
    decision_filter = request.args.get("decision")
    antibiotic_filter = request.args.get("antibiotic", "").strip()
    mrn_filter = request.args.get("mrn", "").strip()
    days = int(request.args.get("days", "30"))

    # Build filter kwargs
    filter_kwargs = {
        "status": ApprovalStatus.COMPLETED,
        "days_back": days,
    }

    if decision_filter:
        filter_kwargs["decision"] = decision_filter
    if antibiotic_filter:
        filter_kwargs["antibiotic_name"] = antibiotic_filter
    if mrn_filter:
        filter_kwargs["patient_mrn"] = mrn_filter

    approvals = store.list_requests(**filter_kwargs)

    return render_template(
        "abx_approvals/history.html",
        approvals=approvals,
        decision_options=ApprovalDecision.all_options(),
        current_decision=decision_filter,
        current_antibiotic=antibiotic_filter,
        current_mrn=mrn_filter,
        current_days=days,
        ApprovalDecision=ApprovalDecision,
    )


@abx_approvals_bp.route("/reports")
def reports():
    """Analytics and reports page."""
    store = _get_approval_store()

    days = int(request.args.get("days", "30"))
    analytics = store.get_analytics(days=days)

    return render_template(
        "abx_approvals/reports.html",
        analytics=analytics,
        current_days=days,
        ApprovalDecision=ApprovalDecision,
    )


@abx_approvals_bp.route("/help")
def help_page():
    """Help documentation page."""
    return render_template("abx_approvals/help.html")


# API Endpoints

@abx_approvals_bp.route("/api/create", methods=["POST"])
def api_create_request():
    """Create a new approval request via API."""
    store = _get_approval_store()
    fhir = _get_fhir_service()

    data = request.get_json() or {}

    # Required fields
    patient_id = data.get("patient_id")
    antibiotic_name = data.get("antibiotic_name", "").strip()

    if not patient_id or not antibiotic_name:
        return jsonify({
            "success": False,
            "error": "patient_id and antibiotic_name are required"
        }), 400

    # Get patient info from FHIR
    patient_mrn = data.get("patient_mrn", "Unknown")
    patient_name = data.get("patient_name")
    patient_location = data.get("patient_location")

    if fhir and not patient_name:
        patient = fhir.get_patient(patient_id)
        if patient:
            patient_mrn = patient.mrn
            patient_name = patient.name
            patient_location = patient.location_display

    # Build clinical context
    clinical_context = {}
    if data.get("current_medications"):
        clinical_context["current_medications"] = data["current_medications"]
    if data.get("recent_cultures"):
        clinical_context["recent_cultures"] = data["recent_cultures"]

    created_by = get_user_from_request(default="Unknown")

    try:
        approval = store.create_request(
            patient_id=patient_id,
            patient_mrn=patient_mrn,
            patient_name=patient_name,
            patient_location=patient_location,
            antibiotic_name=antibiotic_name,
            antibiotic_dose=data.get("antibiotic_dose"),
            antibiotic_route=data.get("antibiotic_route"),
            indication=data.get("indication"),
            duration_requested_hours=data.get("duration_requested_hours"),
            prescriber_name=data.get("prescriber_name"),
            prescriber_pager=data.get("prescriber_pager"),
            clinical_context=clinical_context,
            created_by=created_by,
        )

        return jsonify({
            "success": True,
            "approval_id": approval.id,
        })

    except Exception as e:
        logger.error(f"Failed to create approval request: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@abx_approvals_bp.route("/api/<approval_id>/decide", methods=["POST"])
def api_decide(approval_id: str):
    """Record a decision on an approval request."""
    store = _get_approval_store()

    data = request.get_json() or {}

    decision = data.get("decision")
    if not decision:
        return jsonify({
            "success": False,
            "error": "decision is required"
        }), 400

    # Validate decision
    try:
        ApprovalDecision(decision)
    except ValueError:
        return jsonify({
            "success": False,
            "error": f"Invalid decision: {decision}"
        }), 400

    decision_by = get_user_from_request(default="Unknown")

    try:
        success = store.decide(
            approval_id=approval_id,
            decision=decision,
            decision_by=decision_by,
            decision_notes=data.get("decision_notes"),
            alternative_recommended=data.get("alternative_recommended"),
        )

        if success:
            return jsonify({"success": True})
        else:
            return jsonify({
                "success": False,
                "error": "Decision could not be recorded (request may already be completed)"
            }), 400

    except Exception as e:
        logger.error(f"Failed to record decision: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@abx_approvals_bp.route("/api/<approval_id>/note", methods=["POST"])
def api_add_note(approval_id: str):
    """Add a note to an approval request."""
    store = _get_approval_store()

    data = request.get_json() or {}
    note = data.get("note", "").strip()

    if not note:
        return jsonify({
            "success": False,
            "error": "note is required"
        }), 400

    added_by = get_user_from_request(default="Unknown")

    try:
        success = store.add_note(
            approval_id=approval_id,
            note=note,
            added_by=added_by,
        )

        if success:
            return jsonify({"success": True})
        else:
            return jsonify({
                "success": False,
                "error": "Note could not be added"
            }), 400

    except Exception as e:
        logger.error(f"Failed to add note: {e}")
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500
