"""Data models for guideline adherence monitoring."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EpisodeStatus(Enum):
    """Status of a monitored episode."""
    ACTIVE = "active"           # Bundle monitoring in progress
    COMPLETE = "complete"       # All time windows closed, final assessment
    CLOSED = "closed"           # Patient discharged or bundle no longer applies


class ElementCheckStatus(Enum):
    """Status of individual element check."""
    MET = "met"                 # Element completed within window
    NOT_MET = "not_met"         # Window expired without completion
    PENDING = "pending"         # Still within window
    NOT_APPLICABLE = "na"       # Element doesn't apply to this patient


@dataclass
class PendingElement:
    """An element that is pending completion within its time window."""
    element_id: str
    element_name: str
    time_window_hours: float
    deadline: datetime
    data_source: str
    query_logic: str


@dataclass
class ElementCheckResult:
    """Result of checking a single bundle element."""
    element_id: str
    element_name: str
    status: ElementCheckStatus
    time_window_hours: float | None = None
    deadline: datetime | None = None
    completed_at: datetime | None = None
    value: Any = None
    notes: str = ""


@dataclass
class GuidelineMonitorResult:
    """Result of monitoring a patient episode for guideline adherence."""
    # Patient/Episode identifiers
    patient_id: str
    patient_mrn: str
    patient_name: str
    encounter_id: str
    location: str | None = None

    # Bundle info
    bundle_id: str = ""
    bundle_name: str = ""

    # Timing
    trigger_time: datetime = field(default_factory=datetime.now)
    assessment_time: datetime = field(default_factory=datetime.now)

    # Status
    episode_status: EpisodeStatus = EpisodeStatus.ACTIVE

    # Element results
    element_results: list[ElementCheckResult] = field(default_factory=list)

    # Cached for quick access
    _met_elements: list[str] = field(default_factory=list, repr=False)
    _not_met_elements: list[str] = field(default_factory=list, repr=False)
    _pending_elements: list[str] = field(default_factory=list, repr=False)

    @property
    def total_applicable(self) -> int:
        """Count of applicable elements (not N/A)."""
        return sum(
            1 for r in self.element_results
            if r.status != ElementCheckStatus.NOT_APPLICABLE
        )

    @property
    def total_met(self) -> int:
        """Count of elements met."""
        return sum(
            1 for r in self.element_results
            if r.status == ElementCheckStatus.MET
        )

    @property
    def total_not_met(self) -> int:
        """Count of elements not met (window expired)."""
        return sum(
            1 for r in self.element_results
            if r.status == ElementCheckStatus.NOT_MET
        )

    @property
    def total_pending(self) -> int:
        """Count of elements still pending."""
        return sum(
            1 for r in self.element_results
            if r.status == ElementCheckStatus.PENDING
        )

    @property
    def adherence_percentage(self) -> float:
        """Calculate adherence percentage (met / applicable)."""
        # Only count completed elements (met + not_met)
        completed = self.total_met + self.total_not_met
        if completed == 0:
            return 100.0  # All pending, no violations yet
        return round((self.total_met / completed) * 100, 1)

    @property
    def overall_adherence_percentage(self) -> float:
        """Calculate overall adherence including pending as not yet met."""
        if self.total_applicable == 0:
            return 100.0
        return round((self.total_met / self.total_applicable) * 100, 1)

    def get_not_met_elements(self) -> list[ElementCheckResult]:
        """Get list of elements that were not met."""
        return [r for r in self.element_results if r.status == ElementCheckStatus.NOT_MET]

    def get_pending_elements(self) -> list[ElementCheckResult]:
        """Get list of elements still pending."""
        return [r for r in self.element_results if r.status == ElementCheckStatus.PENDING]

    def to_dict(self) -> dict:
        """Convert to JSON-serializable dictionary."""
        return {
            "patient_id": self.patient_id,
            "patient_mrn": self.patient_mrn,
            "patient_name": self.patient_name,
            "encounter_id": self.encounter_id,
            "location": self.location,
            "bundle_id": self.bundle_id,
            "bundle_name": self.bundle_name,
            "trigger_time": self.trigger_time.isoformat() if self.trigger_time else None,
            "assessment_time": self.assessment_time.isoformat() if self.assessment_time else None,
            "episode_status": self.episode_status.value,
            "total_applicable": self.total_applicable,
            "total_met": self.total_met,
            "total_not_met": self.total_not_met,
            "total_pending": self.total_pending,
            "adherence_percentage": self.adherence_percentage,
            "element_results": [
                {
                    "element_id": r.element_id,
                    "element_name": r.element_name,
                    "status": r.status.value,
                    "time_window_hours": r.time_window_hours,
                    "deadline": r.deadline.isoformat() if r.deadline else None,
                    "completed_at": r.completed_at.isoformat() if r.completed_at else None,
                    "value": r.value,
                    "notes": r.notes,
                }
                for r in self.element_results
            ],
        }


@dataclass
class AlertContent:
    """Content structure for GUIDELINE_DEVIATION alerts."""
    bundle_id: str
    bundle_name: str
    trigger_time: str  # ISO format
    element_id: str
    element_name: str
    time_window_hours: float
    window_expired_at: str  # ISO format
    status: str  # "not_met"
    recommendation: str
    overall_adherence_pct: float
    location: str | None = None
    episode_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for alert storage."""
        return {
            "bundle_id": self.bundle_id,
            "bundle_name": self.bundle_name,
            "trigger_time": self.trigger_time,
            "element_id": self.element_id,
            "element_name": self.element_name,
            "time_window_hours": self.time_window_hours,
            "window_expired_at": self.window_expired_at,
            "status": self.status,
            "recommendation": self.recommendation,
            "overall_adherence_pct": self.overall_adherence_pct,
            "location": self.location,
            "episode_id": self.episode_id,
        }
