"""SQLite-backed alert storage for persistent alert tracking."""

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .models import (
    AlertType,
    AlertStatus,
    AuditAction,
    ResolutionReason,
    StoredAlert,
    AlertAuditEntry,
)

logger = logging.getLogger(__name__)


def _log_asp_activity(
    activity_type: str,
    entity_id: str,
    entity_type: str,
    action_taken: str,
    provider_id: str | None = None,
    provider_name: str | None = None,
    patient_mrn: str | None = None,
    location_code: str | None = None,
    service: str | None = None,
    outcome: str | None = None,
    details: dict | None = None,
) -> None:
    """Log activity to the unified metrics store.

    This is a fire-and-forget operation - failures are logged but don't
    interrupt the main operation.
    """
    try:
        from common.metrics_store import MetricsStore, ActivityType, ModuleSource

        store = MetricsStore()
        store.log_activity(
            activity_type=activity_type,
            module=ModuleSource.ASP_ALERTS,
            provider_id=provider_id,
            provider_name=provider_name,
            entity_id=entity_id,
            entity_type=entity_type,
            action_taken=action_taken,
            outcome=outcome,
            patient_mrn=patient_mrn,
            location_code=location_code,
            service=service,
            details=details,
        )
    except Exception as e:
        logger.debug(f"Failed to log activity to metrics store: {e}")


