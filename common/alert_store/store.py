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


class AlertStore:
    """SQLite-backed storage for managing alert lifecycle."""

    def __init__(self, db_path: str | None = None):
        """Initialize alert store.

        Args:
            db_path: Path to SQLite database. Defaults to ALERT_DB_PATH env var
                     or ~/.asp-alerts/alerts.db
        """
        if db_path:
            self.db_path = db_path
        else:
            self.db_path = os.environ.get(
                "ALERT_DB_PATH",
                os.path.expanduser("~/.asp-alerts/alerts.db")
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
        limit: int = 100,
        include_expired_snooze: bool = True,
    ) -> list[StoredAlert]:
        """List alerts with optional filters.

        Args:
            status: Filter by status (single or list)
            alert_type: Filter by alert type
            patient_mrn: Filter by patient MRN
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

    def get_stats(self) -> dict[str, int]:
        """Get alert statistics."""
        with self._connect() as conn:
            stats = {}

            # Count by status
            cursor = conn.execute(
                "SELECT status, COUNT(*) FROM alerts GROUP BY status"
            )
            for row in cursor:
                stats[f"status_{row[0]}"] = row[1]

            # Total
            cursor = conn.execute("SELECT COUNT(*) FROM alerts")
            stats["total"] = cursor.fetchone()[0]

            # Today's alerts
            today = datetime.now().date().isoformat()
            cursor = conn.execute(
                "SELECT COUNT(*) FROM alerts WHERE date(created_at) = ?",
                (today,)
            )
            stats["today"] = cursor.fetchone()[0]

            return stats

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
