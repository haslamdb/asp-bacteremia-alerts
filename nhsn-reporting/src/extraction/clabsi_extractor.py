"""CLABSI clinical information extractor.

This module uses an LLM to extract structured clinical information from
notes. The extraction is then passed to the rules engine for classification.

The key principle: The LLM extracts FACTS, the rules engine applies LOGIC.
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime

from ..config import Config
from ..models import HAICandidate, ClinicalNote, LLMAuditEntry
from ..llm.factory import get_llm_client
from ..notes.chunker import NoteChunker
from ..db import NHSNDatabase
from ..rules.schemas import (
    ClinicalExtraction,
    ConfidenceLevel,
    DocumentedInfectionSite,
    SymptomExtraction,
    MBIFactors,
    LineAssessment,
    ContaminationAssessment,
)

logger = logging.getLogger(__name__)


# JSON Schema for structured extraction output
EXTRACTION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "alternate_infection_sites": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "site": {"type": "string"},
                    "confidence": {
                        "type": "string",
                        "enum": ["definite", "probable", "possible", "not_found", "ruled_out"]
                    },
                    "same_organism_mentioned": {"type": ["boolean", "null"]},
                    "culture_from_site_positive": {"type": ["boolean", "null"]},
                    "supporting_quote": {"type": "string"},
                    "note_date": {"type": ["string", "null"]},
                },
                "required": ["site", "confidence", "supporting_quote"],
            },
        },
        "primary_diagnosis_if_stated": {"type": ["string", "null"]},
        "symptoms": {
            "type": "object",
            "properties": {
                "fever": {"type": "string"},
                "fever_value_celsius": {"type": ["number", "null"]},
                "hypothermia": {"type": "string"},
                "hypotension": {"type": "string"},
                "hypotension_requiring_pressors": {"type": "string"},
                "tachycardia": {"type": "string"},
                "leukocytosis": {"type": "string"},
                "leukocytosis_value": {"type": ["number", "null"]},
                "leukopenia": {"type": "string"},
                "bandemia": {"type": "string"},
                "bandemia_percentage": {"type": ["number", "null"]},
            },
        },
        "mbi_factors": {
            "type": "object",
            "properties": {
                "mucositis_documented": {"type": "string"},
                "mucositis_grade": {"type": ["integer", "null"]},
                "gi_gvhd_documented": {"type": "string"},
                "gi_gvhd_grade": {"type": ["integer", "null"]},
                "severe_diarrhea": {"type": "string"},
                "nec_documented": {"type": "string"},
                "neutropenia_documented": {"type": "string"},
                "anc_value": {"type": ["number", "null"]},
                "stem_cell_transplant": {"type": "string"},
                "transplant_type": {"type": ["string", "null"]},
                "days_post_transplant": {"type": ["integer", "null"]},
                "conditioning_regimen": {"type": ["string", "null"]},
                "recent_chemotherapy": {"type": "string"},
                "chemo_regimen": {"type": ["string", "null"]},
            },
        },
        "line_assessment": {
            "type": "object",
            "properties": {
                "line_infection_suspected": {"type": "string"},
                "line_removed_for_infection": {"type": "string"},
                "exit_site_erythema": {"type": "string"},
                "exit_site_purulence": {"type": "string"},
                "tunnel_infection": {"type": "string"},
                "catheter_tip_culture_positive": {"type": "string"},
                "catheter_tip_organism": {"type": ["string", "null"]},
                "line_dysfunction": {"type": "string"},
            },
        },
        "contamination": {
            "type": "object",
            "properties": {
                "treated_as_contaminant": {"type": "string"},
                "no_antibiotics_given": {"type": ["boolean", "null"]},
                "antibiotics_stopped_early": {"type": "string"},
                "documented_as_contaminant": {"type": "string"},
                "clinical_note_quote": {"type": ["string", "null"]},
            },
        },
        "clinical_context_summary": {"type": "string"},
        "clinical_team_impression": {"type": ["string", "null"]},
        "documentation_quality": {
            "type": "string",
            "enum": ["poor", "limited", "adequate", "detailed"],
        },
        "notes_reviewed_count": {"type": "integer"},
        "extraction_notes": {"type": ["string", "null"]},
    },
    "required": [
        "alternate_infection_sites",
        "symptoms",
        "mbi_factors",
        "line_assessment",
        "contamination",
        "clinical_context_summary",
        "documentation_quality",
        "notes_reviewed_count",
    ],
}


class CLABSIExtractor:
    """Extract CLABSI-relevant clinical information from notes using LLM.

    This class handles:
    1. Building the extraction prompt from notes and patient context
    2. Calling the LLM with structured output
    3. Parsing the response into ClinicalExtraction dataclass
    4. Audit logging of LLM calls

    The extraction is separate from classification - the rules engine
    takes the extraction output and applies NHSN criteria.
    """

    PROMPT_VERSION = "clabsi_extraction_v1"

    def __init__(
        self,
        llm_client=None,
        db: NHSNDatabase | None = None,
    ):
        """Initialize the extractor.

        Args:
            llm_client: LLM client instance. Uses factory default if None.
            db: Database for audit logging. Optional.
        """
        self._llm_client = llm_client
        self.db = db
        self.chunker = NoteChunker()
        self._prompt_template = self._load_prompt_template()

    @property
    def llm_client(self):
        """Lazy-load LLM client."""
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    def _load_prompt_template(self) -> str:
        """Load extraction prompt template from file."""
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "clabsi_extraction_v1.txt"
        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.warning(f"Prompt template not found: {prompt_path}")
            return self._default_prompt_template()

    def _default_prompt_template(self) -> str:
        """Fallback prompt if file not found."""
        return """Extract clinical information for CLABSI evaluation.

