"""Schemas for CDI (Clostridioides difficile Infection) rules engine.

This module defines:
- CDIClassification: Final classification from the rules engine
- CDIExtraction: What the LLM extracts from clinical notes
- CDIStructuredData: Structured data from EHR (FHIR)
- CDIClassificationResult: Output of the CDI rules engine

NHSN CDI LabID Event Criteria:
1. Positive C. difficile toxin A and/or B test result, OR
2. Detection of toxin-producing C. difficile organism by culture/PCR
3. Specimen must be unformed stool (including ostomy)
4. Antigen-only results do NOT qualify

Classification (Time-Based):
- Healthcare-Facility-Onset (HO-CDI): Specimen collected >3 days after admission
- Community-Onset (CO-CDI): Specimen collected ≤3 days after admission
- Community-Onset Healthcare Facility-Associated (CO-HCFA): CO-CDI with discharge
  from any inpatient facility within prior 4 weeks

Incident vs Recurrent:
- Incident: First event OR >56 days since last CDI LabID event
- Recurrent: 15-56 days after most recent CDI LabID event
- Duplicate (not reported): ≤14 days after most recent event

Reference: 2024 NHSN Patient Safety Component Manual, Chapter 12
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum

from .schemas import ConfidenceLevel, EvidenceSource


class CDIClassification(str, Enum):
    """Final CDI classification from the rules engine."""
    HO_CDI = "ho_cdi"                    # Healthcare-facility onset
    CO_CDI = "co_cdi"                    # Community onset
    CO_HCFA_CDI = "co_hcfa_cdi"          # Community onset, healthcare-facility associated
    RECURRENT_HO = "recurrent_ho"        # Recurrent, facility onset
    RECURRENT_CO = "recurrent_co"        # Recurrent, community onset
    NOT_CDI = "not_cdi"                  # Does not meet criteria
    DUPLICATE = "duplicate"              # Within 14-day window, not reported
    NOT_ELIGIBLE = "not_eligible"        # Doesn't meet basic eligibility (e.g., formed stool)
    INDETERMINATE = "indeterminate"      # Insufficient info to classify


class CDIOnsetType(str, Enum):
    """CDI onset type based on timing."""
    HEALTHCARE_FACILITY = "ho"   # Healthcare-facility onset (>3 days)
    COMMUNITY = "co"             # Community onset (≤3 days)
    COMMUNITY_HCFA = "co_hcfa"   # Community onset, healthcare facility-associated


class CDIRecurrenceStatus(str, Enum):
    """CDI recurrence status based on timing from prior episode."""
    INCIDENT = "incident"        # First event or >56 days since last
    RECURRENT = "recurrent"      # 15-56 days since last event
    DUPLICATE = "duplicate"      # ≤14 days since last (not reported)


# ============================================================================
# LLM Extraction Schemas - What the LLM produces
# ============================================================================

@dataclass
class DiarrheaExtraction:
    """Diarrhea symptom findings from clinical notes."""
    diarrhea_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    diarrhea_date: str | None = None
    stool_frequency: int | None = None  # Number of stools per day if documented
    stool_consistency: str | None = None  # liquid, loose, watery, etc.
    source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "diarrhea_documented": self.diarrhea_documented.value,
            "diarrhea_date": self.diarrhea_date,
            "stool_frequency": self.stool_frequency,
            "stool_consistency": self.stool_consistency,
            "source": self.source.to_dict() if self.source else None,
        }


@dataclass
class CDIHistoryExtraction:
    """Prior CDI history findings from clinical notes."""
    prior_cdi_mentioned: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    prior_cdi_date: str | None = None
    prior_cdi_treatment: str | None = None
    source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "prior_cdi_mentioned": self.prior_cdi_mentioned.value,
            "prior_cdi_date": self.prior_cdi_date,
            "prior_cdi_treatment": self.prior_cdi_treatment,
            "source": self.source.to_dict() if self.source else None,
        }


@dataclass
class CDITreatmentExtraction:
    """CDI treatment findings from clinical notes."""
    treatment_initiated: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    treatment_type: str | None = None  # vancomycin, fidaxomicin, metronidazole
    treatment_route: str | None = None  # oral, iv, rectal
    treatment_start_date: str | None = None
    source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "treatment_initiated": self.treatment_initiated.value,
            "treatment_type": self.treatment_type,
            "treatment_route": self.treatment_route,
            "treatment_start_date": self.treatment_start_date,
            "source": self.source.to_dict() if self.source else None,
        }


@dataclass
class CDIExtraction:
    """Complete extraction of CDI-relevant clinical information.

    This is what the LLM produces from clinical notes. The rules engine
    then combines this with structured EHR data to make a classification.

    CDI extraction is simpler than device-associated HAIs:
    - Diarrhea documentation (usually implied by ordering test)
    - Prior CDI history
    - Treatment initiation
    - Clinical team's impression
    - Alternative diagnoses

    The LLM is NOT making the classification decision.
    """
    # Diarrhea symptoms
    diarrhea: DiarrheaExtraction = field(default_factory=DiarrheaExtraction)

    # Prior CDI history
    prior_history: CDIHistoryExtraction = field(default_factory=CDIHistoryExtraction)

    # CDI treatment
    treatment: CDITreatmentExtraction = field(default_factory=CDITreatmentExtraction)

    # Clinical team's impression
    clinical_team_impression: str | None = None
    cdi_suspected_by_team: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    cdi_diagnosed: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    # Risk factors documented
    recent_antibiotic_use: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    recent_hospitalization: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    recent_antibiotics_list: list[str] = field(default_factory=list)

    # Alternative diagnoses mentioned
    alternative_diagnoses: list[str] = field(default_factory=list)
    # Examples: antibiotic-associated diarrhea without CDI, viral gastroenteritis,
    # IBD flare, laxative use, tube feeds

    # Extraction metadata
    documentation_quality: str = "adequate"  # poor, limited, adequate, detailed
    notes_reviewed_count: int = 0
    extraction_notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "diarrhea": self.diarrhea.to_dict(),
            "prior_history": self.prior_history.to_dict(),
            "treatment": self.treatment.to_dict(),
            "clinical_team_impression": self.clinical_team_impression,
            "cdi_suspected_by_team": self.cdi_suspected_by_team.value,
            "cdi_diagnosed": self.cdi_diagnosed.value,
            "recent_antibiotic_use": self.recent_antibiotic_use.value,
            "recent_hospitalization": self.recent_hospitalization.value,
            "recent_antibiotics_list": self.recent_antibiotics_list,
            "alternative_diagnoses": self.alternative_diagnoses,
            "documentation_quality": self.documentation_quality,
            "notes_reviewed_count": self.notes_reviewed_count,
            "extraction_notes": self.extraction_notes,
        }


# ============================================================================
# Structured EHR Data - From FHIR, not LLM
# ============================================================================

@dataclass
class CDIPriorEpisode:
    """A prior CDI episode from structured data."""
    episode_id: str
    test_date: datetime
    onset_type: str
    is_recurrent: bool

    def to_dict(self) -> dict:
        return {
            "episode_id": self.episode_id,
            "test_date": self.test_date.isoformat(),
            "onset_type": self.onset_type,
            "is_recurrent": self.is_recurrent,
        }


@dataclass
class CDIStructuredData:
    """Structured data from EHR for CDI classification.

    This data comes from discrete fields in the EHR, not from
    clinical note text.
    """
    # Patient information
    patient_id: str
    patient_mrn: str | None = None

    # Current encounter
    admission_date: datetime | None = None
    discharge_date: datetime | None = None
    encounter_id: str | None = None

    # C. diff test data
    test_date: datetime | None = None
    test_type: str | None = None  # toxin_ab, pcr, naat, etc.
    test_result: str | None = None  # positive, negative
    loinc_code: str | None = None
    fhir_observation_id: str | None = None

    # Specimen information
    specimen_type: str | None = None  # stool, ostomy
    is_formed_stool: bool = False

    # Timing calculations
    specimen_day: int | None = None  # Days since admission (1-based)

    # Prior CDI history (from structured data)
    prior_cdi_events: list[CDIPriorEpisode] = field(default_factory=list)
    days_since_last_cdi: int | None = None
    last_cdi_date: datetime | None = None

    # Recent discharge (for CO-HCFA detection)
    prior_discharge_date: datetime | None = None
    prior_discharge_facility: str | None = None
    days_since_prior_discharge: int | None = None

    # Location information
    location_at_test: str | None = None
    location_type: str | None = None

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "patient_mrn": self.patient_mrn,
            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "discharge_date": self.discharge_date.isoformat() if self.discharge_date else None,
            "encounter_id": self.encounter_id,
            "test_date": self.test_date.isoformat() if self.test_date else None,
            "test_type": self.test_type,
            "test_result": self.test_result,
            "loinc_code": self.loinc_code,
            "fhir_observation_id": self.fhir_observation_id,
            "specimen_type": self.specimen_type,
            "is_formed_stool": self.is_formed_stool,
            "specimen_day": self.specimen_day,
            "prior_cdi_events": [e.to_dict() for e in self.prior_cdi_events],
            "days_since_last_cdi": self.days_since_last_cdi,
            "last_cdi_date": self.last_cdi_date.isoformat() if self.last_cdi_date else None,
            "prior_discharge_date": self.prior_discharge_date.isoformat() if self.prior_discharge_date else None,
            "prior_discharge_facility": self.prior_discharge_facility,
            "days_since_prior_discharge": self.days_since_prior_discharge,
            "location_at_test": self.location_at_test,
            "location_type": self.location_type,
        }


# ============================================================================
# Rules Engine Output
# ============================================================================

@dataclass
class CDIClassificationResult:
    """Output of the CDI rules engine.

    This is the final classification with full audit trail of
    which rules were applied and why.
    """
    classification: CDIClassification
    onset_type: str  # "healthcare_facility", "community", "community_hcfa"
    is_recurrent: bool
    confidence: float  # 0.0 to 1.0
    reasoning: list[str]  # Step-by-step reasoning
    requires_review: bool
    review_reasons: list[str]

    # Test eligibility details
    test_eligible: bool = False
    test_type: str | None = None
    test_positive: bool = False

    # Timing details
    specimen_day: int | None = None
    admission_date: datetime | None = None
    test_date: datetime | None = None

    # Recurrence details
    days_since_last_cdi: int | None = None
    recurrence_status: str | None = None  # incident, recurrent, duplicate

    # CO-HCFA details
    is_co_hcfa: bool = False
    prior_discharge_days: int | None = None

    # Clinical context
    diarrhea_documented: bool = False
    treatment_initiated: bool = False
    treatment_type: str | None = None

    def to_dict(self) -> dict:
        return {
            "classification": self.classification.value,
            "onset_type": self.onset_type,
            "is_recurrent": self.is_recurrent,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "requires_review": self.requires_review,
            "review_reasons": self.review_reasons,
            "test_eligible": self.test_eligible,
            "test_type": self.test_type,
            "test_positive": self.test_positive,
            "specimen_day": self.specimen_day,
            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "test_date": self.test_date.isoformat() if self.test_date else None,
            "days_since_last_cdi": self.days_since_last_cdi,
            "recurrence_status": self.recurrence_status,
            "is_co_hcfa": self.is_co_hcfa,
            "prior_discharge_days": self.prior_discharge_days,
            "diarrhea_documented": self.diarrhea_documented,
            "treatment_initiated": self.treatment_initiated,
            "treatment_type": self.treatment_type,
        }
