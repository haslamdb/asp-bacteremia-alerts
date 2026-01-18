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
