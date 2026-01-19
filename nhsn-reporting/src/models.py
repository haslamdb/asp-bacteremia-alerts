"""Domain models for NHSN HAI reporting.

All models use dataclasses following existing asp-alerts patterns.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum
from typing import Any
import json


class HAIType(Enum):
    """Types of Healthcare-Associated Infections tracked."""
    CLABSI = "clabsi"  # Central Line-Associated BSI
    CAUTI = "cauti"    # Catheter-Associated UTI
    SSI = "ssi"        # Surgical Site Infection
    VAE = "vae"        # Ventilator-Associated Event


class CandidateStatus(Enum):
    """Status of an HAI candidate through the workflow."""
    PENDING = "pending"              # Awaiting LLM classification
    CLASSIFIED = "classified"        # LLM has classified
    PENDING_REVIEW = "pending_review"  # Needs IP review
    CONFIRMED = "confirmed"          # Confirmed as HAI
    REJECTED = "rejected"            # Not an HAI
    EXCLUDED = "excluded"            # Failed initial criteria


class ClassificationDecision(Enum):
    """LLM classification decision."""
    HAI_CONFIRMED = "hai_confirmed"
    NOT_HAI = "not_hai"
    PENDING_REVIEW = "pending_review"  # Low confidence


class ReviewQueueType(Enum):
    """Type of review queue."""
    IP_REVIEW = "ip_review"        # Standard IP review
    MANUAL_REVIEW = "manual_review"  # Complex cases


class ReviewerDecision(Enum):
    """Reviewer's final decision."""
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    NEEDS_MORE_INFO = "needs_more_info"


@dataclass
class Patient:
    """Patient information."""
    fhir_id: str
    mrn: str
    name: str
    birth_date: str | None = None
    location: str | None = None


@dataclass
class CultureResult:
    """Blood culture result."""
    fhir_id: str
    collection_date: datetime
    organism: str | None = None
    result_date: datetime | None = None
    specimen_source: str | None = None
    is_positive: bool = True


@dataclass
class DeviceInfo:
    """Central line or other device information."""
    device_type: str  # e.g., "central_venous_catheter", "picc"
    insertion_date: datetime | None = None
    removal_date: datetime | None = None
    site: str | None = None  # e.g., "right_subclavian"
    fhir_id: str | None = None

    def days_at_date(self, reference_date: datetime) -> int | None:
        """Calculate device days at a given date."""
        if self.insertion_date is None:
            return None
        delta = reference_date - self.insertion_date
        return delta.days

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "device_type": self.device_type,
            "insertion_date": self.insertion_date.isoformat() if self.insertion_date else None,
            "removal_date": self.removal_date.isoformat() if self.removal_date else None,
            "site": self.site,
            "fhir_id": self.fhir_id,
        }


@dataclass
class HAICandidate:
    """A candidate HAI event identified by rule-based screening.

    This represents a potential HAI that needs LLM classification
    and potentially IP review before confirmation.
    """
    id: str
    hai_type: HAIType
    patient: Patient
    culture: CultureResult
    device_info: DeviceInfo | None = None
    device_days_at_culture: int | None = None
    meets_initial_criteria: bool = True
    exclusion_reason: str | None = None
    status: CandidateStatus = CandidateStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "id": self.id,
            "hai_type": self.hai_type.value,
            "patient_id": self.patient.fhir_id,
            "patient_mrn": self.patient.mrn,
            "patient_name": self.patient.name,
            "culture_id": self.culture.fhir_id,
            "culture_date": self.culture.collection_date.isoformat(),
            "organism": self.culture.organism,
            "device_info": json.dumps(self.device_info.to_dict()) if self.device_info else None,
            "device_days_at_culture": self.device_days_at_culture,
            "meets_initial_criteria": self.meets_initial_criteria,
            "exclusion_reason": self.exclusion_reason,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class SupportingEvidence:
    """Evidence supporting or contradicting an HAI classification."""
    text: str
    source: str  # e.g., "progress_note", "id_consult", "a_p_section"
    date: datetime | None = None
    relevance: str | None = None  # Brief description of why this is relevant

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "source": self.source,
            "date": self.date.isoformat() if self.date else None,
            "relevance": self.relevance,
        }


