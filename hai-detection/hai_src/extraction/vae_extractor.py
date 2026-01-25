"""VAE clinical information extractor.

This module uses an LLM to extract structured clinical information from
notes for VAE (Ventilator-Associated Event) evaluation. The extraction is
then passed to the rules engine for IVAC/VAP classification.

The key principle: The LLM extracts FACTS, the rules engine applies LOGIC.

VAE Hierarchy:
- VAC: Detected by candidate detector (FiO2/PEEP worsening)
- IVAC: VAC + fever/WBC + new antimicrobials ≥4 days
- Possible VAP: IVAC + purulent secretions OR positive culture
- Probable VAP: IVAC + purulent secretions + positive quantitative culture
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime

from ..config import Config
from ..models import HAICandidate, ClinicalNote, LLMAuditEntry, VAECandidate
from ..llm.factory import get_llm_client
from ..notes.chunker import NoteChunker
from ..db import HAIDatabase
from ..rules.schemas import ConfidenceLevel, EvidenceSource
from ..rules.vae_schemas import (
    VAEExtraction,
    TemperatureExtraction,
    WBCExtraction,
    AntimicrobialExtraction,
    RespiratorySecretionsExtraction,
    RespiratoryCultureExtraction,
    VentilatorStatusExtraction,
)

logger = logging.getLogger(__name__)


# Reusable schema for evidence source attribution
EVIDENCE_SOURCE_SCHEMA = {
    "type": ["object", "null"],
    "properties": {
        "note_type": {"type": "string"},
        "note_date": {"type": "string"},
        "author": {"type": ["string", "null"]},
    },
    "required": ["note_type", "note_date"],
}

# JSON Schema for VAE extraction output
VAE_EXTRACTION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "temperature": {
            "type": "object",
            "properties": {
                "fever_documented": {"type": "string"},
                "max_temp_celsius": {"type": ["number", "null"]},
                "fever_date": {"type": ["string", "null"]},
                "fever_source": EVIDENCE_SOURCE_SCHEMA,
                "hypothermia_documented": {"type": "string"},
                "min_temp_celsius": {"type": ["number", "null"]},
                "hypothermia_date": {"type": ["string", "null"]},
                "hypothermia_source": EVIDENCE_SOURCE_SCHEMA,
            },
        },
        "wbc": {
            "type": "object",
            "properties": {
                "leukocytosis_documented": {"type": "string"},
                "max_wbc": {"type": ["number", "null"]},
                "leukocytosis_date": {"type": ["string", "null"]},
                "leukocytosis_source": EVIDENCE_SOURCE_SCHEMA,
                "leukopenia_documented": {"type": "string"},
                "min_wbc": {"type": ["number", "null"]},
                "leukopenia_date": {"type": ["string", "null"]},
                "leukopenia_source": EVIDENCE_SOURCE_SCHEMA,
            },
        },
        "antimicrobials": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "new_antimicrobial_started": {"type": "string"},
                    "antimicrobial_names": {"type": "array", "items": {"type": "string"}},
                    "start_date": {"type": ["string", "null"]},
                    "route": {"type": ["string", "null"]},
                    "indication": {"type": ["string", "null"]},
                    "duration_days": {"type": ["integer", "null"]},
                    "source": EVIDENCE_SOURCE_SCHEMA,
                    "continued_four_or_more_days": {"type": "string"},
                },
            },
        },
        "secretions": {
            "type": "object",
            "properties": {
                "purulent_secretions": {"type": "string"},
                "secretion_description": {"type": ["string", "null"]},
                "secretion_date": {"type": ["string", "null"]},
                "source": EVIDENCE_SOURCE_SCHEMA,
                "gram_stain_positive": {"type": "string"},
                "pmn_count": {"type": ["integer", "null"]},
                "epithelial_count": {"type": ["integer", "null"]},
            },
        },
        "cultures": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "culture_positive": {"type": "string"},
                    "specimen_type": {"type": ["string", "null"]},
                    "organism_identified": {"type": ["string", "null"]},
                    "colony_count": {"type": ["string", "null"]},
                    "collection_date": {"type": ["string", "null"]},
                    "source": EVIDENCE_SOURCE_SCHEMA,
                    "meets_quantitative_threshold": {"type": "string"},
                },
            },
        },
        "ventilator_status": {
            "type": "object",
            "properties": {
                "on_mechanical_ventilation": {"type": "string"},
                "ventilator_mode": {"type": ["string", "null"]},
                "intubation_date": {"type": ["string", "null"]},
                "extubation_date": {"type": ["string", "null"]},
                "increased_fio2_documented": {"type": "string"},
                "increased_peep_documented": {"type": "string"},
                "worsening_oxygenation": {"type": "string"},
                "source": EVIDENCE_SOURCE_SCHEMA,
            },
        },
        "clinical_team_impression": {"type": ["string", "null"]},
        "vap_suspected_by_team": {"type": "string"},
        "pneumonia_diagnosed": {"type": "string"},
        "alternative_diagnoses": {"type": "array", "items": {"type": "string"}},
        "documentation_quality": {
            "type": "string",
            "enum": ["poor", "limited", "adequate", "detailed"],
        },
        "notes_reviewed_count": {"type": "integer"},
        "extraction_notes": {"type": ["string", "null"]},
    },
    "required": [
        "temperature",
        "wbc",
        "antimicrobials",
        "secretions",
        "cultures",
        "ventilator_status",
        "documentation_quality",
        "notes_reviewed_count",
    ],
}


class VAEExtractor:
    """Extract VAE-relevant clinical information from notes using LLM.

    This class handles:
    1. Building the extraction prompt from notes and VAE context
    2. Calling the LLM with structured output
    3. Parsing the response into VAEExtraction dataclass
    4. Audit logging of LLM calls

    The extraction is separate from classification - the rules engine
    takes the extraction output and applies NHSN IVAC/VAP criteria.
    """

    PROMPT_VERSION = "vae_extraction_v1"

    def __init__(
        self,
        llm_client=None,
        db: HAIDatabase | None = None,
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
        prompt_path = (
            Path(__file__).parent.parent.parent / "prompts" / "vae_extraction_v1.txt"
        )
        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.warning(f"Prompt template not found: {prompt_path}")
            return self._default_prompt_template()

    def _default_prompt_template(self) -> str:
        """Fallback prompt if file not found."""
        return """Extract clinical information for VAE evaluation.

