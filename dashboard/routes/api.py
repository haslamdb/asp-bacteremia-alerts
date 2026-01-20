"""API routes for Teams callbacks and programmatic access."""

from functools import wraps
from flask import Blueprint, jsonify, request, redirect, url_for, current_app

from common.alert_store import AlertStatus

api_bp = Blueprint("api", __name__)


def check_api_key(f):
    """Decorator to check API key for protected endpoints."""
    @wraps(f)
    def decorated(*args, **kwargs):
        api_key = current_app.config.get("DASHBOARD_API_KEY")

        # If no API key configured, allow all requests (dev mode)
        if not api_key:
            return f(*args, **kwargs)

        # Check key from query param or header
        provided_key = request.args.get("key") or request.headers.get("X-API-Key")

        if provided_key != api_key:
            return jsonify({"error": "Invalid or missing API key"}), 401

        return f(*args, **kwargs)

    return decorated


@api_bp.route("/ack/<alert_id>", methods=["GET", "POST"])
@check_api_key
def acknowledge_alert(alert_id):
    """Acknowledge an alert.

    GET: Used by Teams button callbacks (redirects to detail page)
    POST with form: Used by dashboard buttons (redirects)
    POST with JSON: Used by API clients (returns JSON)
    """
    store = current_app.alert_store

    # Get username from query param or header
    acknowledged_by = request.args.get("user") or request.headers.get("X-User", "Dashboard User")

    success = store.acknowledge(alert_id, acknowledged_by=acknowledged_by)

    # Check if this is a browser form submission (redirect) or API call (JSON)
    is_form_request = (
        request.method == "GET" or
        (request.content_type and "form" in request.content_type)
    )

    if is_form_request:
        # Browser request - redirect to detail page with flash message
        if success:
            return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="acknowledged"))
        return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="ack_failed"))

    # API response
    if success:
        alert = store.get_alert(alert_id)
        return jsonify({
            "success": True,
            "alert_id": alert_id,
            "status": alert.status.value if alert else "unknown",
        })

    return jsonify({
        "success": False,
        "error": "Failed to acknowledge alert",
    }), 400


@api_bp.route("/snooze/<alert_id>", methods=["GET", "POST"])
@check_api_key
def snooze_alert(alert_id):
    """Snooze an alert.

    GET: Used by Teams button callbacks (redirects to detail page)
    POST with form: Used by dashboard buttons (redirects)
    POST with JSON: Used by API clients (returns JSON)
    """
    store = current_app.alert_store

    # Get snooze duration from query, form, or JSON
    hours = request.args.get("hours", type=int)
    if hours is None and request.form:
        hours = request.form.get("hours", type=int)
    if hours is None and request.is_json:
        hours = request.json.get("hours", 4)
    if hours is None:
        hours = 4

    snoozed_by = request.args.get("user") or request.headers.get("X-User", "Dashboard User")

    success = store.snooze(alert_id, hours=hours, snoozed_by=snoozed_by)

    # Check if this is a browser form submission (redirect) or API call (JSON)
    is_form_request = (
        request.method == "GET" or
        (request.content_type and "form" in request.content_type)
    )

    if is_form_request:
        # Browser request - redirect to detail page
        if success:
            return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="snoozed"))
        return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="snooze_failed"))

    # API response
    if success:
        alert = store.get_alert(alert_id)
        return jsonify({
            "success": True,
            "alert_id": alert_id,
            "status": alert.status.value if alert else "unknown",
            "snoozed_until": alert.snoozed_until.isoformat() if alert and alert.snoozed_until else None,
        })

    return jsonify({
        "success": False,
        "error": "Failed to snooze alert",
    }), 400


@api_bp.route("/resolve/<alert_id>", methods=["GET", "POST"])
@check_api_key
def resolve_alert(alert_id):
    """Resolve/close an alert.

    GET: Used by Teams button callbacks (redirects to detail page)
    POST: Used by API clients or form submissions (returns JSON or redirects)
    """
    store = current_app.alert_store

    # Handle form data or JSON
    if request.content_type and "form" in request.content_type:
        data = request.form.to_dict()
    else:
        data = request.json or {}

    # Get parameters from query string (GET) or body (POST)
    resolved_by = (
        request.args.get("user") or
        data.get("resolved_by") or
        request.headers.get("X-User", "Dashboard User")
    )
    resolution_reason = request.args.get("reason") or data.get("resolution_reason")
    notes = request.args.get("notes") or data.get("notes")

    success = store.resolve(
        alert_id,
        resolved_by=resolved_by,
        resolution_reason=resolution_reason,
        notes=notes,
    )

    # Check if this is a form submission or API call
    wants_redirect = (
        request.method == "GET" or
        request.content_type and "form" in request.content_type
    )

    if wants_redirect:
        if success:
            return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="resolved"))
        return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="resolve_failed"))

    # API response
    if success:
        return jsonify({
            "success": True,
            "alert_id": alert_id,
            "status": "resolved",
            "resolution_reason": resolution_reason,
        })

    return jsonify({
        "success": False,
        "error": "Failed to resolve alert",
    }), 400


