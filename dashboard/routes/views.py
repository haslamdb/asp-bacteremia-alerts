"""ASP Alerts routes for blood culture and antimicrobial therapy alerts."""

from flask import Blueprint, render_template, redirect, url_for, current_app, request

from common.alert_store import AlertStatus, AlertType, ResolutionReason
from ..services.fhir import FHIRService

asp_alerts_bp = Blueprint("asp_alerts", __name__, url_prefix="/asp-alerts")


@asp_alerts_bp.route("/")
def index():
    """Redirect to active alerts."""
    return redirect(url_for("asp_alerts.alerts_active"))


@asp_alerts_bp.route("/active")
def alerts_active():
    """List active (non-resolved) alerts."""
    store = current_app.alert_store

    # Get filter parameters
    alert_type = request.args.get("type")
    patient_mrn = request.args.get("mrn")
    severity = request.args.get("severity")

    # Build filter kwargs
    filter_kwargs = {
        "status": [
            AlertStatus.PENDING,
            AlertStatus.SENT,
            AlertStatus.ACKNOWLEDGED,
            AlertStatus.SNOOZED,
        ]
    }

    if alert_type:
        try:
            filter_kwargs["alert_type"] = AlertType(alert_type)
        except ValueError:
            pass

    if patient_mrn:
        filter_kwargs["patient_mrn"] = patient_mrn

    if severity:
        filter_kwargs["severity"] = severity

    alerts = store.list_alerts(**filter_kwargs)

    # Sort alerts: bacteremia first, then by severity (critical > warning > info), then by date
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    type_order = {AlertType.BACTEREMIA: 0, AlertType.BROAD_SPECTRUM_USAGE: 1, AlertType.CUSTOM: 2}
    alerts.sort(key=lambda a: (
        type_order.get(a.alert_type, 99),
        severity_order.get(a.severity, 99),
    ))

    # Get stats for active alerts only
    active_statuses = [
        AlertStatus.PENDING,
        AlertStatus.SENT,
        AlertStatus.ACKNOWLEDGED,
        AlertStatus.SNOOZED,
    ]
    stats = store.get_stats(status=active_statuses)

    return render_template(
        "alerts_active.html",
        alerts=alerts,
        stats=stats,
        current_type=alert_type,
        current_mrn=patient_mrn,
        current_severity=severity,
    )


@asp_alerts_bp.route("/history")
def alerts_history():
    """List resolved alerts."""
    store = current_app.alert_store

    # Get filter parameters
    alert_type = request.args.get("type")
    patient_mrn = request.args.get("mrn")
    severity = request.args.get("severity")
    resolution = request.args.get("resolution")

    # Build filter kwargs
    filter_kwargs = {"status": AlertStatus.RESOLVED}

    if alert_type:
        try:
            filter_kwargs["alert_type"] = AlertType(alert_type)
        except ValueError:
            pass

    if patient_mrn:
        filter_kwargs["patient_mrn"] = patient_mrn

    if severity:
        filter_kwargs["severity"] = severity

    if resolution:
        filter_kwargs["resolution_reason"] = resolution

    alerts = store.list_alerts(**filter_kwargs)
    # Get stats for resolved alerts only
    stats = store.get_stats(status=AlertStatus.RESOLVED)

    # Get resolution reason options for dropdown
    resolution_reasons = ResolutionReason.all_options()

    return render_template(
        "alerts_history.html",
        alerts=alerts,
        stats=stats,
        ResolutionReason=ResolutionReason,
        resolution_reasons=resolution_reasons,
        current_type=alert_type,
        current_mrn=patient_mrn,
        current_severity=severity,
        current_resolution=resolution,
    )


@asp_alerts_bp.route("/alerts/<alert_id>")
def alert_detail(alert_id):
    """Show single alert details."""
    store = current_app.alert_store

    alert = store.get_alert(alert_id)
    if not alert:
        return render_template("alert_not_found.html", alert_id=alert_id), 404

    audit_log = store.get_audit_log(alert_id)

    # Get resolution reason options for dropdown
    resolution_reasons = ResolutionReason.all_options()

    return render_template(
        "alert_detail.html",
        alert=alert,
        audit_log=audit_log,
        resolution_reasons=resolution_reasons,
        ResolutionReason=ResolutionReason,
    )


@asp_alerts_bp.route("/reports")
def reports():
    """Show analytics and reports."""
    store = current_app.alert_store

    # Get filter parameters
    alert_type = request.args.get("type")
    days = request.args.get("days", 30, type=int)

    # Validate days
    if days < 1:
        days = 1
    elif days > 365:
        days = 365

    # Parse alert type
    parsed_type = None
    if alert_type:
        try:
            parsed_type = AlertType(alert_type)
        except ValueError:
            pass

    # Get analytics data
    analytics = store.get_analytics(alert_type=parsed_type, days=days)

    # Get alert type options for dropdown
    alert_types = [
        ("", "All Types"),
        ("bacteremia", "Bacteremia"),
        ("broad_spectrum_usage", "Broad Spectrum Usage"),
    ]

    return render_template(
        "reports.html",
        analytics=analytics,
        alert_types=alert_types,
        current_type=alert_type,
        current_days=days,
        ResolutionReason=ResolutionReason,
    )


@asp_alerts_bp.route("/help")
def help_page():
    """Show help/demo workflow documentation."""
    return render_template("help.html")


@asp_alerts_bp.route("/culture/<culture_id>")
def culture_detail(culture_id):
    """Show culture result with susceptibilities."""
    fhir_url = current_app.config.get("FHIR_BASE_URL", "http://localhost:8081/fhir")
    fhir = FHIRService(fhir_url)

    culture = fhir.get_culture_with_susceptibilities(culture_id)
    if not culture:
        return render_template("culture_not_found.html", culture_id=culture_id), 404

    return render_template("culture_detail.html", culture=culture)


@asp_alerts_bp.route("/patient/<patient_id>/medications")
def patient_medications(patient_id):
    """Show current antibiotic medications for a patient."""
    fhir_url = current_app.config.get("FHIR_BASE_URL", "http://localhost:8081/fhir")
    fhir = FHIRService(fhir_url)

    # Get patient info
    patient = fhir._get(f"Patient/{patient_id}")
    if not patient:
        return render_template("patient_not_found.html", patient_id=patient_id), 404

    # Extract patient name and MRN
    patient_name = "Unknown"
    patient_mrn = "Unknown"
    names = patient.get("name", [])
    if names:
        name = names[0]
        given = " ".join(name.get("given", []))
        family = name.get("family", "")
        patient_name = f"{given} {family}".strip() or "Unknown"

    for ident in patient.get("identifier", []):
        type_coding = ident.get("type", {}).get("coding", [])
        for coding in type_coding:
            if coding.get("code") == "MR":
                patient_mrn = ident.get("value", "Unknown")
                break

    # Get medications
    medications = fhir.get_patient_medications(patient_id, antibiotics_only=True)

    return render_template(
        "medications_detail.html",
        patient_id=patient_id,
        patient_name=patient_name,
        patient_mrn=patient_mrn,
        medications=medications,
    )
