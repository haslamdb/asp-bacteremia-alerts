"""Schemas for NHSN rules engine.

This module defines:
- ClinicalExtraction: What the LLM extracts from clinical notes
- StructuredCaseData: Structured data from EHR (Clarity/FHIR)
- ClassificationResult: Output of the rules engine

The key principle: The LLM extracts *information*, the rules engine
applies *logic*. The LLM should never be asked to classify - only to
answer factual questions about what's documented.
"""

from dataclasses import dataclass, field
from datetime import datetime, date
from enum import Enum


class ConfidenceLevel(str, Enum):
    """How confidently something is documented in the notes.

    This is NOT the LLM's confidence in its extraction - it's a description
    of how explicitly something is stated in the documentation.
    """
    DEFINITE = "definite"       # Explicitly documented, unambiguous
    PROBABLE = "probable"       # Strongly implied or likely based on context
    POSSIBLE = "possible"       # Mentioned but uncertain/equivocal
    NOT_FOUND = "not_found"     # Not mentioned in documentation
    RULED_OUT = "ruled_out"     # Explicitly excluded/ruled out


@dataclass
class EvidenceSource:
    """Source attribution for an extracted finding.

    Helps IP reviewers track down the evidence in the medical record.
    Format when displayed: "Progress Note 01/14/2026: David Haslam, MD"
    """
    note_type: str  # Progress Note, ID Consult, Discharge Summary, etc.
    note_date: str  # YYYY-MM-DD
    author: str | None = None  # Name and credentials if available

    def __str__(self) -> str:
        """Format for display."""
        base = f"{self.note_type} {self.note_date}"
        if self.author:
            base += f": {self.author}"
        return base

    def to_dict(self) -> dict:
        return {
            "note_type": self.note_type,
            "note_date": self.note_date,
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, data: dict | str | None) -> "EvidenceSource | None":
        if data is None:
            return None
        if isinstance(data, str):
            # Handle legacy string format
            return cls(note_type="Note", note_date="", author=data)
        return cls(
            note_type=data.get("note_type", "Note"),
            note_date=data.get("note_date", ""),
            author=data.get("author"),
        )


class CLABSIClassification(str, Enum):
    """Final classification from the rules engine."""
    CLABSI = "clabsi"                     # Central line-associated BSI
    MBI_LCBI = "mbi_lcbi"                 # Mucosal barrier injury LCBI
    SECONDARY_BSI = "secondary_bsi"       # BSI secondary to another site
    CONTAMINATION = "contamination"       # Likely contamination
    NOT_ELIGIBLE = "not_eligible"         # Doesn't meet basic eligibility
    INDETERMINATE = "indeterminate"       # Insufficient info to classify


# ============================================================================
# LLM Extraction Schemas - What the LLM produces
# ============================================================================

