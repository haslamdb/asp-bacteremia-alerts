"""Domain models for HAI Detection module.

All models use dataclasses following existing AEGIS patterns.
This module contains models for HAI candidate detection, classification, and review.
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
    CDI = "cdi"        # Clostridioides difficile Infection


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


# ============================================================
# Surgical Site Infection (SSI) Models
# ============================================================

@dataclass
class SurgicalProcedure:
    """Surgical procedure from OR log or FHIR Procedure.

    Used for SSI surveillance - tracks NHSN operative procedures
    and their surveillance windows.
    """
    id: str
    procedure_code: str           # CPT or ICD-10-PCS code
    procedure_name: str
    procedure_date: datetime
    patient_id: str
    nhsn_category: str | None = None   # COLO, HPRO, CABG, etc.
    wound_class: int | None = None     # 1=Clean, 2=Clean-contaminated, 3=Contaminated, 4=Dirty
    duration_minutes: int | None = None
    asa_score: int | None = None       # ASA Physical Status Classification (1-5)
    primary_surgeon: str | None = None
    implant_used: bool = False
    implant_type: str | None = None
    fhir_id: str | None = None
    encounter_id: str | None = None
    location_code: str | None = None   # NHSN location code

    def get_surveillance_days(self) -> int:
        """Return surveillance period based on implant status.

        Standard: 30 days post-procedure
        With implant: 90 days post-procedure
        """
        return 90 if self.implant_used else 30

    def days_since_procedure(self, reference_date: datetime) -> int:
        """Calculate days since procedure at a given date."""
        # Normalize both dates to naive for comparison
        ref = reference_date.replace(tzinfo=None) if reference_date.tzinfo else reference_date
        proc = self.procedure_date.replace(tzinfo=None) if self.procedure_date.tzinfo else self.procedure_date
        delta = ref - proc
        return delta.days

    def is_within_surveillance(self, reference_date: datetime) -> bool:
        """Check if reference date is within surveillance window."""
        days = self.days_since_procedure(reference_date)
        return 0 <= days <= self.get_surveillance_days()

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "id": self.id,
            "procedure_code": self.procedure_code,
            "procedure_name": self.procedure_name,
            "procedure_date": self.procedure_date.isoformat(),
            "patient_id": self.patient_id,
            "nhsn_category": self.nhsn_category,
            "wound_class": self.wound_class,
            "duration_minutes": self.duration_minutes,
            "asa_score": self.asa_score,
            "primary_surgeon": self.primary_surgeon,
            "implant_used": self.implant_used,
            "implant_type": self.implant_type,
            "fhir_id": self.fhir_id,
            "encounter_id": self.encounter_id,
            "location_code": self.location_code,
        }

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return self.to_dict()


@dataclass
class SSICandidate:
    """Extended candidate info specific to SSI.

    Links to an HAICandidate but contains SSI-specific fields.
    """
    candidate_id: str
    procedure: SurgicalProcedure
    days_post_op: int
    ssi_type: str | None = None        # superficial, deep, organ_space
    infection_date: datetime | None = None
    wound_culture_organism: str | None = None
    wound_culture_date: datetime | None = None
    readmission_for_ssi: bool = False
    reoperation_for_ssi: bool = False

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "candidate_id": self.candidate_id,
            "procedure_id": self.procedure.id,
            "procedure_code": self.procedure.procedure_code,
            "procedure_name": self.procedure.procedure_name,
            "procedure_date": self.procedure.procedure_date.isoformat(),
            "nhsn_category": self.procedure.nhsn_category,
            "wound_class": self.procedure.wound_class,
            "days_post_op": self.days_post_op,
            "ssi_type": self.ssi_type,
            "infection_date": self.infection_date.isoformat() if self.infection_date else None,
            "wound_culture_organism": self.wound_culture_organism,
            "wound_culture_date": self.wound_culture_date.isoformat() if self.wound_culture_date else None,
            "readmission_for_ssi": self.readmission_for_ssi,
            "reoperation_for_ssi": self.reoperation_for_ssi,
            "implant_used": self.procedure.implant_used,
            "surveillance_days": self.procedure.get_surveillance_days(),
        }


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
# Ventilator-Associated Event (VAE) Models
# ============================================================

@dataclass
class VentilationEpisode:
    """A mechanical ventilation episode for a patient.

    Tracks intubation to extubation with daily ventilator parameters
    for VAE surveillance.
    """
    id: str
    patient_id: str
    patient_mrn: str
    intubation_date: datetime
    extubation_date: datetime | None = None
    encounter_id: str | None = None
    location_code: str | None = None  # NHSN location code
    fhir_device_id: str | None = None

    def get_ventilator_days(self, reference_date: datetime | None = None) -> int:
        """Calculate ventilator days.

        Day 1 is the day of intubation (calendar day counting).

        Args:
            reference_date: Date to calculate days at. If None, uses
                          extubation date or current date.

        Returns:
            Number of ventilator days (1-based)
        """
        if reference_date is None:
            if self.extubation_date:
                reference_date = self.extubation_date
            else:
                reference_date = datetime.now()

        # Normalize to date for calendar day calculation
        intub_date = self.intubation_date.date() if hasattr(self.intubation_date, 'date') else self.intubation_date
        ref_date = reference_date.date() if hasattr(reference_date, 'date') else reference_date
        delta = ref_date - intub_date
        return delta.days + 1  # Day 1 is intubation day

    def is_active(self, reference_date: datetime | None = None) -> bool:
        """Check if ventilation is still active at a given date."""
        if self.extubation_date is None:
            return True
        if reference_date is None:
            reference_date = datetime.now()
        return reference_date <= self.extubation_date

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "patient_mrn": self.patient_mrn,
            "intubation_date": self.intubation_date.isoformat(),
            "extubation_date": self.extubation_date.isoformat() if self.extubation_date else None,
            "encounter_id": self.encounter_id,
            "location_code": self.location_code,
            "fhir_device_id": self.fhir_device_id,
        }

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return self.to_dict()


@dataclass
class DailyVentParameters:
    """Daily ventilator parameters for VAE detection.

    Captures the minimum FiO2 and PEEP values for each calendar day
    of mechanical ventilation. Minimum values are used per NHSN criteria.
    """
    episode_id: str
    date: date
    ventilator_day: int  # 1-based day number
    min_fio2: float | None = None  # Minimum FiO2 for the day (percentage, e.g., 40.0)
    min_peep: float | None = None  # Minimum PEEP for the day (cmH2O)
    fio2_observation_id: str | None = None  # FHIR Observation ID
    peep_observation_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "episode_id": self.episode_id,
            "date": self.date.isoformat(),
            "ventilator_day": self.ventilator_day,
            "min_fio2": self.min_fio2,
            "min_peep": self.min_peep,
            "fio2_observation_id": self.fio2_observation_id,
            "peep_observation_id": self.peep_observation_id,
        }

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return self.to_dict()


@dataclass
class VAECandidate:
    """Extended candidate info specific to VAE.

    Links to an HAICandidate but contains VAE-specific fields
    including VAC detection details and IVAC/VAP criteria tracking.
    """
    candidate_id: str
    episode: VentilationEpisode
    vac_onset_date: date
    ventilator_day_at_onset: int

    # Baseline period (≥2 days stable/improving)
    baseline_start_date: date | None = None
    baseline_end_date: date | None = None
    baseline_min_fio2: float | None = None
    baseline_min_peep: float | None = None

    # Worsening detection
    worsening_start_date: date | None = None
    fio2_increase: float | None = None  # Percentage point increase from baseline
    peep_increase: float | None = None  # cmH2O increase from baseline
    met_fio2_criterion: bool = False
    met_peep_criterion: bool = False

    # Classification
    vae_classification: str | None = None  # vac, ivac, possible_vap, probable_vap
    vae_tier: int | None = None  # 1, 2, or 3

    # IVAC criteria
    temperature_criterion_met: bool = False
    wbc_criterion_met: bool = False
    antimicrobial_criterion_met: bool = False
    qualifying_antimicrobials: list[str] = field(default_factory=list)

    # VAP criteria
    purulent_secretions_met: bool = False
    positive_culture_met: bool = False
    quantitative_culture_met: bool = False
    organism_identified: str | None = None
    specimen_type: str | None = None

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "candidate_id": self.candidate_id,
            "episode_id": self.episode.id,
            "intubation_date": self.episode.intubation_date.isoformat(),
            "vac_onset_date": self.vac_onset_date.isoformat(),
            "ventilator_day_at_onset": self.ventilator_day_at_onset,
            "baseline_start_date": self.baseline_start_date.isoformat() if self.baseline_start_date else None,
            "baseline_end_date": self.baseline_end_date.isoformat() if self.baseline_end_date else None,
            "baseline_min_fio2": self.baseline_min_fio2,
            "baseline_min_peep": self.baseline_min_peep,
            "worsening_start_date": self.worsening_start_date.isoformat() if self.worsening_start_date else None,
            "fio2_increase": self.fio2_increase,
            "peep_increase": self.peep_increase,
            "met_fio2_criterion": self.met_fio2_criterion,
            "met_peep_criterion": self.met_peep_criterion,
            "vae_classification": self.vae_classification,
            "vae_tier": self.vae_tier,
            "temperature_criterion_met": self.temperature_criterion_met,
            "wbc_criterion_met": self.wbc_criterion_met,
            "antimicrobial_criterion_met": self.antimicrobial_criterion_met,
            "qualifying_antimicrobials": json.dumps(self.qualifying_antimicrobials),
            "purulent_secretions_met": self.purulent_secretions_met,
            "positive_culture_met": self.positive_culture_met,
            "quantitative_culture_met": self.quantitative_culture_met,
            "organism_identified": self.organism_identified,
            "specimen_type": self.specimen_type,
        }


# ============================================================
# Catheter-Associated Urinary Tract Infection (CAUTI) Models
# ============================================================

@dataclass
class CatheterEpisode:
    """An indwelling urinary catheter episode for a patient.

    Tracks catheter insertion to removal for CAUTI surveillance.
    """
    id: str
    patient_id: str
    patient_mrn: str
    insertion_date: datetime
    removal_date: datetime | None = None
    catheter_type: str | None = None  # urethral, suprapubic
    site: str | None = None
    encounter_id: str | None = None
    location_code: str | None = None
    fhir_device_id: str | None = None

    def get_catheter_days(self, reference_date: datetime | None = None) -> int:
        """Calculate catheter days.

        Day 1 is the day of insertion (calendar day counting).

        Args:
            reference_date: Date to calculate days at. If None, uses
                          removal date or current date.

        Returns:
            Number of catheter days (1-based)
        """
        if reference_date is None:
            if self.removal_date:
                reference_date = self.removal_date
            else:
                reference_date = datetime.now()

        # Normalize to date for calendar day calculation
        insert_date = self.insertion_date.date() if hasattr(self.insertion_date, 'date') else self.insertion_date
        ref_date = reference_date.date() if hasattr(reference_date, 'date') else reference_date
        delta = ref_date - insert_date
        return delta.days + 1  # Day 1 is insertion day

    def is_active(self, reference_date: datetime | None = None) -> bool:
        """Check if catheter is still in place at a given date."""
        if self.removal_date is None:
            return True
        if reference_date is None:
            reference_date = datetime.now()
        return reference_date <= self.removal_date

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "patient_mrn": self.patient_mrn,
            "insertion_date": self.insertion_date.isoformat(),
            "removal_date": self.removal_date.isoformat() if self.removal_date else None,
            "catheter_type": self.catheter_type,
            "site": self.site,
            "encounter_id": self.encounter_id,
            "location_code": self.location_code,
            "fhir_device_id": self.fhir_device_id,
        }

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return self.to_dict()


@dataclass
class CAUTICandidate:
    """Extended candidate info specific to CAUTI.

    Links to an HAICandidate but contains CAUTI-specific fields
    including catheter episode and symptom tracking.
    """
    candidate_id: str
    catheter_episode: CatheterEpisode
    catheter_days: int
    patient_age: int | None = None

    # Culture details
    culture_cfu_ml: int | None = None  # CFU/mL
    culture_organism: str | None = None
    culture_organism_count: int | None = None

    # Symptom tracking
    fever_documented: bool = False
    dysuria_documented: bool = False
    urgency_documented: bool = False
    frequency_documented: bool = False
    suprapubic_tenderness: bool = False
    cva_tenderness: bool = False

    # Classification
    classification: str | None = None  # cauti, not_cauti, asymptomatic_bacteriuria

    # Age-based fever rule tracking
    fever_eligible_per_age_rule: bool = True

    def get_symptoms_documented(self) -> list[str]:
        """Get list of documented symptom names."""
        symptoms = []
        if self.fever_documented:
            symptoms.append("fever")
        if self.dysuria_documented:
            symptoms.append("dysuria")
        if self.urgency_documented:
            symptoms.append("urgency")
        if self.frequency_documented:
            symptoms.append("frequency")
        if self.suprapubic_tenderness:
            symptoms.append("suprapubic_tenderness")
        if self.cva_tenderness:
            symptoms.append("cva_tenderness")
        return symptoms

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "candidate_id": self.candidate_id,
            "catheter_episode_id": self.catheter_episode.id,
            "catheter_days": self.catheter_days,
            "patient_age": self.patient_age,
            "culture_cfu_ml": self.culture_cfu_ml,
            "culture_organism": self.culture_organism,
            "culture_organism_count": self.culture_organism_count,
            "fever_documented": self.fever_documented,
            "dysuria_documented": self.dysuria_documented,
            "urgency_documented": self.urgency_documented,
            "frequency_documented": self.frequency_documented,
            "suprapubic_tenderness": self.suprapubic_tenderness,
            "cva_tenderness": self.cva_tenderness,
            "classification": self.classification,
            "fever_eligible_per_age_rule": self.fever_eligible_per_age_rule,
        }


# ============================================================
# Clostridioides difficile Infection (CDI) Models
# ============================================================

@dataclass
class CDITestResult:
    """C. difficile test result from laboratory.

    NHSN CDI LabID Event criteria:
    - Positive C. difficile toxin A and/or B test result, OR
    - Detection of toxin-producing C. difficile organism by culture/PCR
    - Specimen must be unformed stool (including ostomy)
    - Antigen-only results (GDH) do NOT qualify
    """
    fhir_id: str
    patient_id: str
    test_date: datetime
    test_type: str  # toxin_ab, toxin_a, toxin_b, pcr, naat, culture_toxigenic
    result: str  # positive, negative
    loinc_code: str | None = None
    specimen_type: str | None = None  # stool, ostomy
    is_formed_stool: bool = False  # If True, does not qualify for CDI
    encounter_id: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "fhir_id": self.fhir_id,
            "patient_id": self.patient_id,
            "test_date": self.test_date.isoformat(),
            "test_type": self.test_type,
            "result": self.result,
            "loinc_code": self.loinc_code,
            "specimen_type": self.specimen_type,
            "is_formed_stool": self.is_formed_stool,
            "encounter_id": self.encounter_id,
        }


@dataclass
class CDIEpisode:
    """A CDI episode for tracking recurrence.

    NHSN Recurrence Rules:
    - ≤14 days since last event: Duplicate (not reported)
    - 15-56 days since last event: Recurrent
    - >56 days since last event: New Incident
    """
    id: str
    patient_id: str
    test_date: datetime
    test_type: str
    onset_type: str  # ho (healthcare-facility onset), co (community onset), co_hcfa (CO-HCFA)
    is_recurrent: bool = False
    prior_episode_id: str | None = None
    admission_date: datetime | None = None
    discharge_date: datetime | None = None
    fhir_observation_id: str | None = None
    specimen_day: int | None = None  # Days since admission (day 1 = admission)
    created_at: datetime = field(default_factory=datetime.now)

    def days_since(self, reference_date: datetime) -> int:
        """Calculate days since this episode."""
        # Normalize both dates to naive for comparison
        ref = reference_date.replace(tzinfo=None) if reference_date.tzinfo else reference_date
        test = self.test_date.replace(tzinfo=None) if self.test_date.tzinfo else self.test_date
        delta = ref - test
        return delta.days

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON storage."""
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "test_date": self.test_date.isoformat(),
            "test_type": self.test_type,
            "onset_type": self.onset_type,
            "is_recurrent": self.is_recurrent,
            "prior_episode_id": self.prior_episode_id,
            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "discharge_date": self.discharge_date.isoformat() if self.discharge_date else None,
            "fhir_observation_id": self.fhir_observation_id,
            "specimen_day": self.specimen_day,
            "created_at": self.created_at.isoformat(),
        }

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return self.to_dict()


