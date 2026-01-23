"""Schemas for SSI (Surgical Site Infection) rules engine.

This module defines:
- SSIExtraction: What the LLM extracts from clinical notes
- SSIStructuredData: Structured data from EHR (Clarity/FHIR)
- SSIClassificationResult: Output of the SSI rules engine

The key principle: The LLM extracts *information*, the rules engine
applies *logic*. The LLM should never be asked to classify - only to
answer factual questions about what's documented.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from .schemas import ConfidenceLevel, EvidenceSource


class SSIType(str, Enum):
    """SSI classification types per NHSN criteria."""
    SUPERFICIAL_INCISIONAL = "superficial_incisional"
    DEEP_INCISIONAL = "deep_incisional"
    ORGAN_SPACE = "organ_space"


class SSIClassification(str, Enum):
    """Final SSI classification from the rules engine."""
    SUPERFICIAL_SSI = "superficial_ssi"     # Superficial incisional SSI
    DEEP_SSI = "deep_ssi"                   # Deep incisional SSI
    ORGAN_SPACE_SSI = "organ_space_ssi"     # Organ/space SSI
    NOT_SSI = "not_ssi"                     # Does not meet SSI criteria
    NOT_ELIGIBLE = "not_eligible"           # Doesn't meet basic eligibility
    INDETERMINATE = "indeterminate"         # Insufficient info to classify


# ============================================================================
# LLM Extraction Schemas - What the LLM produces
# ============================================================================

@dataclass
class WoundAssessmentExtraction:
    """Wound/incision assessment findings from clinical notes.

    Captures nursing assessments, surgical notes, and wound care documentation.
    """
    drainage_present: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    drainage_type: str | None = None  # purulent, serous, serosanguinous
    drainage_amount: str | None = None  # scant, moderate, copious
    drainage_source: EvidenceSource | None = None

    erythema_present: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    erythema_extent: str | None = None  # e.g., "2cm from incision"
    erythema_source: EvidenceSource | None = None

    warmth_present: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    induration_present: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    tenderness_present: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    wound_dehisced: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    dehiscence_type: str | None = None  # superficial, fascial
    dehiscence_source: EvidenceSource | None = None

    wound_opened_deliberately: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    wound_opened_reason: str | None = None  # drainage, debridement
    wound_opened_source: EvidenceSource | None = None

    assessment_date: str | None = None  # Date of wound assessment
    assessment_source: EvidenceSource | None = None  # Who documented

    def to_dict(self) -> dict:
        return {
            "drainage_present": self.drainage_present.value,
            "drainage_type": self.drainage_type,
            "drainage_amount": self.drainage_amount,
            "drainage_source": self.drainage_source.to_dict() if self.drainage_source else None,
            "erythema_present": self.erythema_present.value,
            "erythema_extent": self.erythema_extent,
            "erythema_source": self.erythema_source.to_dict() if self.erythema_source else None,
            "warmth_present": self.warmth_present.value,
            "induration_present": self.induration_present.value,
            "tenderness_present": self.tenderness_present.value,
            "wound_dehisced": self.wound_dehisced.value,
            "dehiscence_type": self.dehiscence_type,
            "dehiscence_source": self.dehiscence_source.to_dict() if self.dehiscence_source else None,
            "wound_opened_deliberately": self.wound_opened_deliberately.value,
            "wound_opened_reason": self.wound_opened_reason,
            "wound_opened_source": self.wound_opened_source.to_dict() if self.wound_opened_source else None,
            "assessment_date": self.assessment_date,
            "assessment_source": self.assessment_source.to_dict() if self.assessment_source else None,
        }


@dataclass
class SuperficialSSIFindings:
    """Findings relevant to Superficial Incisional SSI criteria.

    NHSN Superficial SSI requires at least ONE of:
    1. Purulent drainage from superficial incision
    2. Organisms from aseptically-obtained culture of fluid/tissue from superficial incision
    3. Signs (pain/tenderness, localized swelling, erythema, heat) AND incision deliberately
       opened by surgeon (unless culture-negative)
    4. Diagnosis of superficial SSI by physician/attending
    """
    # Criterion 1: Purulent drainage from superficial incision
    purulent_drainage_superficial: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    purulent_drainage_source: EvidenceSource | None = None
    purulent_drainage_quote: str | None = None

    # Criterion 2: Organisms from culture
    organisms_from_superficial_culture: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    organism_identified: str | None = None
    culture_source: EvidenceSource | None = None

    # Criterion 3: Signs + incision deliberately opened
    pain_or_tenderness: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    localized_swelling: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    erythema: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    heat: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    incision_deliberately_opened: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    signs_source: EvidenceSource | None = None

    # Criterion 4: Physician diagnosis
    physician_diagnosis_superficial_ssi: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    diagnosis_source: EvidenceSource | None = None
    diagnosis_quote: str | None = None

    def to_dict(self) -> dict:
        return {
            "purulent_drainage_superficial": self.purulent_drainage_superficial.value,
            "purulent_drainage_source": self.purulent_drainage_source.to_dict() if self.purulent_drainage_source else None,
            "purulent_drainage_quote": self.purulent_drainage_quote,
            "organisms_from_superficial_culture": self.organisms_from_superficial_culture.value,
            "organism_identified": self.organism_identified,
            "culture_source": self.culture_source.to_dict() if self.culture_source else None,
            "pain_or_tenderness": self.pain_or_tenderness.value,
            "localized_swelling": self.localized_swelling.value,
            "erythema": self.erythema.value,
            "heat": self.heat.value,
            "incision_deliberately_opened": self.incision_deliberately_opened.value,
            "signs_source": self.signs_source.to_dict() if self.signs_source else None,
            "physician_diagnosis_superficial_ssi": self.physician_diagnosis_superficial_ssi.value,
            "diagnosis_source": self.diagnosis_source.to_dict() if self.diagnosis_source else None,
            "diagnosis_quote": self.diagnosis_quote,
        }


@dataclass
class DeepSSIFindings:
    """Findings relevant to Deep Incisional SSI criteria.

    NHSN Deep SSI requires at least ONE of:
    1. Purulent drainage from deep incision (not organ/space)
    2. Deep incision that dehisces OR is deliberately opened by surgeon AND patient has
       fever (>38C) and/or localized pain/tenderness (unless culture-negative)
    3. Abscess or other evidence of infection involving deep incision on direct exam,
       during reoperation, or by imaging/histopathology
    4. Diagnosis of deep incisional SSI by physician/attending
    """
    # Criterion 1: Purulent drainage from deep incision
    purulent_drainage_deep: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    purulent_drainage_source: EvidenceSource | None = None
    purulent_drainage_quote: str | None = None

    # Criterion 2: Dehiscence/opened + fever/pain
    deep_incision_dehisces: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    deep_incision_opened: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    fever_greater_38: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    fever_value_celsius: float | None = None
    localized_pain_deep: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    dehiscence_source: EvidenceSource | None = None

    # Criterion 3: Abscess/evidence on exam/imaging/reoperation
    abscess_on_direct_exam: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    abscess_on_reoperation: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    abscess_on_imaging: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    imaging_type: str | None = None  # CT, MRI, ultrasound
    abscess_on_histopath: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    abscess_source: EvidenceSource | None = None

    # Criterion 4: Physician diagnosis
    physician_diagnosis_deep_ssi: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    diagnosis_source: EvidenceSource | None = None
    diagnosis_quote: str | None = None

    def to_dict(self) -> dict:
        return {
            "purulent_drainage_deep": self.purulent_drainage_deep.value,
            "purulent_drainage_source": self.purulent_drainage_source.to_dict() if self.purulent_drainage_source else None,
            "purulent_drainage_quote": self.purulent_drainage_quote,
            "deep_incision_dehisces": self.deep_incision_dehisces.value,
            "deep_incision_opened": self.deep_incision_opened.value,
            "fever_greater_38": self.fever_greater_38.value,
            "fever_value_celsius": self.fever_value_celsius,
            "localized_pain_deep": self.localized_pain_deep.value,
            "dehiscence_source": self.dehiscence_source.to_dict() if self.dehiscence_source else None,
            "abscess_on_direct_exam": self.abscess_on_direct_exam.value,
            "abscess_on_reoperation": self.abscess_on_reoperation.value,
            "abscess_on_imaging": self.abscess_on_imaging.value,
            "imaging_type": self.imaging_type,
            "abscess_on_histopath": self.abscess_on_histopath.value,
            "abscess_source": self.abscess_source.to_dict() if self.abscess_source else None,
            "physician_diagnosis_deep_ssi": self.physician_diagnosis_deep_ssi.value,
            "diagnosis_source": self.diagnosis_source.to_dict() if self.diagnosis_source else None,
            "diagnosis_quote": self.diagnosis_quote,
        }


@dataclass
class OrganSpaceSSIFindings:
    """Findings relevant to Organ/Space SSI criteria.

    NHSN Organ/Space SSI requires at least ONE of:
    1. Purulent drainage from a drain placed through a stab wound into organ/space
    2. Organisms from aseptically-obtained culture of fluid/tissue from organ/space
    3. Abscess or other evidence of infection involving organ/space on direct exam,
       during reoperation, or by imaging/histopathology
    4. Diagnosis of organ/space SSI by physician/attending
    """
    # Criterion 1: Purulent drainage from drain in organ/space
    purulent_drainage_drain: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    drain_location: str | None = None  # e.g., "JP drain in pelvis"
    drain_source: EvidenceSource | None = None

    # Criterion 2: Organisms from organ/space culture
    organisms_from_organ_space: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    organism_identified: str | None = None
    specimen_type: str | None = None  # peritoneal fluid, abscess, etc.
    culture_source: EvidenceSource | None = None

    # Criterion 3: Abscess/evidence on exam/imaging/reoperation
    abscess_on_direct_exam: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    abscess_on_reoperation: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    abscess_on_imaging: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    imaging_type: str | None = None
    imaging_findings: str | None = None
    abscess_on_histopath: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    abscess_source: EvidenceSource | None = None

    # Criterion 4: Physician diagnosis
    physician_diagnosis_organ_space_ssi: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    diagnosis_source: EvidenceSource | None = None
    diagnosis_quote: str | None = None

    # Organ/space involved
    organ_space_involved: str | None = None  # e.g., "intra-abdominal", "mediastinal"
    organ_space_nhsn_code: str | None = None  # NHSN specific site code

    def to_dict(self) -> dict:
        return {
            "purulent_drainage_drain": self.purulent_drainage_drain.value,
            "drain_location": self.drain_location,
            "drain_source": self.drain_source.to_dict() if self.drain_source else None,
            "organisms_from_organ_space": self.organisms_from_organ_space.value,
            "organism_identified": self.organism_identified,
            "specimen_type": self.specimen_type,
            "culture_source": self.culture_source.to_dict() if self.culture_source else None,
            "abscess_on_direct_exam": self.abscess_on_direct_exam.value,
            "abscess_on_reoperation": self.abscess_on_reoperation.value,
            "abscess_on_imaging": self.abscess_on_imaging.value,
            "imaging_type": self.imaging_type,
            "imaging_findings": self.imaging_findings,
            "abscess_on_histopath": self.abscess_on_histopath.value,
            "abscess_source": self.abscess_source.to_dict() if self.abscess_source else None,
            "physician_diagnosis_organ_space_ssi": self.physician_diagnosis_organ_space_ssi.value,
            "diagnosis_source": self.diagnosis_source.to_dict() if self.diagnosis_source else None,
            "diagnosis_quote": self.diagnosis_quote,
            "organ_space_involved": self.organ_space_involved,
            "organ_space_nhsn_code": self.organ_space_nhsn_code,
        }


@dataclass
class ReoperationFindings:
    """Findings related to reoperation for infection."""
    reoperation_performed: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    reoperation_date: str | None = None
    reoperation_indication: str | None = None  # e.g., "washout for infection"
    reoperation_findings: str | None = None  # e.g., "purulent fluid, necrotic tissue"
    reoperation_source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "reoperation_performed": self.reoperation_performed.value,
            "reoperation_date": self.reoperation_date,
            "reoperation_indication": self.reoperation_indication,
            "reoperation_findings": self.reoperation_findings,
            "reoperation_source": self.reoperation_source.to_dict() if self.reoperation_source else None,
        }


@dataclass
class SSIExtraction:
    """Complete extraction of SSI-relevant clinical information.

    This is what the LLM produces from clinical notes. The rules engine
    then combines this with structured EHR data to make a classification.

    The LLM is answering factual questions about wound status, drainage,
    cultures, imaging findings, and physician impressions - NOT making
    a classification decision.
    """
    # Wound assessments (may be multiple over time)
    wound_assessments: list[WoundAssessmentExtraction] = field(default_factory=list)

    # SSI type-specific findings
    superficial_findings: SuperficialSSIFindings = field(default_factory=SuperficialSSIFindings)
    deep_findings: DeepSSIFindings = field(default_factory=DeepSSIFindings)
    organ_space_findings: OrganSpaceSSIFindings = field(default_factory=OrganSpaceSSIFindings)

    # Reoperation findings
    reoperation: ReoperationFindings = field(default_factory=ReoperationFindings)

    # General infection indicators
    fever_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    fever_max_celsius: float | None = None
    leukocytosis_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    wbc_value: float | None = None

    # Antibiotic treatment for wound infection
    antibiotics_for_wound_infection: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    antibiotic_names: list[str] = field(default_factory=list)
    antibiotic_source: EvidenceSource | None = None

    # Clinical team's impression
    clinical_team_impression: str | None = None
    ssi_suspected_by_team: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    # Extraction metadata
    documentation_quality: str = "adequate"  # poor, limited, adequate, detailed
    notes_reviewed_count: int = 0
    extraction_notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "wound_assessments": [w.to_dict() for w in self.wound_assessments],
            "superficial_findings": self.superficial_findings.to_dict(),
            "deep_findings": self.deep_findings.to_dict(),
            "organ_space_findings": self.organ_space_findings.to_dict(),
            "reoperation": self.reoperation.to_dict(),
            "fever_documented": self.fever_documented.value,
            "fever_max_celsius": self.fever_max_celsius,
            "leukocytosis_documented": self.leukocytosis_documented.value,
            "wbc_value": self.wbc_value,
            "antibiotics_for_wound_infection": self.antibiotics_for_wound_infection.value,
            "antibiotic_names": self.antibiotic_names,
            "antibiotic_source": self.antibiotic_source.to_dict() if self.antibiotic_source else None,
            "clinical_team_impression": self.clinical_team_impression,
            "ssi_suspected_by_team": self.ssi_suspected_by_team.value,
            "documentation_quality": self.documentation_quality,
            "notes_reviewed_count": self.notes_reviewed_count,
            "extraction_notes": self.extraction_notes,
        }


# ============================================================================
# Structured EHR Data - From Clarity/FHIR, not LLM
# ============================================================================

@dataclass
class SSIStructuredData:
    """Structured data from EHR for SSI classification.

    This data comes from discrete fields in the EHR, not from
    clinical note text.
    """
    # Procedure information
    procedure_code: str
    procedure_name: str
    procedure_date: datetime
    nhsn_category: str
    wound_class: int | None = None  # 1-4
    duration_minutes: int | None = None
    asa_score: int | None = None  # 1-5
    implant_used: bool = False
    implant_type: str | None = None

    # Culture data (from micro lab)
    wound_culture_positive: bool = False
    wound_culture_organism: str | None = None
    wound_culture_date: datetime | None = None
    wound_culture_specimen: str | None = None

    # Timing
    days_post_op: int = 0
    surveillance_window_days: int = 30

    # Patient factors
    patient_days_at_infection: int | None = None
    location_at_infection: str | None = None

    # Readmission
    readmitted_for_ssi: bool = False
    readmission_date: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "procedure_code": self.procedure_code,
            "procedure_name": self.procedure_name,
            "procedure_date": self.procedure_date.isoformat(),
            "nhsn_category": self.nhsn_category,
            "wound_class": self.wound_class,
            "duration_minutes": self.duration_minutes,
            "asa_score": self.asa_score,
            "implant_used": self.implant_used,
            "implant_type": self.implant_type,
            "wound_culture_positive": self.wound_culture_positive,
            "wound_culture_organism": self.wound_culture_organism,
            "wound_culture_date": self.wound_culture_date.isoformat() if self.wound_culture_date else None,
            "wound_culture_specimen": self.wound_culture_specimen,
            "days_post_op": self.days_post_op,
            "surveillance_window_days": self.surveillance_window_days,
            "patient_days_at_infection": self.patient_days_at_infection,
            "location_at_infection": self.location_at_infection,
            "readmitted_for_ssi": self.readmitted_for_ssi,
            "readmission_date": self.readmission_date.isoformat() if self.readmission_date else None,
        }


# ============================================================================
# Rules Engine Output
# ============================================================================

@dataclass
class SSIClassificationResult:
    """Output of the SSI rules engine.

    This is the final classification with full audit trail of
    which rules were applied and why.
    """
    classification: SSIClassification
    ssi_type: SSIType | None  # Specific type if SSI
    confidence: float  # 0.0 to 1.0
    reasoning: list[str]  # Step-by-step reasoning
    requires_review: bool
    review_reasons: list[str]

    # Criteria evaluation details
    eligibility_checks: list[str] = field(default_factory=list)
    superficial_criteria_met: list[str] = field(default_factory=list)
    deep_criteria_met: list[str] = field(default_factory=list)
    organ_space_criteria_met: list[str] = field(default_factory=list)

    # NHSN reporting info
    nhsn_specific_site: str | None = None  # For organ/space SSI
    organism_for_report: str | None = None

    def to_dict(self) -> dict:
        return {
            "classification": self.classification.value,
            "ssi_type": self.ssi_type.value if self.ssi_type else None,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "requires_review": self.requires_review,
            "review_reasons": self.review_reasons,
            "eligibility_checks": self.eligibility_checks,
            "superficial_criteria_met": self.superficial_criteria_met,
            "deep_criteria_met": self.deep_criteria_met,
            "organ_space_criteria_met": self.organ_space_criteria_met,
            "nhsn_specific_site": self.nhsn_specific_site,
            "organism_for_report": self.organism_for_report,
        }