@dataclass
class DocumentedInfectionSite:
    """An infection site mentioned in clinical documentation.

    The LLM identifies mentions of other infections that could be
    the source of bacteremia (pneumonia, UTI, SSTI, etc).
    """
    site: str  # pneumonia, uti, ssti, intra_abdominal, osteomyelitis, etc.
    confidence: ConfidenceLevel
    same_organism_mentioned: bool | None  # True if notes say same bug
    culture_from_site_positive: bool | None  # True if site culture positive
    supporting_quote: str  # Direct quote from documentation
    source: EvidenceSource | None = None  # Source attribution for this finding

    def to_dict(self) -> dict:
        return {
            "site": self.site,
            "confidence": self.confidence.value,
            "same_organism_mentioned": self.same_organism_mentioned,
            "culture_from_site_positive": self.culture_from_site_positive,
            "supporting_quote": self.supporting_quote,
            "source": self.source.to_dict() if self.source else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "DocumentedInfectionSite":
        # Handle legacy note_date field
        source_data = data.get("source")
        if source_data is None and data.get("note_date"):
            source_data = {"note_type": "Note", "note_date": data.get("note_date")}
        return cls(
            site=data.get("site", "unknown"),
            confidence=ConfidenceLevel(data.get("confidence", "not_found")),
            same_organism_mentioned=data.get("same_organism_mentioned"),
            culture_from_site_positive=data.get("culture_from_site_positive"),
            supporting_quote=data.get("supporting_quote", ""),
            source=EvidenceSource.from_dict(source_data),
        )


@dataclass
class SymptomExtraction:
    """Symptoms relevant to BSI/SIRS criteria.

    Extracted from vital signs and clinical documentation.
    These help establish whether the patient has clinical signs
    of infection.
    """
    fever: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    fever_value_celsius: float | None = None
    hypothermia: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    hypotension: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    hypotension_requiring_pressors: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    tachycardia: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    leukocytosis: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    leukocytosis_value: float | None = None  # WBC count
    leukopenia: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    bandemia: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    bandemia_percentage: float | None = None

    def to_dict(self) -> dict:
        return {
            "fever": self.fever.value,
            "fever_value_celsius": self.fever_value_celsius,
            "hypothermia": self.hypothermia.value,
            "hypotension": self.hypotension.value,
            "hypotension_requiring_pressors": self.hypotension_requiring_pressors.value,
            "tachycardia": self.tachycardia.value,
            "leukocytosis": self.leukocytosis.value,
            "leukocytosis_value": self.leukocytosis_value,
            "leukopenia": self.leukopenia.value,
            "bandemia": self.bandemia.value,
            "bandemia_percentage": self.bandemia_percentage,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SymptomExtraction":
        return cls(
            fever=ConfidenceLevel(data.get("fever", "not_found")),
            fever_value_celsius=data.get("fever_value_celsius"),
            hypothermia=ConfidenceLevel(data.get("hypothermia", "not_found")),
            hypotension=ConfidenceLevel(data.get("hypotension", "not_found")),
            hypotension_requiring_pressors=ConfidenceLevel(
                data.get("hypotension_requiring_pressors", "not_found")
            ),
            tachycardia=ConfidenceLevel(data.get("tachycardia", "not_found")),
            leukocytosis=ConfidenceLevel(data.get("leukocytosis", "not_found")),
            leukocytosis_value=data.get("leukocytosis_value"),
            leukopenia=ConfidenceLevel(data.get("leukopenia", "not_found")),
            bandemia=ConfidenceLevel(data.get("bandemia", "not_found")),
            bandemia_percentage=data.get("bandemia_percentage"),
        )


@dataclass
class MBIFactors:
    """Mucosal barrier injury relevant findings.

    These are critical for distinguishing MBI-LCBI from CLABSI
    in immunocompromised patients.
    """
    # Mucosal injury indicators
    mucositis_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    mucositis_grade: int | None = None  # Grade 1-4 if documented
    mucositis_source: EvidenceSource | None = None
    gi_gvhd_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    gi_gvhd_grade: int | None = None
    gi_gvhd_source: EvidenceSource | None = None
    severe_diarrhea: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    severe_diarrhea_source: EvidenceSource | None = None
    nec_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND  # Necrotizing enterocolitis
    nec_source: EvidenceSource | None = None

    # Immunocompromised status
    neutropenia_documented: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    anc_value: float | None = None  # Most recent ANC if documented
    neutropenia_source: EvidenceSource | None = None

    # Transplant status
    stem_cell_transplant: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    transplant_type: str | None = None  # "allogeneic", "autologous"
    days_post_transplant: int | None = None
    conditioning_regimen: str | None = None  # If mentioned
    transplant_source: EvidenceSource | None = None

    # Chemotherapy
    recent_chemotherapy: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    chemo_regimen: str | None = None
    chemotherapy_source: EvidenceSource | None = None

    def to_dict(self) -> dict:
        return {
            "mucositis_documented": self.mucositis_documented.value,
            "mucositis_grade": self.mucositis_grade,
            "mucositis_source": self.mucositis_source.to_dict() if self.mucositis_source else None,
            "gi_gvhd_documented": self.gi_gvhd_documented.value,
            "gi_gvhd_grade": self.gi_gvhd_grade,
            "gi_gvhd_source": self.gi_gvhd_source.to_dict() if self.gi_gvhd_source else None,
            "severe_diarrhea": self.severe_diarrhea.value,
            "severe_diarrhea_source": self.severe_diarrhea_source.to_dict() if self.severe_diarrhea_source else None,
            "nec_documented": self.nec_documented.value,
            "nec_source": self.nec_source.to_dict() if self.nec_source else None,
            "neutropenia_documented": self.neutropenia_documented.value,
            "anc_value": self.anc_value,
            "neutropenia_source": self.neutropenia_source.to_dict() if self.neutropenia_source else None,
            "stem_cell_transplant": self.stem_cell_transplant.value,
            "transplant_type": self.transplant_type,
            "days_post_transplant": self.days_post_transplant,
            "conditioning_regimen": self.conditioning_regimen,
            "transplant_source": self.transplant_source.to_dict() if self.transplant_source else None,
            "recent_chemotherapy": self.recent_chemotherapy.value,
            "chemo_regimen": self.chemo_regimen,
            "chemotherapy_source": self.chemotherapy_source.to_dict() if self.chemotherapy_source else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MBIFactors":
        return cls(
            mucositis_documented=ConfidenceLevel(data.get("mucositis_documented", "not_found")),
            mucositis_grade=data.get("mucositis_grade"),
            mucositis_source=EvidenceSource.from_dict(data.get("mucositis_source")),
            gi_gvhd_documented=ConfidenceLevel(data.get("gi_gvhd_documented", "not_found")),
            gi_gvhd_grade=data.get("gi_gvhd_grade"),
            gi_gvhd_source=EvidenceSource.from_dict(data.get("gi_gvhd_source")),
            severe_diarrhea=ConfidenceLevel(data.get("severe_diarrhea", "not_found")),
            severe_diarrhea_source=EvidenceSource.from_dict(data.get("severe_diarrhea_source")),
            nec_documented=ConfidenceLevel(data.get("nec_documented", "not_found")),
            nec_source=EvidenceSource.from_dict(data.get("nec_source")),
            neutropenia_documented=ConfidenceLevel(data.get("neutropenia_documented", "not_found")),
            anc_value=data.get("anc_value"),
            neutropenia_source=EvidenceSource.from_dict(data.get("neutropenia_source")),
            stem_cell_transplant=ConfidenceLevel(data.get("stem_cell_transplant", "not_found")),
            transplant_type=data.get("transplant_type"),
            days_post_transplant=data.get("days_post_transplant"),
            conditioning_regimen=data.get("conditioning_regimen"),
            transplant_source=EvidenceSource.from_dict(data.get("transplant_source")),
            recent_chemotherapy=ConfidenceLevel(data.get("recent_chemotherapy", "not_found")),
            chemo_regimen=data.get("chemo_regimen"),
            chemotherapy_source=EvidenceSource.from_dict(data.get("chemotherapy_source")),
        )


@dataclass
class LineAssessment:
    """Line-related findings from clinical notes.

    Captures what the clinical team documents about the central line
    and any suspected line complications.
    """
    line_infection_suspected: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    line_infection_suspected_source: EvidenceSource | None = None
    line_removed_for_infection: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    line_removed_source: EvidenceSource | None = None
    exit_site_erythema: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    exit_site_purulence: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    exit_site_source: EvidenceSource | None = None  # Source for exit site findings
    tunnel_infection: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    tunnel_infection_source: EvidenceSource | None = None
    catheter_tip_culture_positive: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    catheter_tip_organism: str | None = None
    catheter_tip_source: EvidenceSource | None = None
    line_dysfunction: ConfidenceLevel = ConfidenceLevel.NOT_FOUND

    def to_dict(self) -> dict:
        return {
            "line_infection_suspected": self.line_infection_suspected.value,
            "line_infection_suspected_source": self.line_infection_suspected_source.to_dict() if self.line_infection_suspected_source else None,
            "line_removed_for_infection": self.line_removed_for_infection.value,
            "line_removed_source": self.line_removed_source.to_dict() if self.line_removed_source else None,
            "exit_site_erythema": self.exit_site_erythema.value,
            "exit_site_purulence": self.exit_site_purulence.value,
            "exit_site_source": self.exit_site_source.to_dict() if self.exit_site_source else None,
            "tunnel_infection": self.tunnel_infection.value,
            "tunnel_infection_source": self.tunnel_infection_source.to_dict() if self.tunnel_infection_source else None,
            "catheter_tip_culture_positive": self.catheter_tip_culture_positive.value,
            "catheter_tip_organism": self.catheter_tip_organism,
            "catheter_tip_source": self.catheter_tip_source.to_dict() if self.catheter_tip_source else None,
            "line_dysfunction": self.line_dysfunction.value,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "LineAssessment":
        return cls(
            line_infection_suspected=ConfidenceLevel(data.get("line_infection_suspected", "not_found")),
            line_infection_suspected_source=EvidenceSource.from_dict(data.get("line_infection_suspected_source")),
            line_removed_for_infection=ConfidenceLevel(data.get("line_removed_for_infection", "not_found")),
            line_removed_source=EvidenceSource.from_dict(data.get("line_removed_source")),
            exit_site_erythema=ConfidenceLevel(data.get("exit_site_erythema", "not_found")),
            exit_site_purulence=ConfidenceLevel(data.get("exit_site_purulence", "not_found")),
            exit_site_source=EvidenceSource.from_dict(data.get("exit_site_source")),
            tunnel_infection=ConfidenceLevel(data.get("tunnel_infection", "not_found")),
            tunnel_infection_source=EvidenceSource.from_dict(data.get("tunnel_infection_source")),
            catheter_tip_culture_positive=ConfidenceLevel(data.get("catheter_tip_culture_positive", "not_found")),
            catheter_tip_organism=data.get("catheter_tip_organism"),
            catheter_tip_source=EvidenceSource.from_dict(data.get("catheter_tip_source")),
            line_dysfunction=ConfidenceLevel(data.get("line_dysfunction", "not_found")),
        )


@dataclass
class ContaminationAssessment:
    """Signals that clinicians may have considered this contamination.

    Important for distinguishing true bacteremia from contamination,
    especially with skin flora organisms.
    """
    treated_as_contaminant: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    no_antibiotics_given: bool | None = None
    antibiotics_stopped_early: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    documented_as_contaminant: ConfidenceLevel = ConfidenceLevel.NOT_FOUND
    clinical_note_quote: str | None = None
    source: EvidenceSource | None = None  # Source for contamination documentation

    def to_dict(self) -> dict:
        return {
            "treated_as_contaminant": self.treated_as_contaminant.value,
            "no_antibiotics_given": self.no_antibiotics_given,
            "antibiotics_stopped_early": self.antibiotics_stopped_early.value,
            "documented_as_contaminant": self.documented_as_contaminant.value,
            "clinical_note_quote": self.clinical_note_quote,
            "source": self.source.to_dict() if self.source else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ContaminationAssessment":
        return cls(
            treated_as_contaminant=ConfidenceLevel(data.get("treated_as_contaminant", "not_found")),
            no_antibiotics_given=data.get("no_antibiotics_given"),
            antibiotics_stopped_early=ConfidenceLevel(data.get("antibiotics_stopped_early", "not_found")),
            documented_as_contaminant=ConfidenceLevel(data.get("documented_as_contaminant", "not_found")),
            clinical_note_quote=data.get("clinical_note_quote"),
            source=EvidenceSource.from_dict(data.get("source")),
        )


@dataclass
class ClinicalExtraction:
    """Complete extraction of CLABSI-relevant clinical information.

    This is what the LLM produces from clinical notes. The rules engine
    then combines this with structured EHR data to make a classification.

    The LLM is answering factual questions:
    - Is an alternate infection source documented?
    - What symptoms are mentioned?
    - Is there evidence of mucosal barrier injury?
    - What does the clinical team say about the line?

    The LLM is NOT making the classification decision.
    """
    # Alternate infection sources identified in notes
    alternate_infection_sites: list[DocumentedInfectionSite] = field(default_factory=list)
    primary_diagnosis_if_stated: str | None = None

    # Symptom documentation
    symptoms: SymptomExtraction = field(default_factory=SymptomExtraction)

    # MBI-LCBI relevant factors
    mbi_factors: MBIFactors = field(default_factory=MBIFactors)

    # Line-specific findings
    line_assessment: LineAssessment = field(default_factory=LineAssessment)

    # Contamination signals
    contamination: ContaminationAssessment = field(default_factory=ContaminationAssessment)

    # Clinical context
    clinical_context_summary: str = ""
    clinical_team_impression: str | None = None  # What the team thinks is happening

    # Extraction metadata
    documentation_quality: str = "adequate"  # poor, limited, adequate, detailed
    notes_reviewed_count: int = 0
    extraction_notes: str | None = None  # Any extraction issues or observations

    def to_dict(self) -> dict:
        return {
            "alternate_infection_sites": [s.to_dict() for s in self.alternate_infection_sites],
            "primary_diagnosis_if_stated": self.primary_diagnosis_if_stated,
            "symptoms": self.symptoms.to_dict(),
            "mbi_factors": self.mbi_factors.to_dict(),
            "line_assessment": self.line_assessment.to_dict(),
            "contamination": self.contamination.to_dict(),
            "clinical_context_summary": self.clinical_context_summary,
            "clinical_team_impression": self.clinical_team_impression,
            "documentation_quality": self.documentation_quality,
            "notes_reviewed_count": self.notes_reviewed_count,
            "extraction_notes": self.extraction_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ClinicalExtraction":
        alt_sites = [
            DocumentedInfectionSite.from_dict(s)
            for s in data.get("alternate_infection_sites", [])
        ]
        return cls(
            alternate_infection_sites=alt_sites,
            primary_diagnosis_if_stated=data.get("primary_diagnosis_if_stated"),
            symptoms=SymptomExtraction.from_dict(data.get("symptoms", {})),
            mbi_factors=MBIFactors.from_dict(data.get("mbi_factors", {})),
            line_assessment=LineAssessment.from_dict(data.get("line_assessment", {})),
            contamination=ContaminationAssessment.from_dict(data.get("contamination", {})),
            clinical_context_summary=data.get("clinical_context_summary", ""),
            clinical_team_impression=data.get("clinical_team_impression"),
            documentation_quality=data.get("documentation_quality", "adequate"),
            notes_reviewed_count=data.get("notes_reviewed_count", 0),
            extraction_notes=data.get("extraction_notes"),
        )


# ============================================================================
# Structured EHR Data - From Clarity/FHIR, not LLM
# ============================================================================

@dataclass
class StructuredCaseData:
    """Structured data from EHR (Clarity/FHIR).

    This data comes from discrete fields in the EHR, not from
    clinical note text. It's authoritative for timing and lab values.
    """
    # Culture information
    organism: str
    culture_date: datetime
    specimen_source: str = "blood"

    # Central line information
    line_present: bool = False
    line_type: str | None = None  # CVC, PICC, tunneled, port
    line_insertion_date: datetime | None = None
    line_removal_date: datetime | None = None
    line_days_at_culture: int | None = None

    # For commensals - need two matching cultures
    has_second_culture_match: bool = False
    second_culture_date: datetime | None = None

    # Admission information
    admission_date: datetime | None = None
    patient_days_at_culture: int | None = None
    location_at_culture: str | None = None  # NHSN location code
    location_type: str | None = None  # ICU, Ward, NICU, etc.

    # Lab values (structured, not from notes)
    anc_values_7_days: list[float] = field(default_factory=list)  # ANC values in 7 days before culture
    wbc_at_culture: float | None = None

    # Transplant registry data (if available)
    is_transplant_patient: bool = False
    transplant_date: datetime | None = None
    transplant_type: str | None = None  # allogeneic, autologous

    # Other cultures from other sites
    matching_organism_other_sites: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "organism": self.organism,
            "culture_date": self.culture_date.isoformat(),
            "specimen_source": self.specimen_source,
            "line_present": self.line_present,
            "line_type": self.line_type,
            "line_insertion_date": self.line_insertion_date.isoformat() if self.line_insertion_date else None,
            "line_removal_date": self.line_removal_date.isoformat() if self.line_removal_date else None,
            "line_days_at_culture": self.line_days_at_culture,
            "has_second_culture_match": self.has_second_culture_match,
            "second_culture_date": self.second_culture_date.isoformat() if self.second_culture_date else None,
            "admission_date": self.admission_date.isoformat() if self.admission_date else None,
            "patient_days_at_culture": self.patient_days_at_culture,
            "location_at_culture": self.location_at_culture,
            "location_type": self.location_type,
            "anc_values_7_days": self.anc_values_7_days,
            "wbc_at_culture": self.wbc_at_culture,
            "is_transplant_patient": self.is_transplant_patient,
            "transplant_date": self.transplant_date.isoformat() if self.transplant_date else None,
            "transplant_type": self.transplant_type,
            "matching_organism_other_sites": self.matching_organism_other_sites,
        }


# ============================================================================
# Rules Engine Output
# ============================================================================

@dataclass
class ClassificationResult:
    """Output of the CLABSI rules engine.

    This is the final classification with full audit trail of
    which rules were applied and why.
    """
    classification: CLABSIClassification
    confidence: float  # 0.0 to 1.0
    reasoning: list[str]  # Step-by-step reasoning
    requires_review: bool
    review_reasons: list[str]

    # Rule application details
    eligibility_checks: list[str] = field(default_factory=list)
    exclusion_criteria_checked: list[str] = field(default_factory=list)
    mbi_lcbi_evaluation: str | None = None
    secondary_bsi_evaluation: str | None = None

    def to_dict(self) -> dict:
        return {
            "classification": self.classification.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "requires_review": self.requires_review,
            "review_reasons": self.review_reasons,
            "eligibility_checks": self.eligibility_checks,
            "exclusion_criteria_checked": self.exclusion_criteria_checked,
            "mbi_lcbi_evaluation": self.mbi_lcbi_evaluation,
            "secondary_bsi_evaluation": self.secondary_bsi_evaluation,
        }