Patient: {patient_mrn}
Organism: {organism}
Central Line Days: {device_days}

Notes:
{clinical_notes}

Extract: alternate infection sources, symptoms, MBI factors, line assessment, contamination signals.
Respond with JSON matching the ClinicalExtraction schema."""

    def extract(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> ClinicalExtraction:
        """Extract clinical information from notes.

        Args:
            candidate: The CLABSI candidate with patient/culture info
            notes: Clinical notes to extract from

        Returns:
            ClinicalExtraction with structured extracted data
        """
        start_time = time.time()

        # Build prompt
        prompt = self._build_prompt(candidate, notes)

        try:
            # Call LLM with structured output
            result = self.llm_client.generate_structured(
                prompt=prompt,
                output_schema=EXTRACTION_OUTPUT_SCHEMA,
                temperature=0.0,  # Deterministic extraction
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            # Parse response into dataclass
            extraction = self._parse_response(result, len(notes))

            # Audit log
            if self.db:
                self._log_success(candidate, elapsed_ms)

            return extraction

        except Exception as e:
            logger.error(f"Extraction failed: {e}")
            elapsed_ms = int((time.time() - start_time) * 1000)

            if self.db:
                self._log_error(candidate, elapsed_ms, str(e))

            # Return minimal extraction on failure
            return ClinicalExtraction(
                clinical_context_summary=f"Extraction failed: {e}",
                documentation_quality="poor",
                notes_reviewed_count=len(notes),
                extraction_notes=f"LLM extraction error: {e}",
            )

    def _build_prompt(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> str:
        """Build the extraction prompt."""
        # Extract relevant context from notes
        notes_context = self.chunker.extract_relevant_context(notes)

        # Format prompt
        return self._prompt_template.format(
            patient_mrn=candidate.patient.mrn,
            culture_date=candidate.culture.collection_date.strftime("%Y-%m-%d"),
            organism=candidate.culture.organism or "Pending identification",
            device_type=candidate.device_info.device_type if candidate.device_info else "Unknown",
            device_days=candidate.device_days_at_culture or "Unknown",
            device_site=candidate.device_info.site if candidate.device_info else "Unknown",
            clinical_notes=notes_context or "No clinical notes available.",
        )

    def _parse_response(
        self,
        result: dict,
        notes_count: int,
    ) -> ClinicalExtraction:
        """Parse LLM response into ClinicalExtraction dataclass."""

        # Parse alternate infection sites
        alt_sites = []
        for site_data in result.get("alternate_infection_sites", []):
            try:
                alt_sites.append(DocumentedInfectionSite(
                    site=site_data.get("site", "unknown"),
                    confidence=self._parse_confidence(site_data.get("confidence")),
                    same_organism_mentioned=site_data.get("same_organism_mentioned"),
                    culture_from_site_positive=site_data.get("culture_from_site_positive"),
                    supporting_quote=site_data.get("supporting_quote", ""),
                    note_date=site_data.get("note_date"),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse alternate site: {e}")

        # Parse symptoms
        symptoms_data = result.get("symptoms", {})
        symptoms = SymptomExtraction(
            fever=self._parse_confidence(symptoms_data.get("fever")),
            fever_value_celsius=symptoms_data.get("fever_value_celsius"),
            hypothermia=self._parse_confidence(symptoms_data.get("hypothermia")),
            hypotension=self._parse_confidence(symptoms_data.get("hypotension")),
            hypotension_requiring_pressors=self._parse_confidence(
                symptoms_data.get("hypotension_requiring_pressors")
            ),
            tachycardia=self._parse_confidence(symptoms_data.get("tachycardia")),
            leukocytosis=self._parse_confidence(symptoms_data.get("leukocytosis")),
            leukocytosis_value=symptoms_data.get("leukocytosis_value"),
            leukopenia=self._parse_confidence(symptoms_data.get("leukopenia")),
            bandemia=self._parse_confidence(symptoms_data.get("bandemia")),
            bandemia_percentage=symptoms_data.get("bandemia_percentage"),
        )

        # Parse MBI factors
        mbi_data = result.get("mbi_factors", {})
        mbi_factors = MBIFactors(
            mucositis_documented=self._parse_confidence(mbi_data.get("mucositis_documented")),
            mucositis_grade=mbi_data.get("mucositis_grade"),
            gi_gvhd_documented=self._parse_confidence(mbi_data.get("gi_gvhd_documented")),
            gi_gvhd_grade=mbi_data.get("gi_gvhd_grade"),
            severe_diarrhea=self._parse_confidence(mbi_data.get("severe_diarrhea")),
            nec_documented=self._parse_confidence(mbi_data.get("nec_documented")),
            neutropenia_documented=self._parse_confidence(mbi_data.get("neutropenia_documented")),
            anc_value=mbi_data.get("anc_value"),
            stem_cell_transplant=self._parse_confidence(mbi_data.get("stem_cell_transplant")),
            transplant_type=mbi_data.get("transplant_type"),
            days_post_transplant=mbi_data.get("days_post_transplant"),
            conditioning_regimen=mbi_data.get("conditioning_regimen"),
            recent_chemotherapy=self._parse_confidence(mbi_data.get("recent_chemotherapy")),
            chemo_regimen=mbi_data.get("chemo_regimen"),
        )

        # Parse line assessment
        line_data = result.get("line_assessment", {})
        line_assessment = LineAssessment(
            line_infection_suspected=self._parse_confidence(line_data.get("line_infection_suspected")),
            line_removed_for_infection=self._parse_confidence(line_data.get("line_removed_for_infection")),
            exit_site_erythema=self._parse_confidence(line_data.get("exit_site_erythema")),
            exit_site_purulence=self._parse_confidence(line_data.get("exit_site_purulence")),
            tunnel_infection=self._parse_confidence(line_data.get("tunnel_infection")),
            catheter_tip_culture_positive=self._parse_confidence(
                line_data.get("catheter_tip_culture_positive")
            ),
            catheter_tip_organism=line_data.get("catheter_tip_organism"),
            line_dysfunction=self._parse_confidence(line_data.get("line_dysfunction")),
        )

        # Parse contamination
        contam_data = result.get("contamination", {})
        contamination = ContaminationAssessment(
            treated_as_contaminant=self._parse_confidence(contam_data.get("treated_as_contaminant")),
            no_antibiotics_given=contam_data.get("no_antibiotics_given"),
            antibiotics_stopped_early=self._parse_confidence(
                contam_data.get("antibiotics_stopped_early")
            ),
            documented_as_contaminant=self._parse_confidence(
                contam_data.get("documented_as_contaminant")
            ),
            clinical_note_quote=contam_data.get("clinical_note_quote"),
        )

        # Build final extraction
        return ClinicalExtraction(
            alternate_infection_sites=alt_sites,
            primary_diagnosis_if_stated=result.get("primary_diagnosis_if_stated"),
            symptoms=symptoms,
            mbi_factors=mbi_factors,
            line_assessment=line_assessment,
            contamination=contamination,
            clinical_context_summary=result.get("clinical_context_summary", ""),
            clinical_team_impression=result.get("clinical_team_impression"),
            documentation_quality=result.get("documentation_quality", "adequate"),
            notes_reviewed_count=result.get("notes_reviewed_count", notes_count),
            extraction_notes=result.get("extraction_notes"),
        )

    def _parse_confidence(self, value: str | None) -> ConfidenceLevel:
        """Parse confidence level string to enum."""
        if not value:
            return ConfidenceLevel.NOT_FOUND
        try:
            return ConfidenceLevel(value.lower())
        except ValueError:
            return ConfidenceLevel.NOT_FOUND

    def _log_success(self, candidate: HAICandidate, elapsed_ms: int) -> None:
        """Log successful extraction."""
        entry = LLMAuditEntry(
            candidate_id=candidate.id,
            model=self.llm_client.model_name,
            success=True,
            response_time_ms=elapsed_ms,
        )
        self.db.log_llm_call(entry)

    def _log_error(self, candidate: HAICandidate, elapsed_ms: int, error: str) -> None:
        """Log failed extraction."""
        entry = LLMAuditEntry(
            candidate_id=candidate.id,
            model=self.llm_client.model_name,
            success=False,
            response_time_ms=elapsed_ms,
            error_message=error,
        )
        self.db.log_llm_call(entry)


def extract_clinical_info(
    candidate: HAICandidate,
    notes: list[ClinicalNote],
    llm_client=None,
) -> ClinicalExtraction:
    """Convenience function for clinical extraction.

    Args:
        candidate: CLABSI candidate
        notes: Clinical notes
        llm_client: Optional LLM client

    Returns:
        ClinicalExtraction
    """
    extractor = CLABSIExtractor(llm_client=llm_client)
    return extractor.extract(candidate, notes)
