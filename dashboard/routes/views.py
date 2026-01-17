"""HTML view routes for the dashboard."""

from flask import Blueprint, render_template, redirect, url_for, current_app, request

from common.alert_store import AlertStatus, ResolutionReason

views_bp = Blueprint("views", __name__)


@views_bp.route("/")
def index():
    """Redirect to active alerts."""
    return redirect(url_for("views.alerts_active"))


@views_bp.route("/alerts/active")
def alerts_active():
    """List active (non-resolved) alerts."""
    store = current_app.alert_store

    # Get filter parameters
    alert_type = request.args.get("type")
    patient_mrn = request.args.get("mrn")

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
        from common.alert_store import AlertType
        try:
            filter_kwargs["alert_type"] = AlertType(alert_type)
        except ValueError:
            pass

    if patient_mrn:
        filter_kwargs["patient_mrn"] = patient_mrn

    alerts = store.list_alerts(**filter_kwargs)
    stats = store.get_stats()

    return render_template(
        "alerts_active.html",
        alerts=alerts,
        stats=stats,
        current_type=alert_type,
        current_mrn=patient_mrn,
    )


@views_bp.route("/alerts/history")
def alerts_history():
    """List resolved alerts."""
    store = current_app.alert_store

    alerts = store.list_alerts(status=AlertStatus.RESOLVED)
    stats = store.get_stats()

    return render_template(
        "alerts_history.html",
        alerts=alerts,
        stats=stats,
        ResolutionReason=ResolutionReason,
    )


@views_bp.route("/alerts/<alert_id>")
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
