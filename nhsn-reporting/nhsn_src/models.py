"""Domain models for NHSN Reporting module.

All models use dataclasses following existing AEGIS patterns.
This module contains models for NHSN submission, AU/AR data, and denominators.

HAI candidate detection models are re-exported from hai-detection for convenience.
"""

import importlib.util
from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from pathlib import Path
from typing import Any
import json

# Re-export HAI detection models from hai-detection module
_hai_models_path = Path(__file__).parent.parent.parent / "hai-detection" / "hai_src" / "models.py"
_spec = importlib.util.spec_from_file_location("hai_detection_models", _hai_models_path)
_hai_models = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hai_models)

HAICandidate = _hai_models.HAICandidate
CandidateStatus = _hai_models.CandidateStatus
Classification = _hai_models.Classification
ClassificationDecision = _hai_models.ClassificationDecision
Review = _hai_models.Review
ReviewQueueType = _hai_models.ReviewQueueType
ReviewerDecision = _hai_models.ReviewerDecision
Patient = _hai_models.Patient
CultureResult = _hai_models.CultureResult
DeviceInfo = _hai_models.DeviceInfo
SupportingEvidence = _hai_models.SupportingEvidence
LLMAuditEntry = _hai_models.LLMAuditEntry

# CDI-specific models
CDICandidate = _hai_models.CDICandidate
CDITestResult = _hai_models.CDITestResult
CDIEpisode = _hai_models.CDIEpisode


class HAIType(Enum):
    """Types of Healthcare-Associated Infections tracked.

    Duplicated here for NHSN event reporting. The authoritative
    definition is in hai-detection module.
    """
    CLABSI = "clabsi"  # Central Line-Associated BSI
    CAUTI = "cauti"    # Catheter-Associated UTI
    SSI = "ssi"        # Surgical Site Infection
    VAE = "vae"        # Ventilator-Associated Event


@dataclass
class NHSNEvent:
    """Confirmed NHSN reportable event."""
    id: str
    candidate_id: str
    event_date: date
    hai_type: HAIType
    location_code: str | None = None  # NHSN location code
    pathogen_code: str | None = None  # NHSN pathogen code
    reported: bool = False
    reported_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "event_date": self.event_date.isoformat(),
            "hai_type": self.hai_type.value,
            "location_code": self.location_code,
            "pathogen_code": self.pathogen_code,
            "reported": self.reported,
            "reported_at": self.reported_at.isoformat() if self.reported_at else None,
            "created_at": self.created_at.isoformat(),
        }


# ============================================================
# Denominator Models
# ============================================================

@dataclass
class DenominatorDaily:
    """Daily denominator data for a location."""
    id: str
    date: date
    location_code: str
    location_type: str | None = None
    patient_days: int = 0
    central_line_days: int = 0
    urinary_catheter_days: int = 0
    ventilator_days: int = 0
    admissions: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "date": self.date.isoformat(),
            "location_code": self.location_code,
            "location_type": self.location_type,
            "patient_days": self.patient_days,
            "central_line_days": self.central_line_days,
            "urinary_catheter_days": self.urinary_catheter_days,
            "ventilator_days": self.ventilator_days,
            "admissions": self.admissions,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class DenominatorMonthly:
    """Monthly aggregated denominator data for NHSN submission."""
    id: str
    month: str  # YYYY-MM format
    location_code: str
    location_type: str | None = None
    patient_days: int = 0
    central_line_days: int = 0
    urinary_catheter_days: int = 0
    ventilator_days: int = 0
    admissions: int = 0
    central_line_utilization: float | None = None
    urinary_catheter_utilization: float | None = None
    ventilator_utilization: float | None = None
    submitted_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def calculate_utilization(self) -> None:
        """Calculate device utilization ratios."""
        if self.patient_days > 0:
            self.central_line_utilization = self.central_line_days / self.patient_days
            self.urinary_catheter_utilization = self.urinary_catheter_days / self.patient_days
            self.ventilator_utilization = self.ventilator_days / self.patient_days

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "month": self.month,
            "location_code": self.location_code,
            "location_type": self.location_type,
            "patient_days": self.patient_days,
            "central_line_days": self.central_line_days,
            "urinary_catheter_days": self.urinary_catheter_days,
            "ventilator_days": self.ventilator_days,
            "admissions": self.admissions,
            "central_line_utilization": self.central_line_utilization,
            "urinary_catheter_utilization": self.urinary_catheter_utilization,
            "ventilator_utilization": self.ventilator_utilization,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "created_at": self.created_at.isoformat(),
        }


