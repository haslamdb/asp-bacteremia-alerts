"""Data models for persistent alert storage."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
import json


class AlertType(Enum):
    """Types of alerts that can be stored."""
    BACTEREMIA = "bacteremia"
    BROAD_SPECTRUM_USAGE = "broad_spectrum_usage"
    NHSN_CLABSI = "nhsn_clabsi"        # NHSN CLABSI candidate
    NHSN_SSI = "nhsn_ssi"              # NHSN SSI candidate
    NHSN_VAE = "nhsn_vae"              # NHSN VAE candidate
    NHSN_CAUTI = "nhsn_cauti"          # NHSN CAUTI candidate
    NHSN_CDI = "nhsn_cdi"              # NHSN CDI candidate
    NHSN_REVIEW = "nhsn_review"        # NHSN review queue item
    CUSTOM = "custom"


class AlertStatus(Enum):
    """Alert lifecycle status."""
    PENDING = "pending"          # Created but not yet sent
    SENT = "sent"                # Successfully sent to notification channel
    ACKNOWLEDGED = "acknowledged"  # User acknowledged the alert
    SNOOZED = "snoozed"          # Temporarily silenced
    RESOLVED = "resolved"        # Issue resolved, alert closed


class AuditAction(Enum):
    """Actions tracked in audit log."""
    CREATED = "created"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    SNOOZED = "snoozed"
    RESOLVED = "resolved"
    REOPENED = "reopened"
    NOTE_ADDED = "note_added"


class ResolutionReason(Enum):
    """Predefined reasons for resolving an alert."""
    ACKNOWLEDGED = "acknowledged"           # Just acknowledged, no action needed
    MESSAGED_TEAM = "messaged_team"         # Messaged the care team
    DISCUSSED_WITH_TEAM = "discussed_with_team"  # Discussed with care team
    APPROVED = "approved"                   # Therapy approved as appropriate
    SUGGESTED_ALTERNATIVE = "suggested_alternative"  # Recommended alternative therapy
    THERAPY_CHANGED = "therapy_changed"     # Therapy was changed
    THERAPY_STOPPED = "therapy_stopped"     # Therapy was discontinued
    PATIENT_DISCHARGED = "patient_discharged"  # Patient discharged
    OTHER = "other"                         # Other reason (see notes)

    @classmethod
    def display_name(cls, reason: "ResolutionReason | str") -> str:
        """Get human-readable display name for a reason.

        Args:
            reason: Either a ResolutionReason enum or a string value
        """
        display_names = {
            cls.ACKNOWLEDGED: "Acknowledged",
            cls.MESSAGED_TEAM: "Messaged Team",
            cls.DISCUSSED_WITH_TEAM: "Discussed with Team",
            cls.APPROVED: "Approved",
            cls.SUGGESTED_ALTERNATIVE: "Suggested Alternative",
            cls.THERAPY_CHANGED: "Therapy Changed",
            cls.THERAPY_STOPPED: "Therapy Stopped",
            cls.PATIENT_DISCHARGED: "Patient Discharged",
            cls.OTHER: "Other",
        }
        # If it's a string, try to convert to enum first
        if isinstance(reason, str):
            try:
                reason = cls(reason)
            except ValueError:
                return reason  # Return as-is if not a valid enum value
        return display_names.get(reason, reason.value)

    @classmethod
    def all_options(cls) -> list[tuple[str, str]]:
        """Get all options as (value, display_name) tuples for dropdowns."""
        return [(r.value, cls.display_name(r)) for r in cls]


@dataclass
class StoredAlert:
    """A persistently stored alert with full lifecycle tracking."""
    id: str
    alert_type: AlertType
    source_id: str  # FHIR order ID, culture ID, etc.
    status: AlertStatus
    severity: str  # "critical", "warning", "info"

    # Patient info
    patient_id: str | None = None
    patient_mrn: str | None = None
    patient_name: str | None = None

    # Alert content (stored as JSON)
    title: str = ""
    summary: str = ""
    content: dict = field(default_factory=dict)

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    sent_at: datetime | None = None
    acknowledged_at: datetime | None = None
    acknowledged_by: str | None = None
    resolved_at: datetime | None = None
    resolved_by: str | None = None
    resolution_reason: ResolutionReason | None = None

    # Snooze support
    snoozed_until: datetime | None = None

    # Notes
    notes: str | None = None

    def is_snoozed(self) -> bool:
        """Check if alert is currently snoozed (not expired)."""
        if self.status != AlertStatus.SNOOZED:
            return False
        if self.snoozed_until is None:
            return False
        return datetime.now() < self.snoozed_until

    def is_actionable(self) -> bool:
        """Check if alert requires attention (not resolved/expired snooze)."""
        if self.status == AlertStatus.RESOLVED:
            return False
        if self.is_snoozed():
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "id": self.id,
            "alert_type": self.alert_type.value,
            "source_id": self.source_id,
            "status": self.status.value,
            "severity": self.severity,
            "patient_id": self.patient_id,
            "patient_mrn": self.patient_mrn,
            "patient_name": self.patient_name,
            "title": self.title,
            "summary": self.summary,
            "content": self.content,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "acknowledged_by": self.acknowledged_by,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "resolution_reason": self.resolution_reason.value if self.resolution_reason else None,
            "resolution_reason_display": ResolutionReason.display_name(self.resolution_reason) if self.resolution_reason else None,
            "snoozed_until": self.snoozed_until.isoformat() if self.snoozed_until else None,
            "notes": self.notes,
        }

    @classmethod
    def from_row(cls, row: tuple) -> "StoredAlert":
        """Create from database row tuple."""
        # Row order matches schema: id, alert_type, source_id, status, severity,
        # patient_id, patient_mrn, patient_name, title, summary, content,
        # created_at, sent_at, acknowledged_at, acknowledged_by,
        # resolved_at, resolved_by, resolution_reason, snoozed_until, notes
        content_json = row[10]
        content = json.loads(content_json) if content_json else {}

        def parse_datetime(val):
            if val is None:
                return None
            if isinstance(val, datetime):
                return val
            return datetime.fromisoformat(val)

        # Parse resolution_reason
        resolution_reason_val = row[17] if len(row) > 17 else None
        resolution_reason = None
        if resolution_reason_val:
            try:
                resolution_reason = ResolutionReason(resolution_reason_val)
            except ValueError:
                pass  # Invalid value, leave as None

        return cls(
            id=row[0],
            alert_type=AlertType(row[1]),
            source_id=row[2],
            status=AlertStatus(row[3]),
            severity=row[4],
            patient_id=row[5],
            patient_mrn=row[6],
            patient_name=row[7],
            title=row[8] or "",
            summary=row[9] or "",
            content=content,
            created_at=parse_datetime(row[11]),
            sent_at=parse_datetime(row[12]),
            acknowledged_at=parse_datetime(row[13]),
            acknowledged_by=row[14],
            resolved_at=parse_datetime(row[15]),
            resolved_by=row[16],
            resolution_reason=resolution_reason,
            snoozed_until=parse_datetime(row[18]) if len(row) > 18 else None,
            notes=row[19] if len(row) > 19 else None,
        )


@dataclass
class AlertAuditEntry:
    """Audit log entry for alert actions."""
    id: int
    alert_id: str
    action: AuditAction
    performed_by: str | None
    performed_at: datetime
    details: str | None = None

    @classmethod
    def from_row(cls, row: tuple) -> "AlertAuditEntry":
        """Create from database row tuple."""
        performed_at = row[4]
        if isinstance(performed_at, str):
            performed_at = datetime.fromisoformat(performed_at)

        return cls(
            id=row[0],
            alert_id=row[1],
            action=AuditAction(row[2]),
            performed_by=row[3],
            performed_at=performed_at,
            details=row[5],
        )