@dataclass
class CDICandidate:
    """Extended candidate info specific to CDI.

    Links to an HAICandidate but contains CDI-specific fields
    including timing-based classification and recurrence tracking.

    NHSN CDI Classification (Time-Based):
    - Healthcare-Facility-Onset (HO-CDI): Specimen collected >3 days after admission
    - Community-Onset (CO-CDI): Specimen collected ≤3 days after admission
    - Community-Onset Healthcare Facility-Associated (CO-HCFA): CO-CDI with discharge
      from any inpatient facility within prior 4 weeks
    """
    candidate_id: str
    test_result: CDITestResult
    admission_date: datetime
    specimen_day: int  # Days since admission (day 1 = admission day)
    onset_type: str  # ho, co, co_hcfa

    # Recurrence tracking
    prior_episodes: list[CDIEpisode] = field(default_factory=list)
    days_since_last_cdi: int | None = None
    is_recurrent: bool = False
    is_duplicate: bool = False  # Within 14-day window, should not be reported

    # Additional context
    recent_discharge_date: datetime | None = None  # For CO-HCFA detection
    recent_discharge_facility: str | None = None

    # Clinical context (from extraction)
    diarrhea_documented: bool = False
    treatment_initiated: bool = False
    treatment_type: str | None = None  # vancomycin, fidaxomicin, metronidazole

    # Classification result
    classification: str | None = None  # ho_cdi, co_cdi, co_hcfa_cdi, recurrent_ho, recurrent_co, duplicate, not_cdi

    def get_onset_display(self) -> str:
        """Get display name for onset type."""
        display_map = {
            "ho": "Healthcare-Facility Onset (HO-CDI)",
            "co": "Community Onset (CO-CDI)",
            "co_hcfa": "Community Onset, Healthcare Facility-Associated (CO-HCFA-CDI)",
        }
        return display_map.get(self.onset_type, self.onset_type)

    def to_db_row(self) -> dict:
        """Convert to database row format."""
        return {
            "candidate_id": self.candidate_id,
            "test_type": self.test_result.test_type,
            "test_date": self.test_result.test_date.isoformat(),
            "specimen_day": self.specimen_day,
            "onset_type": self.onset_type,
            "is_recurrent": self.is_recurrent,
            "days_since_last_cdi": self.days_since_last_cdi,
            "prior_episode_date": self.prior_episodes[0].test_date.isoformat() if self.prior_episodes else None,
            "diarrhea_documented": self.diarrhea_documented,
            "treatment_initiated": self.treatment_initiated,
            "treatment_type": self.treatment_type,
            "classification": self.classification,
            "recent_discharge_date": self.recent_discharge_date.isoformat() if self.recent_discharge_date else None,
        }
