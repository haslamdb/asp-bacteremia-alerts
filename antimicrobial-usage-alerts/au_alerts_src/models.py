"""Data models for Antimicrobial Usage Alerts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class AlertSeverity(Enum):
    """Alert severity levels."""
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class Patient:
    """Patient information."""
    fhir_id: str
    mrn: str
    name: str
    birth_date: str | None = None
    gender: str | None = None
    location: str | None = None
    department: str | None = None


@dataclass
class MedicationOrder:
    """Active medication order."""
    fhir_id: str
    patient_id: str
    medication_name: str
    rxnorm_code: str | None = None
    dose: str | None = None
    route: str | None = None
    start_date: datetime | None = None
    status: str = "active"

    @property
    def duration_hours(self) -> float | None:
        """Calculate hours since medication started."""
        if self.start_date is None:
            return None
        delta = datetime.now() - self.start_date.replace(tzinfo=None)
        return delta.total_seconds() / 3600

    @property
    def duration_days(self) -> float | None:
        """Calculate days since medication started."""
        hours = self.duration_hours
        return hours / 24 if hours else None


@dataclass
class UsageAssessment:
    """Assessment of broad-spectrum antibiotic usage."""
    patient: Patient
    medication: MedicationOrder
    duration_hours: float
    threshold_hours: float
    exceeds_threshold: bool
    recommendation: str
    assessed_at: datetime = field(default_factory=datetime.now)
    severity: AlertSeverity = AlertSeverity.WARNING

    # Optional context
    related_cultures: list[str] = field(default_factory=list)
    justification_found: bool = False
    justification_reason: str | None = None


@dataclass
class IndicationCandidate:
    """Antibiotic order needing indication review."""
    id: str
    patient: Patient
    medication: MedicationOrder
    icd10_codes: list[str]
    icd10_classification: str  # A, S, N, P, FN, U
    icd10_primary_indication: str | None
    llm_extracted_indication: str | None
    llm_classification: str | None
    final_classification: str
    classification_source: str  # icd10, llm, manual
    status: str  # pending, alerted, reviewed
    alert_id: str | None = None


@dataclass
class IndicationAssessment:
    """Assessment result for an antibiotic order."""
    candidate: IndicationCandidate
    requires_alert: bool  # True if final_classification == 'N'
    recommendation: str
    severity: AlertSeverity
    assessed_at: datetime = field(default_factory=datetime.now)


@dataclass
class IndicationExtraction:
    """LLM extraction result from clinical notes."""
    found_indications: list[str]
    supporting_quotes: list[str]
    confidence: str  # HIGH, MEDIUM, LOW
    model_used: str
    prompt_version: str
    tokens_used: int | None = None