# ============================================================
# Antibiotic Usage (AU) Models
# ============================================================

class AntimicrobialRoute(Enum):
    """Route of antimicrobial administration."""
    IV = "IV"
    PO = "PO"
    IM = "IM"
    TOPICAL = "TOPICAL"
    INHALED = "INHALED"


@dataclass
class AUMonthlySummary:
    """Monthly AU summary by location for NHSN submission."""
    id: str
    reporting_month: str  # YYYY-MM format
    location_code: str
    location_type: str | None = None
    patient_days: int = 0
    admissions: int = 0
    submitted_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "reporting_month": self.reporting_month,
            "location_code": self.location_code,
            "location_type": self.location_type,
            "patient_days": self.patient_days,
            "admissions": self.admissions,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AUAntimicrobialUsage:
    """Aggregated antimicrobial usage data for a summary period."""
    id: str
    summary_id: str
    antimicrobial_code: str  # NHSN code
    antimicrobial_name: str
    antimicrobial_class: str | None = None
    route: AntimicrobialRoute = AntimicrobialRoute.IV
    days_of_therapy: int = 0  # DOT
    defined_daily_doses: float | None = None  # DDD
    doses_administered: int | None = None
    patients_treated: int | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "summary_id": self.summary_id,
            "antimicrobial_code": self.antimicrobial_code,
            "antimicrobial_name": self.antimicrobial_name,
            "antimicrobial_class": self.antimicrobial_class,
            "route": self.route.value,
            "days_of_therapy": self.days_of_therapy,
            "defined_daily_doses": self.defined_daily_doses,
            "doses_administered": self.doses_administered,
            "patients_treated": self.patients_treated,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class AUPatientLevel:
    """Patient-level antimicrobial usage for drill-down."""
    id: str
    patient_id: str
    patient_mrn: str
    encounter_id: str
    antimicrobial_code: str
    antimicrobial_name: str
    route: AntimicrobialRoute
    start_date: date
    end_date: date | None = None
    total_doses: int | None = None
    days_of_therapy: int | None = None
    location_code: str | None = None
    indication: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "patient_mrn": self.patient_mrn,
            "encounter_id": self.encounter_id,
            "antimicrobial_code": self.antimicrobial_code,
            "antimicrobial_name": self.antimicrobial_name,
            "route": self.route.value,
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat() if self.end_date else None,
            "total_doses": self.total_doses,
            "days_of_therapy": self.days_of_therapy,
            "location_code": self.location_code,
            "indication": self.indication,
            "created_at": self.created_at.isoformat(),
        }


# ============================================================
# Antimicrobial Resistance (AR) Models
# ============================================================

class SusceptibilityInterpretation(Enum):
    """Antimicrobial susceptibility interpretation."""
    SUSCEPTIBLE = "S"
    INTERMEDIATE = "I"
    RESISTANT = "R"
    NON_SUSCEPTIBLE = "NS"


