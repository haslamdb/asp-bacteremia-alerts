"""Alert storage module for persistent alert tracking.

Provides SQLite-backed storage for managing alert lifecycle:
- Prevent duplicate alerts via check_if_alerted()
- Track alert status (pending, sent, acknowledged, snoozed, resolved)
- Audit trail for compliance
"""

from .models import (
    AlertType,
    AlertStatus,
    ResolutionReason,
    StoredAlert,
    AlertAuditEntry,
)
from .store import AlertStore

__all__ = [
    "AlertType",
    "AlertStatus",
    "ResolutionReason",
    "StoredAlert",
    "AlertAuditEntry",
    "AlertStore",
]