@api_bp.route("/alerts", methods=["GET"])
@check_api_key
def list_alerts():
    """List alerts with optional filters."""
    store = current_app.alert_store

    # Parse query parameters
    status_param = request.args.get("status")
    alert_type = request.args.get("type")
    patient_mrn = request.args.get("mrn")
    limit = request.args.get("limit", type=int, default=100)

    # Build filter kwargs
    filter_kwargs = {"limit": limit}

    if status_param:
        try:
            filter_kwargs["status"] = AlertStatus(status_param)
        except ValueError:
            pass

    if alert_type:
        from common.alert_store import AlertType
        try:
            filter_kwargs["alert_type"] = AlertType(alert_type)
        except ValueError:
            pass

    if patient_mrn:
        filter_kwargs["patient_mrn"] = patient_mrn

    alerts = store.list_alerts(**filter_kwargs)

    return jsonify({
        "alerts": [a.to_dict() for a in alerts],
        "count": len(alerts),
    })


@api_bp.route("/alerts/<alert_id>", methods=["GET"])
@check_api_key
def get_alert(alert_id):
    """Get a single alert by ID."""
    store = current_app.alert_store

    alert = store.get_alert(alert_id)
    if not alert:
        return jsonify({"error": "Alert not found"}), 404

    return jsonify(alert.to_dict())


@api_bp.route("/alerts/<alert_id>/status", methods=["POST"])
@check_api_key
def update_status(alert_id):
    """Update alert status."""
    store = current_app.alert_store

    data = request.json or {}
    new_status = data.get("status")
    user = data.get("user") or request.headers.get("X-User", "API User")

    if not new_status:
        return jsonify({"error": "status field required"}), 400

    try:
        status = AlertStatus(new_status)
    except ValueError:
        return jsonify({"error": f"Invalid status: {new_status}"}), 400

    # Route to appropriate method
    if status == AlertStatus.ACKNOWLEDGED:
        success = store.acknowledge(alert_id, acknowledged_by=user)
    elif status == AlertStatus.SNOOZED:
        hours = data.get("hours", 4)
        success = store.snooze(alert_id, hours=hours, snoozed_by=user)
    elif status == AlertStatus.RESOLVED:
        resolution_reason = data.get("resolution_reason")
        notes = data.get("notes")
        success = store.resolve(
            alert_id,
            resolved_by=user,
            resolution_reason=resolution_reason,
            notes=notes,
        )
    else:
        return jsonify({"error": f"Cannot transition to status: {new_status}"}), 400

    if success:
        alert = store.get_alert(alert_id)
        return jsonify({
            "success": True,
            "alert": alert.to_dict() if alert else None,
        })

    return jsonify({"success": False, "error": "Status update failed"}), 400


@api_bp.route("/alerts/<alert_id>/notes", methods=["POST"])
@check_api_key
def add_note(alert_id):
    """Add a note to an alert."""
    store = current_app.alert_store

    # Handle form or JSON data
    if request.form:
        note = request.form.get("note")
        user = request.form.get("user") or "Dashboard User"
    else:
        data = request.json or {}
        note = data.get("note")
        user = data.get("user") or request.headers.get("X-User", "API User")

    if not note:
        # For form submissions, redirect back with error
        if request.content_type and "form" in request.content_type:
            return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="note_empty"))
        return jsonify({"error": "note field required"}), 400

    success = store.add_note(alert_id, note=note, added_by=user)

    # Check if this is a form submission
    if request.content_type and "form" in request.content_type:
        if success:
            return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="note_added"))
        return redirect(url_for("asp_alerts.alert_detail", alert_id=alert_id, msg="note_failed"))

    if success:
        return jsonify({"success": True})

    return jsonify({"success": False, "error": "Failed to add note"}), 400


@api_bp.route("/stats", methods=["GET"])
@check_api_key
def get_stats():
    """Get alert statistics."""
    store = current_app.alert_store
    return jsonify(store.get_stats())