class ResistancePhenotype(Enum):
    """Common resistance phenotypes for NHSN AR reporting."""
    MRSA = "MRSA"  # Methicillin-resistant S. aureus
    MSSA = "MSSA"  # Methicillin-susceptible S. aureus
    VRE = "VRE"    # Vancomycin-resistant Enterococcus
    VSE = "VSE"    # Vancomycin-susceptible Enterococcus
    ESBL = "ESBL"  # Extended-spectrum beta-lactamase
    CRE = "CRE"    # Carbapenem-resistant Enterobacterales
    CRPA = "CRPA"  # Carbapenem-resistant P. aeruginosa
    CRAB = "CRAB"  # Carbapenem-resistant A. baumannii
    MDR = "MDR"    # Multi-drug resistant


@dataclass
class ARQuarterlySummary:
    """Quarterly AR summary by location for NHSN submission."""
    id: str
    reporting_quarter: str  # YYYY-Q# format
    location_code: str
    location_type: str | None = None
    submitted_at: datetime | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "reporting_quarter": self.reporting_quarter,
            "location_code": self.location_code,
            "location_type": self.location_type,
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ARIsolate:
    """Individual isolate for AR reporting."""
    id: str
    summary_id: str
    patient_id: str
    patient_mrn: str
    encounter_id: str
    specimen_date: date
    specimen_type: str  # Blood, Urine, Respiratory, etc.
    organism_code: str  # NHSN organism code
    organism_name: str
    specimen_source: str | None = None
    location_code: str | None = None
    is_first_isolate: bool = True  # First per patient per quarter
    is_hai_associated: bool = False
    hai_event_id: str | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "summary_id": self.summary_id,
            "patient_id": self.patient_id,
            "patient_mrn": self.patient_mrn,
            "encounter_id": self.encounter_id,
            "specimen_date": self.specimen_date.isoformat(),
            "specimen_type": self.specimen_type,
            "specimen_source": self.specimen_source,
            "organism_code": self.organism_code,
            "organism_name": self.organism_name,
            "location_code": self.location_code,
            "is_first_isolate": 1 if self.is_first_isolate else 0,
            "is_hai_associated": 1 if self.is_hai_associated else 0,
            "hai_event_id": self.hai_event_id,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ARSusceptibility:
    """Susceptibility result for an isolate."""
    id: str
    isolate_id: str
    antimicrobial_code: str
    antimicrobial_name: str
    interpretation: SusceptibilityInterpretation
    mic_value: str | None = None  # e.g., "<=0.5", ">8"
    mic_numeric: float | None = None
    disk_zone: int | None = None  # mm
    testing_method: str | None = None  # MIC, Disk, Vitek, etc.
    breakpoint_source: str | None = None  # CLSI, EUCAST
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "isolate_id": self.isolate_id,
            "antimicrobial_code": self.antimicrobial_code,
            "antimicrobial_name": self.antimicrobial_name,
            "interpretation": self.interpretation.value,
            "mic_value": self.mic_value,
            "mic_numeric": self.mic_numeric,
            "disk_zone": self.disk_zone,
            "testing_method": self.testing_method,
            "breakpoint_source": self.breakpoint_source,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class ARPhenotypeSummary:
    """Aggregated phenotype summary for AR reporting."""
    id: str
    summary_id: str
    organism_code: str
    organism_name: str
    phenotype: str  # MRSA, VRE, ESBL, CRE, etc.
    total_isolates: int
    resistant_isolates: int
    percent_resistant: float | None = None
    created_at: datetime = field(default_factory=datetime.now)

    def calculate_percent(self) -> None:
        """Calculate percent resistant."""
        if self.total_isolates > 0:
            self.percent_resistant = (self.resistant_isolates / self.total_isolates) * 100

    def to_db_row(self) -> dict:
        return {
            "id": self.id,
            "summary_id": self.summary_id,
            "organism_code": self.organism_code,
            "organism_name": self.organism_name,
            "phenotype": self.phenotype,
            "total_isolates": self.total_isolates,
            "resistant_isolates": self.resistant_isolates,
            "percent_resistant": self.percent_resistant,
            "created_at": self.created_at.isoformat(),
        }