Patient: {patient_mrn}
VAC Onset Date: {vac_onset_date}
Ventilator Day: {ventilator_day}
Intubation Date: {intubation_date}

Notes:
{clinical_notes}

Extract: temperature, WBC, antimicrobials, secretions, cultures, ventilator status.
Respond with JSON matching the VAEExtraction schema."""

    def extract(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        vae_data: VAECandidate | None = None,
    ) -> VAEExtraction:
        """Extract VAE-relevant clinical information from notes.

        Args:
            candidate: The VAE candidate with patient info
            notes: Clinical notes to extract from
            vae_data: VAE-specific data (optional, may be in candidate)

        Returns:
            VAEExtraction with structured extracted data
        """
        start_time = time.time()

        # Get VAE data from candidate if not provided
        if vae_data is None:
            vae_data = getattr(candidate, "_vae_data", None)

        if vae_data is None:
            logger.warning(f"No VAE data for candidate {candidate.id}")
            return VAEExtraction(
                clinical_team_impression="No VAE data available",
                documentation_quality="poor",
                notes_reviewed_count=len(notes),
                extraction_notes="Missing VAE information",
            )

        # Build prompt
        prompt = self._build_prompt(candidate, notes, vae_data)

        try:
            # Call LLM with structured output
            result = self.llm_client.generate_structured(
                prompt=prompt,
                output_schema=VAE_EXTRACTION_OUTPUT_SCHEMA,
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
            logger.error(f"VAE extraction failed: {e}")
            elapsed_ms = int((time.time() - start_time) * 1000)

            if self.db:
                self._log_error(candidate, elapsed_ms, str(e))

            # Return minimal extraction on failure
            return VAEExtraction(
                clinical_team_impression=f"Extraction failed: {e}",
                documentation_quality="poor",
                notes_reviewed_count=len(notes),
                extraction_notes=f"LLM extraction error: {e}",
            )

    def _build_prompt(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        vae_data: VAECandidate,
    ) -> str:
        """Build the extraction prompt."""
        # Extract relevant context from notes
        notes_context = self.chunker.extract_relevant_context(notes)

        # Get VAE-specific context
        vac_onset_date = vae_data.vac_onset_date.strftime("%Y-%m-%d") if vae_data.vac_onset_date else "Unknown"
        intubation_date = vae_data.episode.intubation_date.strftime("%Y-%m-%d") if vae_data.episode else "Unknown"
        location = vae_data.episode.location_code if vae_data.episode else "Unknown"

        # Format prompt
        return self._prompt_template.format(
            patient_mrn=candidate.patient.mrn,
            vac_onset_date=vac_onset_date,
            ventilator_day=vae_data.ventilator_day_at_onset,
            intubation_date=intubation_date,
            location=location or "Unknown",
            clinical_notes=notes_context or "No clinical notes available.",
        )

    def _parse_response(
        self,
        result: dict,
        notes_count: int,
    ) -> VAEExtraction:
        """Parse LLM response into VAEExtraction dataclass."""

        # Parse temperature findings
        temp_data = result.get("temperature", {})
        temperature = TemperatureExtraction(
            fever_documented=self._parse_confidence(temp_data.get("fever_documented")),
            max_temp_celsius=temp_data.get("max_temp_celsius"),
            fever_date=temp_data.get("fever_date"),
            fever_source=EvidenceSource.from_dict(temp_data.get("fever_source")),
            hypothermia_documented=self._parse_confidence(temp_data.get("hypothermia_documented")),
            min_temp_celsius=temp_data.get("min_temp_celsius"),
            hypothermia_date=temp_data.get("hypothermia_date"),
            hypothermia_source=EvidenceSource.from_dict(temp_data.get("hypothermia_source")),
        )

        # Parse WBC findings
        wbc_data = result.get("wbc", {})
        wbc = WBCExtraction(
            leukocytosis_documented=self._parse_confidence(wbc_data.get("leukocytosis_documented")),
            max_wbc=wbc_data.get("max_wbc"),
            leukocytosis_date=wbc_data.get("leukocytosis_date"),
            leukocytosis_source=EvidenceSource.from_dict(wbc_data.get("leukocytosis_source")),
            leukopenia_documented=self._parse_confidence(wbc_data.get("leukopenia_documented")),
            min_wbc=wbc_data.get("min_wbc"),
            leukopenia_date=wbc_data.get("leukopenia_date"),
            leukopenia_source=EvidenceSource.from_dict(wbc_data.get("leukopenia_source")),
        )

        # Parse antimicrobials
        antimicrobials = []
        for abx_data in result.get("antimicrobials", []):
            try:
                antimicrobials.append(AntimicrobialExtraction(
                    new_antimicrobial_started=self._parse_confidence(abx_data.get("new_antimicrobial_started")),
                    antimicrobial_names=abx_data.get("antimicrobial_names", []),
                    start_date=abx_data.get("start_date"),
                    route=abx_data.get("route"),
                    indication=abx_data.get("indication"),
                    duration_days=abx_data.get("duration_days"),
                    source=EvidenceSource.from_dict(abx_data.get("source")),
                    continued_four_or_more_days=self._parse_confidence(abx_data.get("continued_four_or_more_days")),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse antimicrobial: {e}")

        # Parse secretions
        sec_data = result.get("secretions", {})
        secretions = RespiratorySecretionsExtraction(
            purulent_secretions=self._parse_confidence(sec_data.get("purulent_secretions")),
            secretion_description=sec_data.get("secretion_description"),
            secretion_date=sec_data.get("secretion_date"),
            source=EvidenceSource.from_dict(sec_data.get("source")),
            gram_stain_positive=self._parse_confidence(sec_data.get("gram_stain_positive")),
            pmn_count=sec_data.get("pmn_count"),
            epithelial_count=sec_data.get("epithelial_count"),
        )

        # Parse cultures
        cultures = []
        for cx_data in result.get("cultures", []):
            try:
                cultures.append(RespiratoryCultureExtraction(
                    culture_positive=self._parse_confidence(cx_data.get("culture_positive")),
                    specimen_type=cx_data.get("specimen_type"),
                    organism_identified=cx_data.get("organism_identified"),
                    colony_count=cx_data.get("colony_count"),
                    collection_date=cx_data.get("collection_date"),
                    source=EvidenceSource.from_dict(cx_data.get("source")),
                    meets_quantitative_threshold=self._parse_confidence(cx_data.get("meets_quantitative_threshold")),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse culture: {e}")

        # Parse ventilator status
        vent_data = result.get("ventilator_status", {})
        ventilator_status = VentilatorStatusExtraction(
            on_mechanical_ventilation=self._parse_confidence(vent_data.get("on_mechanical_ventilation")),
            ventilator_mode=vent_data.get("ventilator_mode"),
            intubation_date=vent_data.get("intubation_date"),
            extubation_date=vent_data.get("extubation_date"),
            increased_fio2_documented=self._parse_confidence(vent_data.get("increased_fio2_documented")),
            increased_peep_documented=self._parse_confidence(vent_data.get("increased_peep_documented")),
            worsening_oxygenation=self._parse_confidence(vent_data.get("worsening_oxygenation")),
            source=EvidenceSource.from_dict(vent_data.get("source")),
        )

        # Build final extraction
        return VAEExtraction(
            temperature=temperature,
            wbc=wbc,
            antimicrobials=antimicrobials,
            secretions=secretions,
            cultures=cultures,
            ventilator_status=ventilator_status,
            clinical_team_impression=result.get("clinical_team_impression"),
            vap_suspected_by_team=self._parse_confidence(result.get("vap_suspected_by_team")),
            pneumonia_diagnosed=self._parse_confidence(result.get("pneumonia_diagnosed")),
            alternative_diagnoses=result.get("alternative_diagnoses", []),
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


def extract_vae_info(
    candidate: HAICandidate,
    notes: list[ClinicalNote],
    vae_data: VAECandidate | None = None,
    llm_client=None,
) -> VAEExtraction:
    """Convenience function for VAE clinical extraction.

    Args:
        candidate: VAE candidate
        notes: Clinical notes
        vae_data: VAE-specific data
        llm_client: Optional LLM client

    Returns:
        VAEExtraction
    """
    extractor = VAEExtractor(llm_client=llm_client)
    return extractor.extract(candidate, notes, vae_data)
