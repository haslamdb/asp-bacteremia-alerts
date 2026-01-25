"""Drug-Bug Mismatch routes for the dashboard."""

from datetime import datetime, timedelta

from flask import Blueprint, render_template, current_app, request

from common.alert_store import AlertStatus, AlertType, ResolutionReason

drug_bug_bp = Blueprint("drug_bug", __name__, url_prefix="/drug-bug-mismatch")


@drug_bug_bp.route("/")
def dashboard():
    """Drug-Bug Mismatch dashboard with active alerts and statistics."""
    store = current_app.alert_store

    # Get filter parameters
    severity = request.args.get("severity")
    mismatch_type = request.args.get("mismatch_type")

    # Build filter kwargs for active alerts
    filter_kwargs = {
        "alert_type": AlertType.DRUG_BUG_MISMATCH,
        "status": [
            AlertStatus.PENDING,
            AlertStatus.SENT,
            AlertStatus.ACKNOWLEDGED,
            AlertStatus.SNOOZED,
        ],
    }

    if severity:
        filter_kwargs["severity"] = severity

    # Get active drug-bug mismatch alerts
    active_alerts = store.list_alerts(**filter_kwargs)

    # Filter by mismatch_type if specified
    if mismatch_type:
        active_alerts = [
            a for a in active_alerts
            if a.content and a.content.get("mismatch_type") == mismatch_type
        ]

    # Sort by severity (critical first) then by created_at (newest first)
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    active_alerts.sort(key=lambda a: (
        severity_order.get(a.severity, 99),
        -(a.created_at.timestamp() if a.created_at else 0),
    ))

    # Get resolved alerts for today
    today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
    resolved_alerts = store.list_alerts(
        alert_type=AlertType.DRUG_BUG_MISMATCH,
        status=AlertStatus.RESOLVED,
    )
    resolved_today = [
        a for a in resolved_alerts
        if a.resolved_at and a.resolved_at >= today_start
    ]

    # Calculate statistics
    stats = {
        "active_count": len(active_alerts),
        "critical_count": sum(1 for a in active_alerts if a.severity == "critical"),
        "warning_count": sum(1 for a in active_alerts if a.severity == "warning"),
        "resolved_today": len(resolved_today),
    }

    # Count by mismatch type
    mismatch_counts = {"resistant": 0, "intermediate": 0, "no_coverage": 0}
    for alert in active_alerts:
        if alert.content:
            mt = alert.content.get("mismatch_type")
            if mt in mismatch_counts:
                mismatch_counts[mt] += 1

    return render_template(
        "drug_bug_dashboard.html",
        alerts=active_alerts,
        stats=stats,
        mismatch_counts=mismatch_counts,
        current_severity=severity,
        current_mismatch_type=mismatch_type,
    )


@drug_bug_bp.route("/history")
def history():
    """Show resolved drug-bug mismatch alerts."""
    store = current_app.alert_store

    # Get filter parameters
    severity = request.args.get("severity")
    resolution = request.args.get("resolution")

    # Build filter kwargs
    filter_kwargs = {
        "alert_type": AlertType.DRUG_BUG_MISMATCH,
        "status": AlertStatus.RESOLVED,
    }

    if severity:
        filter_kwargs["severity"] = severity

    if resolution:
        filter_kwargs["resolution_reason"] = resolution

    alerts = store.list_alerts(**filter_kwargs)

    # Sort by resolved_at (newest first)
    alerts.sort(key=lambda a: -(a.resolved_at.timestamp() if a.resolved_at else 0))

    # Get resolution reason options for dropdown
    resolution_reasons = ResolutionReason.all_options()

    return render_template(
        "drug_bug_history.html",
        alerts=alerts,
        resolution_reasons=resolution_reasons,
        ResolutionReason=ResolutionReason,
        current_severity=severity,
        current_resolution=resolution,
    )


@drug_bug_bp.route("/help")
def help_page():
    """Drug-Bug Mismatch help page."""
    return render_template("drug_bug_help.html")
