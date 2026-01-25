"""Schemas for CAUTI (Catheter-Associated Urinary Tract Infection) rules engine.

This module defines:
- CAUTIClassification: Final classification from the rules engine
- CAUTIExtraction: What the LLM extracts from clinical notes
- CAUTIStructuredData: Structured data from EHR (FHIR/Clarity)
- CAUTIClassificationResult: Output of the CAUTI rules engine

NHSN CAUTI Criteria:
1. Indwelling urinary catheter (IUC) in place >2 calendar days
2. Positive urine culture >=10^5 CFU/mL with <=2 organisms (no mixed flora)
3. At least one sign/symptom: fever >38C, suprapubic tenderness, CVA pain/tenderness,
   urinary urgency, frequency, or dysuria
4. Not asymptomatic bacteriuria

Age-Based Fever Rule:
- Patient <=65 years: Fever can be used alone
- Patient >65 years: Fever requires catheter >2 days; other symptoms always valid

Reference: 2024 NHSN Patient Safety Component Manual, Chapter 7
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum

from .schemas import ConfidenceLevel, EvidenceSource


class CAUTIClassification(str, Enum):
    """Final CAUTI classification from the rules engine."""
    CAUTI = "cauti"                                 # Meets all CAUTI criteria
    NOT_CAUTI = "not_cauti"                         # Does not meet CAUTI criteria
    ASYMPTOMATIC_BACTERIURIA = "asymptomatic_bacteriuria"  # Positive culture but no symptoms
    NOT_ELIGIBLE = "not_eligible"                   # Doesn't meet basic eligibility
    INDETERMINATE = "indeterminate"                 # Insufficient info to classify


# ============================================================================
# LLM Extraction Schemas - What the LLM produces
# ============================================================================

@dataclass
class UrinarySymptomExtraction:
    """Urinary symptom findings from clinical notes."""
    # Fever
    fever_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    fever_temp_celsius: float | None = None
    fever_date: str | None = None
    fever_source: EvidenceSource | None = None

    # Suprapubic tenderness
    suprapubic_tenderness: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    suprapubic_tenderness_date: str | None = None
    suprapubic_tenderness_source: EvidenceSource | None = None

    # CVA (costovertebral angle) pain/tenderness
    cva_tenderness: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    cva_tenderness_date: str | None = None
    cva_tenderness_source: EvidenceSource | None = None

    # Urinary urgency
    urgency: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    urgency_date: str | None = None
    urgency_source: EvidenceSource | None = None

    # Urinary frequency
    frequency: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    frequency_date: str | None = None
    frequency_source: EvidenceSource | None = None

    # Dysuria (painful urination)
    dysuria: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    dysuria_date: str | None = None
    dysuria_source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "fever_documented": self.fever_documented.value,
            "fever_temp_celsius": self.fever_temp_celsius,
            "fever_date": self.fever_date,
            "fever_source": self.fever_source.to_dict() if self.fever_source else None,
            "suprapubic_tenderness": self.suprapubic_tenderness.value,
            "suprapubic_tenderness_date": self.suprapubic_tenderness_date,
            "suprapubic_tenderness_source": self.suprapubic_tenderness_source.to_dict() if self.suprapubic_tenderness_source else None,
            "cva_tenderness": self.cva_tenderness.value,
            "cva_tenderness_date": self.cva_tenderness_date,
            "cva_tenderness_source": self.cva_tenderness_source.to_dict() if self.cva_tenderness_source else None,
            "urgency": self.urgency.value,
            "urgency_date": self.urgency_date,
            "urgency_source": self.urgency_source.to_dict() if self.urgency_source else None,
            "frequency": self.frequency.value,
            "frequency_date": self.frequency_date,
            "frequency_source": self.frequency_source.to_dict() if self.frequency_source else None,
            "dysuria": self.dysuria.value,
            "dysuria_date": self.dysuria_date,
            "dysuria_source": self.dysuria_source.to_dict() if self.dysuria_source else None,
        }

    def has_any_symptom(self) -> bool:
        """Check if any symptom is documented (definite or probable)."""
        symptom_fields = [
            self.fever_documented,
            self.suprapubic_tenderness,
            self.cva_tenderness,
            self.urgency,
            self.frequency,
            self.dysuria,
        ]
        return any(
            s in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]
            for s in symptom_fields
        )

    def has_non_fever_symptom(self) -> bool:
        """Check if any non-fever symptom is documented."""
        non_fever_fields = [
            self.suprapubic_tenderness,
            self.cva_tenderness,
            self.urgency,
            self.frequency,
            self.dysuria,
        ]
        return any(
            s in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]
            for s in non_fever_fields
        )


@dataclass
class UrineCultureExtraction:
    """Urine culture findings from clinical notes."""
    culture_positive: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    organism_identified: str | None = None
    organism_count: int | None = None  # Number of organisms (<=2 for CAUTI)
    cfu_ml: int | None = None  # Colony forming units per mL
    collection_date: str | None = None
    collection_method: str | None = None  # catheter specimen, clean catch, etc.
    source: EvidenceSource | None = None

    # Is this considered mixed flora / contamination?
    mixed_flora: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    def to_dict(self) -> dict:
        return {
            "culture_positive": self.culture_positive.value,
            "organism_identified": self.organism_identified,
            "organism_count": self.organism_count,
            "cfu_ml": self.cfu_ml,
            "collection_date": self.collection_date,
            "collection_method": self.collection_method,
            "source": self.source.to_dict() if self.source else None,
            "mixed_flora": self.mixed_flora.value,
        }


@dataclass
class CatheterStatusExtraction:
    """Catheter status findings from clinical notes."""
    catheter_in_place: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    catheter_type: str | None = None  # Foley, suprapubic, etc.
    insertion_date: str | None = None
    removal_date: str | None = None
    days_in_place: int | None = None
    source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "catheter_in_place": self.catheter_in_place.value,
            "catheter_type": self.catheter_type,
            "insertion_date": self.insertion_date,
            "removal_date": self.removal_date,
            "days_in_place": self.days_in_place,
            "source": self.source.to_dict() if self.source else None,
        }


@dataclass
class CAUTIExtraction:
    """Complete extraction of CAUTI-relevant clinical information.

    This is what the LLM produces from clinical notes. The rules engine
    then combines this with structured EHR data to make a classification.

    The LLM is answering factual questions about:
    - Urinary symptoms (fever, dysuria, urgency, frequency, suprapubic pain, CVA tenderness)
    - Catheter status
    - Urine culture results
    - Clinical team's impression

    The LLM is NOT making the classification decision.
    """
    # Urinary symptoms
    symptoms: UrinarySymptomExtraction = field(default_factory=UrinarySymptomExtraction)

    # Urine culture findings
    cultures: list[UrineCultureExtraction] = field(default_factory=list)

    # Catheter status
    catheter_status: CatheterStatusExtraction = field(default_factory=CatheterStatusExtraction)

    # Clinical team's impression
    clinical_team_impression: str | None = None
    uti_suspected_by_team: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    uti_diagnosed: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    # Alternative diagnoses mentioned (things that might explain symptoms)
    alternative_diagnoses: list[str] = field(default_factory=list)
    # Examples: renal colic, urethritis, pyelonephritis, prostatitis, vaginitis

    # Extraction metadata
    documentation_quality: str = "adequate"  # poor, limited, adequate, detailed
    notes_reviewed_count: int = 0
    extraction_notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "symptoms": self.symptoms.to_dict(),
            "cultures": [c.to_dict() for c in self.cultures],
            "catheter_status": self.catheter_status.to_dict(),
            "clinical_team_impression": self.clinical_team_impression,
            "uti_suspected_by_team": self.uti_suspected_by_team.value,
            "uti_diagnosed": self.uti_diagnosed.value,
            "alternative_diagnoses": self.alternative_diagnoses,
            "documentation_quality": self.documentation_quality,
            "notes_reviewed_count": self.notes_reviewed_count,
            "extraction_notes": self.extraction_notes,
        }


# ============================================================================
# Structured EHR Data - From FHIR/Clarity, not LLM
# ============================================================================

@dataclass
class CAUTIStructuredData:
    """Structured data from EHR for CAUTI classification.

    This data comes from discrete fields in the EHR, not from
    clinical note text.
    """
    # Patient information
    patient_id: str
    patient_age: int | None = None  # Age in years (for fever rule)
    patient_birth_date: date | None = None

    # Catheter episode
    catheter_insertion_date: datetime | None = None
    catheter_removal_date: datetime | None = None
    catheter_type: str | None = None  # urethral, suprapubic
    catheter_days: int | None = None  # Days at culture date

    # Urine culture data
    culture_date: datetime | None = None
    culture_cfu_ml: int | None = None  # CFU/mL (>=10^5 required)
    culture_organism: str | None = None
    culture_organism_count: int | None = None  # Number of distinct organisms
    culture_fhir_id: str | None = None

    # Lab data (for temp/WBC if from discrete fields)
    temperatures: list[tuple[datetime, float]] = field(default_factory=list)

    # Location information
    location_at_culture: str | None = None
    location_type: str | None = None

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "patient_age": self.patient_age,
            "patient_birth_date": self.patient_birth_date.isoformat() if self.patient_birth_date else None,
            "catheter_insertion_date": self.catheter_insertion_date.isoformat() if self.catheter_insertion_date else None,
            "catheter_removal_date": self.catheter_removal_date.isoformat() if self.catheter_removal_date else None,
            "catheter_type": self.catheter_type,
            "catheter_days": self.catheter_days,
            "culture_date": self.culture_date.isoformat() if self.culture_date else None,
            "culture_cfu_ml": self.culture_cfu_ml,
            "culture_organism": self.culture_organism,
            "culture_organism_count": self.culture_organism_count,
            "culture_fhir_id": self.culture_fhir_id,
            "temperatures": [(t[0].isoformat(), t[1]) for t in self.temperatures],
            "location_at_culture": self.location_at_culture,
            "location_type": self.location_type,
        }


# ============================================================================
# Rules Engine Output
# ============================================================================

@dataclass
class CAUTIClassificationResult:
    """Output of the CAUTI rules engine.

    This is the final classification with full audit trail of
    which rules were applied and why.
    """
    classification: CAUTIClassification
    confidence: float  # 0.0 to 1.0
    reasoning: list[str]  # Step-by-step reasoning
    requires_review: bool
    review_reasons: list[str]

    # Catheter eligibility details
    catheter_eligible: bool = False
    catheter_days: int | None = None
    catheter_type: str | None = None

    # Culture criteria details
    culture_eligible: bool = False
    culture_cfu_ml: int | None = None
    culture_organism: str | None = None
    culture_organism_count: int | None = None

    # Symptom criteria details
    symptom_criterion_met: bool = False
    fever_documented: bool = False
    suprapubic_tenderness_documented: bool = False
    cva_tenderness_documented: bool = False
    urgency_documented: bool = False
    frequency_documented: bool = False
    dysuria_documented: bool = False

    # Age-based fever rule
    patient_age: int | None = None
    fever_eligible_per_age_rule: bool = True  # Default True, only False for >65 with catheter <=2 days

    def to_dict(self) -> dict:
        return {
            "classification": self.classification.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "requires_review": self.requires_review,
            "review_reasons": self.review_reasons,
            "catheter_eligible": self.catheter_eligible,
            "catheter_days": self.catheter_days,
            "catheter_type": self.catheter_type,
            "culture_eligible": self.culture_eligible,
            "culture_cfu_ml": self.culture_cfu_ml,
            "culture_organism": self.culture_organism,
            "culture_organism_count": self.culture_organism_count,
            "symptom_criterion_met": self.symptom_criterion_met,
            "fever_documented": self.fever_documented,
            "suprapubic_tenderness_documented": self.suprapubic_tenderness_documented,
            "cva_tenderness_documented": self.cva_tenderness_documented,
            "urgency_documented": self.urgency_documented,
            "frequency_documented": self.frequency_documented,
            "dysuria_documented": self.dysuria_documented,
            "patient_age": self.patient_age,
            "fever_eligible_per_age_rule": self.fever_eligible_per_age_rule,
        }