class AlertStore:
    """SQLite-backed storage for managing alert lifecycle."""

    def __init__(self, db_path: str | None = None):
        """Initialize alert store.

        Args:
            db_path: Path to SQLite database. Defaults to ALERT_DB_PATH env var
                     or ~/.aegis/alerts.db
        """
        if db_path:
            self.db_path = os.path.expanduser(db_path)
        else:
            self.db_path = os.path.expanduser(
                os.environ.get("ALERT_DB_PATH", "~/.aegis/alerts.db")
            )

        # Ensure directory exists
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)

        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        schema_path = Path(__file__).parent / "schema.sql"
        with open(schema_path) as f:
            schema = f.read()

        with self._connect() as conn:
            conn.executescript(schema)

    def _connect(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _generate_id(self) -> str:
        """Generate a unique alert ID."""
        return str(uuid.uuid4())[:8]

    # Core alert operations

    def save_alert(
        self,
        alert_type: AlertType,
        source_id: str,
        severity: str = "warning",
        patient_id: str | None = None,
        patient_mrn: str | None = None,
        patient_name: str | None = None,
        title: str = "",
        summary: str = "",
        content: dict | None = None,
    ) -> StoredAlert:
        """Save a new alert to the store.

        Args:
            alert_type: Type of alert (bacteremia, broad_spectrum_usage, etc.)
            source_id: Unique identifier from source system (FHIR ID, etc.)
            severity: Alert severity level
            patient_id: FHIR patient ID
            patient_mrn: Patient MRN
            patient_name: Patient name
            title: Alert title for display
            summary: Brief summary text
            content: Additional content as dict (stored as JSON)

        Returns:
            The created StoredAlert

        Raises:
            sqlite3.IntegrityError: If alert for this type/source already exists
        """
        alert_id = self._generate_id()
        now = datetime.now()
        content_json = json.dumps(content) if content else None

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO alerts (
                    id, alert_type, source_id, status, severity,
                    patient_id, patient_mrn, patient_name,
                    title, summary, content, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    alert_id, alert_type.value, source_id, AlertStatus.PENDING.value,
                    severity, patient_id, patient_mrn, patient_name,
                    title, summary, content_json, now.isoformat()
                )
            )

            # Audit log
            conn.execute(
                """
                INSERT INTO alert_audit (alert_id, action, performed_at, details)
                VALUES (?, ?, ?, ?)
                """,
                (alert_id, AuditAction.CREATED.value, now.isoformat(), None)
            )

            conn.commit()

        logger.info(f"Created alert {alert_id} for {alert_type.value}/{source_id}")

        return StoredAlert(
            id=alert_id,
            alert_type=alert_type,
            source_id=source_id,
            status=AlertStatus.PENDING,
            severity=severity,
            patient_id=patient_id,
            patient_mrn=patient_mrn,
            patient_name=patient_name,
            title=title,
            summary=summary,
            content=content or {},
            created_at=now,
        )

    def check_if_alerted(
        self,
        alert_type: AlertType,
        source_id: str,
        include_resolved: bool = False,
    ) -> bool:
        """Check if an alert already exists for this source.

        Use this before sending to prevent duplicates.

        Args:
            alert_type: Type of alert
            source_id: Source identifier to check
            include_resolved: If True, return True even for resolved alerts

        Returns:
            True if alert exists (and is active or include_resolved=True)
        """
        with self._connect() as conn:
            if include_resolved:
                cursor = conn.execute(
                    "SELECT id FROM alerts WHERE alert_type = ? AND source_id = ?",
                    (alert_type.value, source_id)
                )
            else:
                # Exclude resolved, but include snoozed (they may un-snooze)
                cursor = conn.execute(
                    """
                    SELECT id FROM alerts
                    WHERE alert_type = ? AND source_id = ?
                    AND status != ?
                    """,
                    (alert_type.value, source_id, AlertStatus.RESOLVED.value)
                )

            return cursor.fetchone() is not None

    def get_alert(self, alert_id: str) -> StoredAlert | None:
        """Get an alert by ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, alert_type, source_id, status, severity,
                       patient_id, patient_mrn, patient_name,
                       title, summary, content,
                       created_at, sent_at, acknowledged_at, acknowledged_by,
                       resolved_at, resolved_by, resolution_reason, snoozed_until, notes
                FROM alerts WHERE id = ?
                """,
                (alert_id,)
            )
            row = cursor.fetchone()

            if row:
                return StoredAlert.from_row(tuple(row))
            return None

    def get_alert_by_source(
        self,
        alert_type: AlertType,
        source_id: str,
    ) -> StoredAlert | None:
        """Get an alert by type and source ID."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, alert_type, source_id, status, severity,
                       patient_id, patient_mrn, patient_name,
                       title, summary, content,
                       created_at, sent_at, acknowledged_at, acknowledged_by,
                       resolved_at, resolved_by, resolution_reason, snoozed_until, notes
                FROM alerts WHERE alert_type = ? AND source_id = ?
                """,
                (alert_type.value, source_id)
            )
            row = cursor.fetchone()

            if row:
                return StoredAlert.from_row(tuple(row))
            return None

    # Status updates

    def mark_sent(self, alert_id: str) -> bool:
        """Mark alert as sent."""
        return self._update_status(
            alert_id,
            AlertStatus.SENT,
            AuditAction.SENT,
            sent_at=datetime.now()
        )

    def acknowledge(
        self,
        alert_id: str,
        acknowledged_by: str | None = None,
    ) -> bool:
        """Acknowledge an alert."""
        now = datetime.now()

        # Get alert info for activity logging
        alert = self.get_alert(alert_id)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE alerts
                SET status = ?, acknowledged_at = ?, acknowledged_by = ?
                WHERE id = ? AND status NOT IN (?)
                """,
                (
                    AlertStatus.ACKNOWLEDGED.value,
                    now.isoformat(),
                    acknowledged_by,
                    alert_id,
                    AlertStatus.RESOLVED.value,
                )
            )

            if cursor.rowcount > 0:
                conn.execute(
                    """
                    INSERT INTO alert_audit (alert_id, action, performed_by, performed_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (alert_id, AuditAction.ACKNOWLEDGED.value, acknowledged_by, now.isoformat())
                )
                conn.commit()
                logger.info(f"Alert {alert_id} acknowledged by {acknowledged_by}")

                # Log to unified metrics store
                _log_asp_activity(
                    activity_type="acknowledgment",
                    entity_id=alert_id,
                    entity_type="alert",
                    action_taken="acknowledged",
                    provider_name=acknowledged_by,
                    patient_mrn=alert.patient_mrn if alert else None,
                    details={
                        "alert_type": alert.alert_type.value if alert else None,
                        "severity": alert.severity if alert else None,
                    },
                )

                return True

            return False

    def snooze(
        self,
        alert_id: str,
        hours: int = 4,
        snoozed_by: str | None = None,
    ) -> bool:
        """Snooze an alert for specified hours."""
        now = datetime.now()
        snoozed_until = now + timedelta(hours=hours)

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE alerts
                SET status = ?, snoozed_until = ?
                WHERE id = ? AND status NOT IN (?)
                """,
                (
                    AlertStatus.SNOOZED.value,
                    snoozed_until.isoformat(),
                    alert_id,
                    AlertStatus.RESOLVED.value,
                )
            )

            if cursor.rowcount > 0:
                conn.execute(
                    """
                    INSERT INTO alert_audit (alert_id, action, performed_by, performed_at, details)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        alert_id,
                        AuditAction.SNOOZED.value,
                        snoozed_by,
                        now.isoformat(),
                        f"Snoozed for {hours} hours until {snoozed_until.isoformat()}"
                    )
                )
                conn.commit()
                logger.info(f"Alert {alert_id} snoozed for {hours}h by {snoozed_by}")
                return True

            return False

    def resolve(
        self,
        alert_id: str,
        resolved_by: str | None = None,
        resolution_reason: ResolutionReason | str | None = None,
        notes: str | None = None,
    ) -> bool:
        """Resolve/close an alert.

        Args:
            alert_id: The alert ID to resolve
            resolved_by: Who resolved the alert
            resolution_reason: How the alert was handled (ResolutionReason enum or string value)
            notes: Additional notes about the resolution

        Returns:
            True if resolved successfully
        """
        now = datetime.now()

        # Get alert info for activity logging
        alert = self.get_alert(alert_id)

        # Convert string to enum if needed
        reason_value = None
        if resolution_reason:
            if isinstance(resolution_reason, ResolutionReason):
                reason_value = resolution_reason.value
            else:
                reason_value = resolution_reason

        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE alerts
                SET status = ?, resolved_at = ?, resolved_by = ?,
                    resolution_reason = ?, notes = COALESCE(?, notes)
                WHERE id = ?
                """,
                (
                    AlertStatus.RESOLVED.value,
                    now.isoformat(),
                    resolved_by,
                    reason_value,
                    notes,
                    alert_id,
                )
            )

            if cursor.rowcount > 0:
                # Build audit details
                details_parts = []
                if reason_value:
                    try:
                        reason_display = ResolutionReason.display_name(ResolutionReason(reason_value))
                    except ValueError:
                        reason_display = reason_value
                    details_parts.append(f"Reason: {reason_display}")
                if notes:
                    details_parts.append(f"Notes: {notes[:100]}")
                details = "; ".join(details_parts) if details_parts else None

                conn.execute(
                    """
                    INSERT INTO alert_audit (alert_id, action, performed_by, performed_at, details)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (alert_id, AuditAction.RESOLVED.value, resolved_by, now.isoformat(), details)
                )
                conn.commit()
                logger.info(f"Alert {alert_id} resolved by {resolved_by} (reason: {reason_value})")

                # Log to unified metrics store
                _log_asp_activity(
                    activity_type="resolution",
                    entity_id=alert_id,
                    entity_type="alert",
                    action_taken=reason_value or "resolved",
                    provider_name=resolved_by,
                    patient_mrn=alert.patient_mrn if alert else None,
                    outcome=reason_value,
                    details={
                        "alert_type": alert.alert_type.value if alert else None,
                        "severity": alert.severity if alert else None,
                        "resolution_reason": reason_value,
                        "notes": notes[:200] if notes else None,
                    },
                )

                return True

            return False

    def add_note(
        self,
        alert_id: str,
        note: str,
        added_by: str | None = None,
    ) -> bool:
        """Add a note to an alert."""
        now = datetime.now()

        with self._connect() as conn:
            # Append to existing notes
            cursor = conn.execute(
                """
                UPDATE alerts
                SET notes = CASE
                    WHEN notes IS NULL OR notes = '' THEN ?
                    ELSE notes || char(10) || char(10) || ?
                END
                WHERE id = ?
                """,
                (note, note, alert_id)
            )

            if cursor.rowcount > 0:
                conn.execute(
                    """
                    INSERT INTO alert_audit (alert_id, action, performed_by, performed_at, details)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (alert_id, AuditAction.NOTE_ADDED.value, added_by, now.isoformat(), note[:200])
                )
                conn.commit()
                return True

            return False

    def _update_status(
        self,
        alert_id: str,
        new_status: AlertStatus,
        audit_action: AuditAction,
        **kwargs,
    ) -> bool:
        """Generic status update helper."""
        now = datetime.now()

        # Build SET clause from kwargs
        set_parts = ["status = ?"]
        params = [new_status.value]

        for key, value in kwargs.items():
            set_parts.append(f"{key} = ?")
            if isinstance(value, datetime):
                params.append(value.isoformat())
            else:
                params.append(value)

        params.append(alert_id)

        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE alerts SET {', '.join(set_parts)} WHERE id = ?",
                params
            )

            if cursor.rowcount > 0:
                conn.execute(
                    """
                    INSERT INTO alert_audit (alert_id, action, performed_at)
                    VALUES (?, ?, ?)
                    """,
                    (alert_id, audit_action.value, now.isoformat())
                )
                conn.commit()
                return True

            return False

    # Query methods

    def list_alerts(
        self,
        status: AlertStatus | list[AlertStatus] | None = None,
        alert_type: AlertType | None = None,
        patient_mrn: str | None = None,
        severity: str | None = None,
        resolution_reason: str | None = None,
        limit: int = 100,
        include_expired_snooze: bool = True,
    ) -> list[StoredAlert]:
        """List alerts with optional filters.

        Args:
            status: Filter by status (single or list)
            alert_type: Filter by alert type
            patient_mrn: Filter by patient MRN
            severity: Filter by severity (critical, warning, info)
            resolution_reason: Filter by resolution reason
            limit: Maximum results
            include_expired_snooze: If True, include snoozed alerts past expiration

        Returns:
            List of matching StoredAlert objects
        """
        conditions = []
        params: list[Any] = []

        if status:
            if isinstance(status, list):
                placeholders = ",".join("?" * len(status))
                conditions.append(f"status IN ({placeholders})")
                params.extend(s.value for s in status)
            else:
                conditions.append("status = ?")
                params.append(status.value)

        if alert_type:
            conditions.append("alert_type = ?")
            params.append(alert_type.value)

        if patient_mrn:
            conditions.append("patient_mrn = ?")
            params.append(patient_mrn)

        if severity:
            conditions.append("severity = ?")
            params.append(severity)

        if resolution_reason:
            conditions.append("resolution_reason = ?")
            params.append(resolution_reason)

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        params.append(limit)

        with self._connect() as conn:
            cursor = conn.execute(
                f"""
                SELECT id, alert_type, source_id, status, severity,
                       patient_id, patient_mrn, patient_name,
                       title, summary, content,
                       created_at, sent_at, acknowledged_at, acknowledged_by,
                       resolved_at, resolved_by, resolution_reason, snoozed_until, notes
                FROM alerts
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT ?
                """,
                params
            )

            alerts = [StoredAlert.from_row(tuple(row)) for row in cursor.fetchall()]

        # Filter out expired snoozes if requested
        if not include_expired_snooze:
            now = datetime.now()
            alerts = [
                a for a in alerts
                if a.status != AlertStatus.SNOOZED or (a.snoozed_until and a.snoozed_until > now)
            ]

        return alerts

    def list_active_alerts(self) -> list[StoredAlert]:
        """List all active (non-resolved) alerts, respecting snooze expiration."""
        return self.list_alerts(
            status=[
                AlertStatus.PENDING,
                AlertStatus.SENT,
                AlertStatus.ACKNOWLEDGED,
                AlertStatus.SNOOZED,
            ],
            include_expired_snooze=True,
        )

    def list_actionable_alerts(self) -> list[StoredAlert]:
        """List alerts that need attention (active and not currently snoozed)."""
        alerts = self.list_active_alerts()
        return [a for a in alerts if a.is_actionable()]

    def get_audit_log(self, alert_id: str) -> list[AlertAuditEntry]:
        """Get audit history for an alert."""
        with self._connect() as conn:
            cursor = conn.execute(
                """
                SELECT id, alert_id, action, performed_by, performed_at, details
                FROM alert_audit
                WHERE alert_id = ?
                ORDER BY performed_at ASC
                """,
                (alert_id,)
            )

            return [AlertAuditEntry.from_row(tuple(row)) for row in cursor.fetchall()]

    # Statistics

    def get_stats(
        self,
        status: AlertStatus | list[AlertStatus] | None = None,
    ) -> dict[str, int]:
        """Get alert statistics.

        Args:
            status: Filter by status (single, list, or None for all)
        """
        with self._connect() as conn:
            stats = {}

            # Build status filter
            status_filter = ""
            params: list = []
            if status:
                if isinstance(status, list):
                    placeholders = ",".join("?" * len(status))
                    status_filter = f" WHERE status IN ({placeholders})"
                    params = [s.value for s in status]
                else:
                    status_filter = " WHERE status = ?"
                    params = [status.value]

            # Count by status (within filter)
            cursor = conn.execute(
                f"SELECT status, COUNT(*) FROM alerts{status_filter} GROUP BY status",
                params
            )
            for row in cursor:
                stats[f"status_{row[0]}"] = row[1]

            # Total (within filter)
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM alerts{status_filter}",
                params
            )
            stats["total"] = cursor.fetchone()[0]

            # Today's alerts (within filter)
            today = datetime.now().date().isoformat()
            today_filter = status_filter.replace(" WHERE ", " WHERE date(created_at) = ? AND ") if status_filter else " WHERE date(created_at) = ?"
            today_params = [today] + params if status_filter else [today]
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM alerts{today_filter}",
                today_params
            )
            stats["today"] = cursor.fetchone()[0]

            # Count by severity (within filter)
            cursor = conn.execute(
                f"SELECT severity, COUNT(*) FROM alerts{status_filter} GROUP BY severity",
                params
            )
            for row in cursor:
                stats[f"severity_{row[0]}"] = row[1]

            return stats

    # Analytics / Reports

    def get_analytics(
        self,
        alert_type: AlertType | None = None,
        days: int = 30,
    ) -> dict:
        """Get comprehensive analytics for reporting.

        Args:
            alert_type: Filter by alert type (None for all)
            days: Number of days to include in analysis

        Returns:
            Dictionary with analytics data
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        type_filter = ""
        params: list = [cutoff]

        if alert_type:
            type_filter = " AND alert_type = ?"
            params.append(alert_type.value)

        with self._connect() as conn:
            analytics = {
                "period_days": days,
                "alert_type": alert_type.value if alert_type else "all",
            }

            # Total alerts in period
            cursor = conn.execute(
                f"SELECT COUNT(*) FROM alerts WHERE created_at >= ?{type_filter}",
                params
            )
            analytics["total_alerts"] = cursor.fetchone()[0]

            # Alerts by day
            cursor = conn.execute(
                f"""
                SELECT date(created_at) as day, COUNT(*) as count
                FROM alerts
                WHERE created_at >= ?{type_filter}
                GROUP BY date(created_at)
                ORDER BY day DESC
                """,
                params
            )
            analytics["alerts_by_day"] = [
                {"date": row[0], "count": row[1]} for row in cursor.fetchall()
            ]

            # Average alerts per day
            if analytics["alerts_by_day"]:
                analytics["avg_alerts_per_day"] = round(
                    analytics["total_alerts"] / len(analytics["alerts_by_day"]), 1
                )
            else:
                analytics["avg_alerts_per_day"] = 0

            # Alerts by severity
            cursor = conn.execute(
                f"""
                SELECT severity, COUNT(*) as count
                FROM alerts
                WHERE created_at >= ?{type_filter}
                GROUP BY severity
                ORDER BY count DESC
                """,
                params
            )
            analytics["by_severity"] = {row[0]: row[1] for row in cursor.fetchall()}

            # Alerts by status
            cursor = conn.execute(
                f"""
                SELECT status, COUNT(*) as count
                FROM alerts
                WHERE created_at >= ?{type_filter}
                GROUP BY status
                """,
                params
            )
            analytics["by_status"] = {row[0]: row[1] for row in cursor.fetchall()}

            # Resolution reason breakdown (for resolved alerts)
            cursor = conn.execute(
                f"""
                SELECT resolution_reason, COUNT(*) as count
                FROM alerts
                WHERE created_at >= ?{type_filter}
                  AND status = 'resolved'
                  AND resolution_reason IS NOT NULL
                GROUP BY resolution_reason
                ORDER BY count DESC
                """,
                params
            )
            resolution_data = cursor.fetchall()
            total_resolved = sum(row[1] for row in resolution_data)
            analytics["resolution_breakdown"] = [
                {
                    "reason": row[0],
                    "count": row[1],
                    "percentage": round(row[1] / total_resolved * 100, 1) if total_resolved > 0 else 0
                }
                for row in resolution_data
            ]
            analytics["total_resolved"] = total_resolved

            # Response time metrics (for resolved alerts)
            cursor = conn.execute(
                f"""
                SELECT
                    AVG(CAST((julianday(acknowledged_at) - julianday(created_at)) * 24 * 60 AS INTEGER)) as avg_time_to_ack_min,
                    AVG(CAST((julianday(resolved_at) - julianday(created_at)) * 24 * 60 AS INTEGER)) as avg_time_to_resolve_min,
                    MIN(CAST((julianday(resolved_at) - julianday(created_at)) * 24 * 60 AS INTEGER)) as min_time_to_resolve_min,
                    MAX(CAST((julianday(resolved_at) - julianday(created_at)) * 24 * 60 AS INTEGER)) as max_time_to_resolve_min
                FROM alerts
                WHERE created_at >= ?{type_filter}
                  AND status = 'resolved'
                  AND resolved_at IS NOT NULL
                """,
                params
            )
            row = cursor.fetchone()
            analytics["response_times"] = {
                "avg_time_to_ack_minutes": round(row[0]) if row[0] else None,
                "avg_time_to_resolve_minutes": round(row[1]) if row[1] else None,
                "min_time_to_resolve_minutes": round(row[2]) if row[2] else None,
                "max_time_to_resolve_minutes": round(row[3]) if row[3] else None,
            }

            # Convert minutes to human-readable format
            def format_duration(minutes):
                if minutes is None:
                    return None
                if minutes < 60:
                    return f"{minutes} min"
                hours = minutes // 60
                mins = minutes % 60
                if hours < 24:
                    return f"{hours}h {mins}m" if mins else f"{hours}h"
                days = hours // 24
                hours = hours % 24
                return f"{days}d {hours}h" if hours else f"{days}d"

            analytics["response_times_formatted"] = {
                "avg_time_to_ack": format_duration(analytics["response_times"]["avg_time_to_ack_minutes"]),
                "avg_time_to_resolve": format_duration(analytics["response_times"]["avg_time_to_resolve_minutes"]),
                "min_time_to_resolve": format_duration(analytics["response_times"]["min_time_to_resolve_minutes"]),
                "max_time_to_resolve": format_duration(analytics["response_times"]["max_time_to_resolve_minutes"]),
            }

            # Resolution rate
            total_in_period = analytics["total_alerts"]
            if total_in_period > 0:
                analytics["resolution_rate"] = round(total_resolved / total_in_period * 100, 1)
            else:
                analytics["resolution_rate"] = 0

            # Alerts by day of week
            cursor = conn.execute(
                f"""
                SELECT
                    CASE CAST(strftime('%w', created_at) AS INTEGER)
                        WHEN 0 THEN 'Sunday'
                        WHEN 1 THEN 'Monday'
                        WHEN 2 THEN 'Tuesday'
                        WHEN 3 THEN 'Wednesday'
                        WHEN 4 THEN 'Thursday'
                        WHEN 5 THEN 'Friday'
                        WHEN 6 THEN 'Saturday'
                    END as day_name,
                    COUNT(*) as count
                FROM alerts
                WHERE created_at >= ?{type_filter}
                GROUP BY strftime('%w', created_at)
                ORDER BY CAST(strftime('%w', created_at) AS INTEGER)
                """,
                params
            )
            analytics["by_day_of_week"] = [
                {"day": row[0], "count": row[1]} for row in cursor.fetchall()
            ]

            return analytics

    # Cleanup

    def cleanup_old_resolved(self, days: int = 90) -> int:
        """Remove resolved alerts older than specified days.

        Returns number of alerts removed.
        """
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with self._connect() as conn:
            # First delete audit entries
            conn.execute(
                """
                DELETE FROM alert_audit
                WHERE alert_id IN (
                    SELECT id FROM alerts
                    WHERE status = ? AND resolved_at < ?
                )
                """,
                (AlertStatus.RESOLVED.value, cutoff)
            )

            # Then delete alerts
            cursor = conn.execute(
                "DELETE FROM alerts WHERE status = ? AND resolved_at < ?",
                (AlertStatus.RESOLVED.value, cutoff)
            )

            conn.commit()
            count = cursor.rowcount

            if count > 0:
                logger.info(f"Cleaned up {count} old resolved alerts")

            return count

    def auto_accept_old_alerts(
        self,
        alert_type: AlertType,
        hours: int = 48,
    ) -> int:
        """Auto-accept alerts older than specified hours without human resolution.

        This prevents the alert queue from growing indefinitely. Alerts
        that haven't been resolved within the time limit are auto-accepted.

        Args:
            alert_type: Type of alerts to auto-accept.
            hours: Hours after which to auto-accept. Default 48.

        Returns:
            Number of alerts auto-accepted.
        """
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        auto_accepted = 0

        with self._connect() as conn:
            # Find alerts that:
            # 1. Match the alert type
            # 2. Are not resolved
            # 3. Were created more than `hours` ago
            cursor = conn.execute(
                """
                SELECT id, patient_mrn, title
                FROM alerts
                WHERE alert_type = ?
                AND status != ?
                AND created_at < ?
                """,
                (alert_type.value, AlertStatus.RESOLVED.value, cutoff),
            )

            alerts_to_accept = cursor.fetchall()

            for row in alerts_to_accept:
                alert_id = row[0]

                # Resolve the alert
                conn.execute(
                    """
                    UPDATE alerts
                    SET status = ?, resolved_at = ?, resolved_by = ?,
                        resolution_reason = ?, notes = COALESCE(notes || ' | ', '') || ?
                    WHERE id = ?
                    """,
                    (
                        AlertStatus.RESOLVED.value,
                        datetime.now().isoformat(),
                        "Auto accepted",
                        ResolutionReason.AUTO_ACCEPTED.value,
                        f"Auto-accepted after {hours} hours without human review",
                        alert_id,
                    ),
                )

                # Add audit entry
                conn.execute(
                    """
                    INSERT INTO alert_audit (alert_id, action, performed_by, details)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        alert_id,
                        AuditAction.RESOLVED.value,
                        "Auto accepted",
                        f"Auto-accepted after {hours} hours without human review",
                    ),
                )

                auto_accepted += 1

            conn.commit()

        if auto_accepted > 0:
            logger.info(f"Auto-accepted {auto_accepted} {alert_type.value} alerts older than {hours} hours")

        return auto_accepted
