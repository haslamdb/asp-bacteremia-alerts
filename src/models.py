"""Data models for ASP Bacteremia Alerts."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class AlertSeverity(Enum):
    """Severity level for routing alerts to appropriate channels."""
    CRITICAL = "critical"  # Resistant organism + inadequate coverage
    WARNING = "warning"    # Possible gap, needs review
    INFO = "info"          # FYI, resolved, or daily summary


class AlertStatus(Enum):
    """Status of a coverage alert."""
    PENDING = "pending"
    SENT = "sent"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class CoverageStatus(Enum):
    """Whether antibiotic coverage is adequate."""
    ADEQUATE = "adequate"
    INADEQUATE = "inadequate"
    UNKNOWN = "unknown"
    PENDING_ID = "pending_identification"


@dataclass
class Patient:
    """Patient information."""
    fhir_id: str
    mrn: str
    name: str
    birth_date: Optional[str] = None
    gender: Optional[str] = None
    location: Optional[str] = None


@dataclass
class Antibiotic:
    """Active antibiotic order."""
    fhir_id: str
    medication_name: str
    rxnorm_code: Optional[str] = None
    route: Optional[str] = None
    status: str = "active"
    ordered_date: Optional[datetime] = None


@dataclass
class CultureResult:
    """Blood culture result."""
    fhir_id: str
    patient_id: str
    organism: Optional[str] = None
    gram_stain: Optional[str] = None
    status: str = "final"  # preliminary, final
    collected_date: Optional[datetime] = None
    resulted_date: Optional[datetime] = None
    snomed_code: Optional[str] = None


@dataclass
class CoverageAssessment:
    """Assessment of antibiotic coverage for a culture result."""
    patient: Patient
    culture: CultureResult
    current_antibiotics: list[Antibiotic] = field(default_factory=list)
    coverage_status: CoverageStatus = CoverageStatus.UNKNOWN
    recommendation: str = ""
    missing_coverage: list[str] = field(default_factory=list)
    assessed_at: datetime = field(default_factory=datetime.now)


@dataclass
class Alert:
    """Alert generated for inadequate coverage."""
    id: str
    assessment: CoverageAssessment
    status: AlertStatus = AlertStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    sent_at: Optional[datetime] = None
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
