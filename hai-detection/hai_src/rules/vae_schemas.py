"""Schemas for VAE (Ventilator-Associated Event) rules engine.

This module defines:
- VAEClassification: Final classification from the rules engine
- VAEExtraction: What the LLM extracts from clinical notes
- VAEStructuredData: Structured data from EHR (FHIR/Clarity)
- VAEClassificationResult: Output of the VAE rules engine

NHSN VAE Hierarchy (most specific first):
1. Probable VAP - IVAC + purulent secretions + positive quantitative culture
2. Possible VAP - IVAC + purulent secretions OR positive respiratory culture
3. IVAC - VAC + temperature/WBC abnormality + new antimicrobial ≥4 days
4. VAC - ≥2 days stable ventilator settings followed by ≥2 days sustained worsening

Reference: 2024 NHSN Patient Safety Component Manual, Chapter 10
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum

from .schemas import ConfidenceLevel, EvidenceSource


class VAEClassification(str, Enum):
    """Final VAE classification from the rules engine.

    Classifications are hierarchical - a patient meeting Probable VAP
    criteria also meets IVAC and VAC criteria by definition.
    """
    PROBABLE_VAP = "probable_vap"       # IVAC + purulent secretions + positive quant culture
    POSSIBLE_VAP = "possible_vap"       # IVAC + purulent secretions OR positive culture
    IVAC = "ivac"                       # VAC + infection indicators
    VAC = "vac"                         # Ventilator-Associated Condition only
    NOT_VAE = "not_vae"                 # Does not meet VAE criteria
    NOT_ELIGIBLE = "not_eligible"       # Doesn't meet basic eligibility (e.g., <2 vent days)
    INDETERMINATE = "indeterminate"     # Insufficient info to classify


class VAETier(str, Enum):
    """VAE tier for reporting purposes."""
    TIER_1 = "tier_1"  # VAC only
    TIER_2 = "tier_2"  # IVAC
    TIER_3 = "tier_3"  # Possible/Probable VAP


# ============================================================================
# LLM Extraction Schemas - What the LLM produces
# ============================================================================

@dataclass
class TemperatureExtraction:
    """Temperature findings from clinical notes."""
    fever_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    max_temp_celsius: float | None = None
    fever_date: str | None = None
    fever_source: EvidenceSource | None = None

    hypothermia_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    min_temp_celsius: float | None = None
    hypothermia_date: str | None = None
    hypothermia_source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "fever_documented": self.fever_documented.value,
            "max_temp_celsius": self.max_temp_celsius,
            "fever_date": self.fever_date,
            "fever_source": self.fever_source.to_dict() if self.fever_source else None,
            "hypothermia_documented": self.hypothermia_documented.value,
            "min_temp_celsius": self.min_temp_celsius,
            "hypothermia_date": self.hypothermia_date,
            "hypothermia_source": self.hypothermia_source.to_dict() if self.hypothermia_source else None,
        }


@dataclass
class WBCExtraction:
    """White blood cell count findings from clinical notes."""
    leukocytosis_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    max_wbc: float | None = None  # cells/µL
    leukocytosis_date: str | None = None
    leukocytosis_source: EvidenceSource | None = None

    leukopenia_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    min_wbc: float | None = None
    leukopenia_date: str | None = None
    leukopenia_source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "leukocytosis_documented": self.leukocytosis_documented.value,
            "max_wbc": self.max_wbc,
            "leukocytosis_date": self.leukocytosis_date,
            "leukocytosis_source": self.leukocytosis_source.to_dict() if self.leukocytosis_source else None,
            "leukopenia_documented": self.leukopenia_documented.value,
            "min_wbc": self.min_wbc,
            "leukopenia_date": self.leukopenia_date,
            "leukopenia_source": self.leukopenia_source.to_dict() if self.leukopenia_source else None,
        }


@dataclass
class AntimicrobialExtraction:
    """Antimicrobial treatment findings from clinical notes."""
    new_antimicrobial_started: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    antimicrobial_names: list[str] = field(default_factory=list)
    start_date: str | None = None
    route: str | None = None  # IV, PO, inhaled
    indication: str | None = None  # e.g., "pneumonia", "sepsis", "VAP"
    duration_days: int | None = None
    source: EvidenceSource | None = None

    # Track if antimicrobials continued ≥4 calendar days
    continued_four_or_more_days: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    def to_dict(self) -> dict:
        return {
            "new_antimicrobial_started": self.new_antimicrobial_started.value,
            "antimicrobial_names": self.antimicrobial_names,
            "start_date": self.start_date,
            "route": self.route,
            "indication": self.indication,
            "duration_days": self.duration_days,
            "source": self.source.to_dict() if self.source else None,
            "continued_four_or_more_days": self.continued_four_or_more_days.value,
        }


@dataclass
class RespiratorySecretionsExtraction:
    """Respiratory secretion findings from clinical notes."""
    purulent_secretions: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    secretion_description: str | None = None  # e.g., "thick yellow-green sputum"
    secretion_date: str | None = None
    source: EvidenceSource | None = None

    # Quantitative gram stain (≥25 PMNs and ≤10 epithelial cells per LPF)
    gram_stain_positive: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    pmn_count: int | None = None
    epithelial_count: int | None = None

    def to_dict(self) -> dict:
        return {
            "purulent_secretions": self.purulent_secretions.value,
            "secretion_description": self.secretion_description,
            "secretion_date": self.secretion_date,
            "source": self.source.to_dict() if self.source else None,
            "gram_stain_positive": self.gram_stain_positive.value,
            "pmn_count": self.pmn_count,
            "epithelial_count": self.epithelial_count,
        }


@dataclass
class RespiratoryCultureExtraction:
    """Respiratory culture findings from clinical notes."""
    culture_positive: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    specimen_type: str | None = None  # BAL, mini-BAL, ETA, PSB, lung tissue
    organism_identified: str | None = None
    colony_count: str | None = None  # e.g., "10^5 CFU/mL"
    collection_date: str | None = None
    source: EvidenceSource | None = None

    # For quantitative threshold evaluation
    meets_quantitative_threshold: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    def to_dict(self) -> dict:
        return {
            "culture_positive": self.culture_positive.value,
            "specimen_type": self.specimen_type,
            "organism_identified": self.organism_identified,
            "colony_count": self.colony_count,
            "collection_date": self.collection_date,
            "source": self.source.to_dict() if self.source else None,
            "meets_quantitative_threshold": self.meets_quantitative_threshold.value,
        }


@dataclass
class VentilatorStatusExtraction:
    """Ventilator status findings from clinical notes."""
    on_mechanical_ventilation: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    ventilator_mode: str | None = None  # AC, SIMV, PSV, etc.
    intubation_date: str | None = None
    extubation_date: str | None = None

    # Respiratory deterioration indicators
    increased_fio2_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    increased_peep_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    worsening_oxygenation: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "on_mechanical_ventilation": self.on_mechanical_ventilation.value,
            "ventilator_mode": self.ventilator_mode,
            "intubation_date": self.intubation_date,
            "extubation_date": self.extubation_date,
            "increased_fio2_documented": self.increased_fio2_documented.value,
            "increased_peep_documented": self.increased_peep_documented.value,
            "worsening_oxygenation": self.worsening_oxygenation.value,
            "source": self.source.to_dict() if self.source else None,
        }


@dataclass
class VAEExtraction:
    """Complete extraction of VAE-relevant clinical information.

    This is what the LLM produces from clinical notes. The rules engine
    then combines this with structured EHR data to make a classification.

    The LLM is answering factual questions about:
    - Temperature and WBC findings
    - Antimicrobial treatments
    - Respiratory secretions
    - Respiratory culture results
    - Clinical team's impression

    The LLM is NOT making the classification decision.
    """
    # Temperature findings
    temperature: TemperatureExtraction = field(default_factory=TemperatureExtraction)

    # WBC findings
    wbc: WBCExtraction = field(default_factory=WBCExtraction)

    # Antimicrobial treatment
    antimicrobials: list[AntimicrobialExtraction] = field(default_factory=list)

    # Respiratory secretions
    secretions: RespiratorySecretionsExtraction = field(default_factory=RespiratorySecretionsExtraction)

    # Respiratory cultures
    cultures: list[RespiratoryCultureExtraction] = field(default_factory=list)

    # Ventilator status
    ventilator_status: VentilatorStatusExtraction = field(default_factory=VentilatorStatusExtraction)

    # Clinical team's impression
    clinical_team_impression: str | None = None
    vap_suspected_by_team: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    pneumonia_diagnosed: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    # Alternative diagnoses mentioned
    alternative_diagnoses: list[str] = field(default_factory=list)  # ARDS, aspiration, CHF, etc.

    # Extraction metadata
    documentation_quality: str = "adequate"  # poor, limited, adequate, detailed
    notes_reviewed_count: int = 0
    extraction_notes: str | None = None

    def to_dict(self) -> dict:
        return {
            "temperature": self.temperature.to_dict(),
            "wbc": self.wbc.to_dict(),
            "antimicrobials": [a.to_dict() for a in self.antimicrobials],
            "secretions": self.secretions.to_dict(),
            "cultures": [c.to_dict() for c in self.cultures],
            "ventilator_status": self.ventilator_status.to_dict(),
            "clinical_team_impression": self.clinical_team_impression,
            "vap_suspected_by_team": self.vap_suspected_by_team.value,
            "pneumonia_diagnosed": self.pneumonia_diagnosed.value,
            "alternative_diagnoses": self.alternative_diagnoses,
            "documentation_quality": self.documentation_quality,
            "notes_reviewed_count": self.notes_reviewed_count,
            "extraction_notes": self.extraction_notes,
        }


# ============================================================================
# Structured EHR Data - From FHIR/Clarity, not LLM
# ============================================================================

@dataclass
class DailyVentParameters:
    """Daily ventilator parameters for a patient.

    Used to detect VAC by identifying baseline period followed by worsening.
    """
    date: date
    min_fio2: float | None = None  # Minimum FiO2 for the day (%)
    min_peep: float | None = None  # Minimum PEEP for the day (cmH2O)
    fio2_source: str | None = None  # FHIR Observation ID
    peep_source: str | None = None

    def to_dict(self) -> dict:
        return {
            "date": self.date.isoformat(),
            "min_fio2": self.min_fio2,
            "min_peep": self.min_peep,
            "fio2_source": self.fio2_source,
            "peep_source": self.peep_source,
        }


@dataclass
class VAEStructuredData:
    """Structured data from EHR for VAE classification.

    This data comes from discrete fields in the EHR, not from
    clinical note text.
    """
    # Ventilation episode
    patient_id: str
    intubation_date: datetime
    extubation_date: datetime | None = None
    ventilator_days: int = 0

    # Daily ventilator parameters
    daily_parameters: list[DailyVentParameters] = field(default_factory=list)

    # VAC detection results (from candidate detector)
    vac_onset_date: date | None = None
    baseline_period_start: date | None = None
    baseline_period_end: date | None = None
    baseline_min_fio2: float | None = None
    baseline_min_peep: float | None = None
    worsening_start_date: date | None = None
    fio2_increase: float | None = None  # Percentage point increase
    peep_increase: float | None = None  # cmH2O increase

    # Lab data for IVAC
    temperatures: list[tuple[datetime, float]] = field(default_factory=list)  # (date, temp_celsius)
    wbc_values: list[tuple[datetime, float]] = field(default_factory=list)    # (date, wbc_count)

    # Antimicrobial data for IVAC
    qualifying_antimicrobials: list[dict] = field(default_factory=list)
    # Format: {"drug": str, "start_date": date, "days_on_drug": int, "route": str}

    # Culture data for VAP
    respiratory_cultures: list[dict] = field(default_factory=list)
    # Format: {"specimen_type": str, "organism": str, "count": int, "date": date}

    # Location information
    location_at_vac: str | None = None
    location_type: str | None = None  # ICU, Ward, etc.

    def to_dict(self) -> dict:
        return {
            "patient_id": self.patient_id,
            "intubation_date": self.intubation_date.isoformat(),
            "extubation_date": self.extubation_date.isoformat() if self.extubation_date else None,
            "ventilator_days": self.ventilator_days,
            "daily_parameters": [p.to_dict() for p in self.daily_parameters],
            "vac_onset_date": self.vac_onset_date.isoformat() if self.vac_onset_date else None,
            "baseline_period_start": self.baseline_period_start.isoformat() if self.baseline_period_start else None,
            "baseline_period_end": self.baseline_period_end.isoformat() if self.baseline_period_end else None,
            "baseline_min_fio2": self.baseline_min_fio2,
            "baseline_min_peep": self.baseline_min_peep,
            "worsening_start_date": self.worsening_start_date.isoformat() if self.worsening_start_date else None,
            "fio2_increase": self.fio2_increase,
            "peep_increase": self.peep_increase,
            "temperatures": [(t[0].isoformat(), t[1]) for t in self.temperatures],
            "wbc_values": [(w[0].isoformat(), w[1]) for w in self.wbc_values],
            "qualifying_antimicrobials": self.qualifying_antimicrobials,
            "respiratory_cultures": self.respiratory_cultures,
            "location_at_vac": self.location_at_vac,
            "location_type": self.location_type,
        }


# ============================================================================
# Rules Engine Output
# ============================================================================

@dataclass
class VAEClassificationResult:
    """Output of the VAE rules engine.

    This is the final classification with full audit trail of
    which rules were applied and why.
    """
    classification: VAEClassification
    vae_tier: VAETier | None  # Tier for NHSN reporting
    confidence: float  # 0.0 to 1.0
    reasoning: list[str]  # Step-by-step reasoning
    requires_review: bool
    review_reasons: list[str]

    # VAC detection details
    vac_met: bool = False
    vac_onset_date: date | None = None
    baseline_period: str | None = None  # e.g., "Days 3-4"
    worsening_period: str | None = None  # e.g., "Days 5-6"
    fio2_increase_details: str | None = None
    peep_increase_details: str | None = None

    # IVAC criteria details
    ivac_met: bool = False
    temperature_criterion_met: bool = False
    wbc_criterion_met: bool = False
    antimicrobial_criterion_met: bool = False
    qualifying_antimicrobials: list[str] = field(default_factory=list)

    # VAP criteria details
    vap_met: bool = False
    purulent_secretions_met: bool = False
    positive_culture_met: bool = False
    quantitative_threshold_met: bool = False
    organism_identified: str | None = None
    specimen_type: str | None = None

    def to_dict(self) -> dict:
        return {
            "classification": self.classification.value,
            "vae_tier": self.vae_tier.value if self.vae_tier else None,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "requires_review": self.requires_review,
            "review_reasons": self.review_reasons,
            "vac_met": self.vac_met,
            "vac_onset_date": self.vac_onset_date.isoformat() if self.vac_onset_date else None,
            "baseline_period": self.baseline_period,
            "worsening_period": self.worsening_period,
            "fio2_increase_details": self.fio2_increase_details,
            "peep_increase_details": self.peep_increase_details,
            "ivac_met": self.ivac_met,
            "temperature_criterion_met": self.temperature_criterion_met,
            "wbc_criterion_met": self.wbc_criterion_met,
            "antimicrobial_criterion_met": self.antimicrobial_criterion_met,
            "qualifying_antimicrobials": self.qualifying_antimicrobials,
            "vap_met": self.vap_met,
            "purulent_secretions_met": self.purulent_secretions_met,
            "positive_culture_met": self.positive_culture_met,
            "quantitative_threshold_met": self.quantitative_threshold_met,
            "organism_identified": self.organism_identified,
            "specimen_type": self.specimen_type,
        }