@dataclass
class Classification:
    """LLM classification result for an HAI candidate."""
    id: str
    candidate_id: str
    decision: ClassificationDecision
    confidence: float  # 0.0 to 1.0
    alternative_source: str | None = None  # If not HAI, what is the likely source?
    is_mbi_lcbi: bool = False  # Mucosal barrier injury LCBI
    supporting_evidence: list[SupportingEvidence] = field(default_factory=list)
    contradicting_evidence: list[SupportingEvidence] = field(default_factory=list)
    reasoning: str | None = None
    model_used: str = ""
    prompt_version: str = ""
    tokens_used: int = 0
    processing_time_ms: int = 0
    created_at: datetime = field(default_factory=datetime.now)

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "decision": self.decision.value,
            "confidence": self.confidence,
            "alternative_source": self.alternative_source,
            "is_mbi_lcbi": self.is_mbi_lcbi,
            "supporting_evidence": json.dumps([e.to_dict() for e in self.supporting_evidence]),
            "contradicting_evidence": json.dumps([e.to_dict() for e in self.contradicting_evidence]),
            "reasoning": self.reasoning,
            "model_used": self.model_used,
            "prompt_version": self.prompt_version,
            "tokens_used": self.tokens_used,
            "processing_time_ms": self.processing_time_ms,
            "created_at": self.created_at.isoformat(),
        }


@dataclass
class Review:
    """IP review record for an HAI candidate.

    Tracks the IP reviewer's decision and whether they overrode the LLM
    classification. Override tracking helps assess LLM quality over time.
    """
    id: str
    candidate_id: str
    classification_id: str | None = None
    queue_type: ReviewQueueType = ReviewQueueType.IP_REVIEW
    reviewed: bool = False
    reviewer: str | None = None
    reviewer_decision: ReviewerDecision | None = None
    reviewer_notes: str | None = None
    # Override tracking
    llm_decision: str | None = None  # Original LLM decision for comparison
    is_override: bool = False  # True if reviewer disagreed with LLM
    override_reason: str | None = None  # Categorized reason for override
    created_at: datetime = field(default_factory=datetime.now)
    reviewed_at: datetime | None = None

    def determine_override(self, llm_decision: str) -> bool:
        """Determine if the reviewer's decision overrides the LLM.

        Args:
            llm_decision: The original LLM classification decision

        Returns:
            True if the reviewer disagreed with the LLM
        """
        if not self.reviewer_decision:
            return False

        # Map LLM decisions to expected reviewer decisions
        # hai_confirmed -> confirmed (agree) or rejected (override)
        # not_hai -> rejected (agree) or confirmed (override)
        # pending_review -> either is not considered an override

        if llm_decision == "hai_confirmed":
            return self.reviewer_decision == ReviewerDecision.REJECTED
        elif llm_decision == "not_hai":
            return self.reviewer_decision == ReviewerDecision.CONFIRMED
        else:
            # pending_review cases - reviewer is providing a decision, not overriding
            return False

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "classification_id": self.classification_id,
            "queue_type": self.queue_type.value,
            "reviewed": self.reviewed,
            "reviewer": self.reviewer,
            "reviewer_decision": self.reviewer_decision.value if self.reviewer_decision else None,
            "reviewer_notes": self.reviewer_notes,
            "llm_decision": self.llm_decision,
            "is_override": self.is_override,
            "override_reason": self.override_reason,
            "created_at": self.created_at.isoformat(),
            "reviewed_at": self.reviewed_at.isoformat() if self.reviewed_at else None,
        }


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


@dataclass
class ClinicalNote:
    """A clinical note retrieved from the EHR."""
    id: str
    patient_id: str
    note_type: str  # e.g., "progress_note", "id_consult", "discharge_summary"
    date: datetime
    content: str
    source: str  # "fhir" or "clarity"
    author: str | None = None

    def __hash__(self):
        return hash(self.id)


@dataclass
class NoteChunk:
    """A processed section from a clinical note."""
    note_id: str
    section_type: str  # e.g., "assessment_plan", "physical_exam", "id_section"
    content: str
    start_pos: int = 0
    end_pos: int = 0


@dataclass
class LLMAuditEntry:
    """Audit log entry for LLM calls."""
    candidate_id: str | None
    model: str
    success: bool
    input_tokens: int = 0
    output_tokens: int = 0
    response_time_ms: int = 0
    error_message: str | None = None
    created_at: datetime = field(default_factory=datetime.now)


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
    specimen_source: str | None = None
    organism_code: str  # NHSN organism code
    organism_name: str
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
