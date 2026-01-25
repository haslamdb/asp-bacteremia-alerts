"""SSI clinical information extractor.

This module uses an LLM to extract structured clinical information from
notes for SSI (Surgical Site Infection) evaluation. The extraction is
then passed to the rules engine for classification.

The key principle: The LLM extracts FACTS, the rules engine applies LOGIC.
"""

import json
import logging
import time
from pathlib import Path
from datetime import datetime

from ..config import Config
from ..models import HAICandidate, ClinicalNote, LLMAuditEntry, SurgicalProcedure
from ..llm.factory import get_llm_client
from ..notes.chunker import NoteChunker
from ..db import HAIDatabase
from ..rules.schemas import ConfidenceLevel, EvidenceSource
from ..rules.ssi_schemas import (
    SSIExtraction,
    WoundAssessmentExtraction,
    SuperficialSSIFindings,
    DeepSSIFindings,
    OrganSpaceSSIFindings,
    ReoperationFindings,
)
from ..rules.nhsn_criteria import get_wound_class_name

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

# JSON Schema for SSI extraction output
SSI_EXTRACTION_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "wound_assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "drainage_present": {"type": "string"},
                    "drainage_type": {"type": ["string", "null"]},
                    "drainage_amount": {"type": ["string", "null"]},
                    "drainage_source": EVIDENCE_SOURCE_SCHEMA,
                    "erythema_present": {"type": "string"},
                    "erythema_extent": {"type": ["string", "null"]},
                    "erythema_source": EVIDENCE_SOURCE_SCHEMA,
                    "warmth_present": {"type": "string"},
                    "induration_present": {"type": "string"},
                    "tenderness_present": {"type": "string"},
                    "wound_dehisced": {"type": "string"},
                    "dehiscence_type": {"type": ["string", "null"]},
                    "dehiscence_source": EVIDENCE_SOURCE_SCHEMA,
                    "wound_opened_deliberately": {"type": "string"},
                    "wound_opened_reason": {"type": ["string", "null"]},
                    "wound_opened_source": EVIDENCE_SOURCE_SCHEMA,
                    "assessment_date": {"type": ["string", "null"]},
                    "assessment_source": EVIDENCE_SOURCE_SCHEMA,
                },
            },
        },
        "superficial_findings": {
            "type": "object",
            "properties": {
                "purulent_drainage_superficial": {"type": "string"},
                "purulent_drainage_source": EVIDENCE_SOURCE_SCHEMA,
                "purulent_drainage_quote": {"type": ["string", "null"]},
                "organisms_from_superficial_culture": {"type": "string"},
                "organism_identified": {"type": ["string", "null"]},
                "culture_source": EVIDENCE_SOURCE_SCHEMA,
                "pain_or_tenderness": {"type": "string"},
                "localized_swelling": {"type": "string"},
                "erythema": {"type": "string"},
                "heat": {"type": "string"},
                "incision_deliberately_opened": {"type": "string"},
                "signs_source": EVIDENCE_SOURCE_SCHEMA,
                "physician_diagnosis_superficial_ssi": {"type": "string"},
                "diagnosis_source": EVIDENCE_SOURCE_SCHEMA,
                "diagnosis_quote": {"type": ["string", "null"]},
            },
        },
        "deep_findings": {
            "type": "object",
            "properties": {
                "purulent_drainage_deep": {"type": "string"},
                "purulent_drainage_source": EVIDENCE_SOURCE_SCHEMA,
                "purulent_drainage_quote": {"type": ["string", "null"]},
                "deep_incision_dehisces": {"type": "string"},
                "deep_incision_opened": {"type": "string"},
                "fever_greater_38": {"type": "string"},
                "fever_value_celsius": {"type": ["number", "null"]},
                "localized_pain_deep": {"type": "string"},
                "dehiscence_source": EVIDENCE_SOURCE_SCHEMA,
                "abscess_on_direct_exam": {"type": "string"},
                "abscess_on_reoperation": {"type": "string"},
                "abscess_on_imaging": {"type": "string"},
                "imaging_type": {"type": ["string", "null"]},
                "abscess_on_histopath": {"type": "string"},
                "abscess_source": EVIDENCE_SOURCE_SCHEMA,
                "physician_diagnosis_deep_ssi": {"type": "string"},
                "diagnosis_source": EVIDENCE_SOURCE_SCHEMA,
                "diagnosis_quote": {"type": ["string", "null"]},
            },
        },
        "organ_space_findings": {
            "type": "object",
            "properties": {
                "purulent_drainage_drain": {"type": "string"},
                "drain_location": {"type": ["string", "null"]},
                "drain_source": EVIDENCE_SOURCE_SCHEMA,
                "organisms_from_organ_space": {"type": "string"},
                "organism_identified": {"type": ["string", "null"]},
                "specimen_type": {"type": ["string", "null"]},
                "culture_source": EVIDENCE_SOURCE_SCHEMA,
                "abscess_on_direct_exam": {"type": "string"},
                "abscess_on_reoperation": {"type": "string"},
                "abscess_on_imaging": {"type": "string"},
                "imaging_type": {"type": ["string", "null"]},
                "imaging_findings": {"type": ["string", "null"]},
                "abscess_on_histopath": {"type": "string"},
                "abscess_source": EVIDENCE_SOURCE_SCHEMA,
                "physician_diagnosis_organ_space_ssi": {"type": "string"},
                "diagnosis_source": EVIDENCE_SOURCE_SCHEMA,
                "diagnosis_quote": {"type": ["string", "null"]},
                "organ_space_involved": {"type": ["string", "null"]},
                "organ_space_nhsn_code": {"type": ["string", "null"]},
            },
        },
        "reoperation": {
            "type": "object",
            "properties": {
                "reoperation_performed": {"type": "string"},
                "reoperation_date": {"type": ["string", "null"]},
                "reoperation_indication": {"type": ["string", "null"]},
                "reoperation_findings": {"type": ["string", "null"]},
                "reoperation_source": EVIDENCE_SOURCE_SCHEMA,
            },
        },
        "fever_documented": {"type": "string"},
        "fever_max_celsius": {"type": ["number", "null"]},
        "leukocytosis_documented": {"type": "string"},
        "wbc_value": {"type": ["number", "null"]},
        "antibiotics_for_wound_infection": {"type": "string"},
        "antibiotic_names": {"type": "array", "items": {"type": "string"}},
        "antibiotic_source": EVIDENCE_SOURCE_SCHEMA,
        "clinical_team_impression": {"type": ["string", "null"]},
        "ssi_suspected_by_team": {"type": "string"},
        "documentation_quality": {
            "type": "string",
            "enum": ["poor", "limited", "adequate", "detailed"],
        },
        "notes_reviewed_count": {"type": "integer"},
        "extraction_notes": {"type": ["string", "null"]},
    },
    "required": [
        "wound_assessments",
        "superficial_findings",
        "deep_findings",
        "organ_space_findings",
        "reoperation",
        "documentation_quality",
        "notes_reviewed_count",
    ],
}


class SSIExtractor:
    """Extract SSI-relevant clinical information from notes using LLM.

    This class handles:
    1. Building the extraction prompt from notes and procedure context
    2. Calling the LLM with structured output
    3. Parsing the response into SSIExtraction dataclass
    4. Audit logging of LLM calls

    The extraction is separate from classification - the rules engine
    takes the extraction output and applies NHSN SSI criteria.
    """

    PROMPT_VERSION = "ssi_extraction_v1"

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
            Path(__file__).parent.parent.parent / "prompts" / "ssi_extraction_v1.txt"
        )
        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.warning(f"Prompt template not found: {prompt_path}")
            return self._default_prompt_template()

    def _default_prompt_template(self) -> str:
        """Fallback prompt if file not found."""
        return """Extract clinical information for SSI evaluation.

Patient: {patient_mrn}
Procedure: {procedure_name}
Procedure Date: {procedure_date}
Days Post-Op: {days_post_op}

Notes:
{clinical_notes}

Extract: wound assessments, SSI findings (superficial/deep/organ-space), reoperation info.
Respond with JSON matching the SSIExtraction schema."""

    def extract(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        procedure: SurgicalProcedure | None = None,
    ) -> SSIExtraction:
        """Extract SSI-relevant clinical information from notes.

        Args:
            candidate: The SSI candidate with patient info
            notes: Clinical notes to extract from
            procedure: Surgical procedure details (optional, may be in candidate)

        Returns:
            SSIExtraction with structured extracted data
        """
        start_time = time.time()

        # Get procedure from candidate if not provided
        if procedure is None:
            procedure = getattr(candidate, "_ssi_data", None)
            if procedure:
                procedure = procedure.procedure

        if procedure is None:
            logger.warning(f"No procedure data for candidate {candidate.id}")
            return SSIExtraction(
                clinical_team_impression="No procedure data available",
                documentation_quality="poor",
                notes_reviewed_count=len(notes),
                extraction_notes="Missing procedure information",
            )

        # Build prompt
        prompt = self._build_prompt(candidate, notes, procedure)

        try:
            # Call LLM with structured output
            result = self.llm_client.generate_structured(
                prompt=prompt,
                output_schema=SSI_EXTRACTION_OUTPUT_SCHEMA,
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
            logger.error(f"SSI extraction failed: {e}")
            elapsed_ms = int((time.time() - start_time) * 1000)

            if self.db:
                self._log_error(candidate, elapsed_ms, str(e))

            # Return minimal extraction on failure
            return SSIExtraction(
                clinical_team_impression=f"Extraction failed: {e}",
                documentation_quality="poor",
                notes_reviewed_count=len(notes),
                extraction_notes=f"LLM extraction error: {e}",
            )

    def _build_prompt(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        procedure: SurgicalProcedure,
    ) -> str:
        """Build the extraction prompt."""
        # Extract relevant context from notes
        notes_context = self.chunker.extract_relevant_context(notes)

        # Calculate days post-op
        now = datetime.now()
        days_post_op = procedure.days_since_procedure(now)

        # Get wound class name
        wound_class_str = "Unknown"
        if procedure.wound_class:
            wound_class_str = f"{procedure.wound_class} ({get_wound_class_name(procedure.wound_class)})"

        # Format prompt
        return self._prompt_template.format(
            patient_mrn=candidate.patient.mrn,
            procedure_name=procedure.procedure_name,
            procedure_date=procedure.procedure_date.strftime("%Y-%m-%d"),
            nhsn_category=procedure.nhsn_category or "Unknown",
            days_post_op=days_post_op,
            wound_class=wound_class_str,
            implant_used="Yes" if procedure.implant_used else "No",
            surveillance_days=procedure.get_surveillance_days(),
            clinical_notes=notes_context or "No clinical notes available.",
        )

    def _parse_response(
        self,
        result: dict,
        notes_count: int,
    ) -> SSIExtraction:
        """Parse LLM response into SSIExtraction dataclass."""

        # Parse wound assessments
        wound_assessments = []
        for wa_data in result.get("wound_assessments", []):
            try:
                wound_assessments.append(WoundAssessmentExtraction(
                    drainage_present=self._parse_confidence(wa_data.get("drainage_present")),
                    drainage_type=wa_data.get("drainage_type"),
                    drainage_amount=wa_data.get("drainage_amount"),
                    drainage_source=EvidenceSource.from_dict(wa_data.get("drainage_source")),
                    erythema_present=self._parse_confidence(wa_data.get("erythema_present")),
                    erythema_extent=wa_data.get("erythema_extent"),
                    erythema_source=EvidenceSource.from_dict(wa_data.get("erythema_source")),
                    warmth_present=self._parse_confidence(wa_data.get("warmth_present")),
                    induration_present=self._parse_confidence(wa_data.get("induration_present")),
                    tenderness_present=self._parse_confidence(wa_data.get("tenderness_present")),
                    wound_dehisced=self._parse_confidence(wa_data.get("wound_dehisced")),
                    dehiscence_type=wa_data.get("dehiscence_type"),
                    dehiscence_source=EvidenceSource.from_dict(wa_data.get("dehiscence_source")),
                    wound_opened_deliberately=self._parse_confidence(wa_data.get("wound_opened_deliberately")),
                    wound_opened_reason=wa_data.get("wound_opened_reason"),
                    wound_opened_source=EvidenceSource.from_dict(wa_data.get("wound_opened_source")),
                    assessment_date=wa_data.get("assessment_date"),
                    assessment_source=EvidenceSource.from_dict(wa_data.get("assessment_source")),
                ))
            except Exception as e:
                logger.warning(f"Failed to parse wound assessment: {e}")

        # Parse superficial findings
        sup_data = result.get("superficial_findings", {})
        superficial_findings = SuperficialSSIFindings(
            purulent_drainage_superficial=self._parse_confidence(sup_data.get("purulent_drainage_superficial")),
            purulent_drainage_source=EvidenceSource.from_dict(sup_data.get("purulent_drainage_source")),
            purulent_drainage_quote=sup_data.get("purulent_drainage_quote"),
            organisms_from_superficial_culture=self._parse_confidence(sup_data.get("organisms_from_superficial_culture")),
            organism_identified=sup_data.get("organism_identified"),
            culture_source=EvidenceSource.from_dict(sup_data.get("culture_source")),
            pain_or_tenderness=self._parse_confidence(sup_data.get("pain_or_tenderness")),
            localized_swelling=self._parse_confidence(sup_data.get("localized_swelling")),
            erythema=self._parse_confidence(sup_data.get("erythema")),
            heat=self._parse_confidence(sup_data.get("heat")),
            incision_deliberately_opened=self._parse_confidence(sup_data.get("incision_deliberately_opened")),
            signs_source=EvidenceSource.from_dict(sup_data.get("signs_source")),
            physician_diagnosis_superficial_ssi=self._parse_confidence(sup_data.get("physician_diagnosis_superficial_ssi")),
            diagnosis_source=EvidenceSource.from_dict(sup_data.get("diagnosis_source")),
            diagnosis_quote=sup_data.get("diagnosis_quote"),
        )

        # Parse deep findings
        deep_data = result.get("deep_findings", {})
        deep_findings = DeepSSIFindings(
            purulent_drainage_deep=self._parse_confidence(deep_data.get("purulent_drainage_deep")),
            purulent_drainage_source=EvidenceSource.from_dict(deep_data.get("purulent_drainage_source")),
            purulent_drainage_quote=deep_data.get("purulent_drainage_quote"),
            deep_incision_dehisces=self._parse_confidence(deep_data.get("deep_incision_dehisces")),
            deep_incision_opened=self._parse_confidence(deep_data.get("deep_incision_opened")),
            fever_greater_38=self._parse_confidence(deep_data.get("fever_greater_38")),
            fever_value_celsius=deep_data.get("fever_value_celsius"),
            localized_pain_deep=self._parse_confidence(deep_data.get("localized_pain_deep")),
            dehiscence_source=EvidenceSource.from_dict(deep_data.get("dehiscence_source")),
            abscess_on_direct_exam=self._parse_confidence(deep_data.get("abscess_on_direct_exam")),
            abscess_on_reoperation=self._parse_confidence(deep_data.get("abscess_on_reoperation")),
            abscess_on_imaging=self._parse_confidence(deep_data.get("abscess_on_imaging")),
            imaging_type=deep_data.get("imaging_type"),
            abscess_on_histopath=self._parse_confidence(deep_data.get("abscess_on_histopath")),
            abscess_source=EvidenceSource.from_dict(deep_data.get("abscess_source")),
            physician_diagnosis_deep_ssi=self._parse_confidence(deep_data.get("physician_diagnosis_deep_ssi")),
            diagnosis_source=EvidenceSource.from_dict(deep_data.get("diagnosis_source")),
            diagnosis_quote=deep_data.get("diagnosis_quote"),
        )

        # Parse organ/space findings
        os_data = result.get("organ_space_findings", {})
        organ_space_findings = OrganSpaceSSIFindings(
            purulent_drainage_drain=self._parse_confidence(os_data.get("purulent_drainage_drain")),
            drain_location=os_data.get("drain_location"),
            drain_source=EvidenceSource.from_dict(os_data.get("drain_source")),
            organisms_from_organ_space=self._parse_confidence(os_data.get("organisms_from_organ_space")),
            organism_identified=os_data.get("organism_identified"),
            specimen_type=os_data.get("specimen_type"),
            culture_source=EvidenceSource.from_dict(os_data.get("culture_source")),
            abscess_on_direct_exam=self._parse_confidence(os_data.get("abscess_on_direct_exam")),
            abscess_on_reoperation=self._parse_confidence(os_data.get("abscess_on_reoperation")),
            abscess_on_imaging=self._parse_confidence(os_data.get("abscess_on_imaging")),
            imaging_type=os_data.get("imaging_type"),
            imaging_findings=os_data.get("imaging_findings"),
            abscess_on_histopath=self._parse_confidence(os_data.get("abscess_on_histopath")),
            abscess_source=EvidenceSource.from_dict(os_data.get("abscess_source")),
            physician_diagnosis_organ_space_ssi=self._parse_confidence(os_data.get("physician_diagnosis_organ_space_ssi")),
            diagnosis_source=EvidenceSource.from_dict(os_data.get("diagnosis_source")),
            diagnosis_quote=os_data.get("diagnosis_quote"),
            organ_space_involved=os_data.get("organ_space_involved"),
            organ_space_nhsn_code=os_data.get("organ_space_nhsn_code"),
        )

        # Parse reoperation findings
        reop_data = result.get("reoperation", {})
        reoperation = ReoperationFindings(
            reoperation_performed=self._parse_confidence(reop_data.get("reoperation_performed")),
            reoperation_date=reop_data.get("reoperation_date"),
            reoperation_indication=reop_data.get("reoperation_indication"),
            reoperation_findings=reop_data.get("reoperation_findings"),
            reoperation_source=EvidenceSource.from_dict(reop_data.get("reoperation_source")),
        )

        # Build final extraction
        return SSIExtraction(
            wound_assessments=wound_assessments,
            superficial_findings=superficial_findings,
            deep_findings=deep_findings,
            organ_space_findings=organ_space_findings,
            reoperation=reoperation,
            fever_documented=self._parse_confidence(result.get("fever_documented")),
            fever_max_celsius=result.get("fever_max_celsius"),
            leukocytosis_documented=self._parse_confidence(result.get("leukocytosis_documented")),
            wbc_value=result.get("wbc_value"),
            antibiotics_for_wound_infection=self._parse_confidence(result.get("antibiotics_for_wound_infection")),
            antibiotic_names=result.get("antibiotic_names", []),
            antibiotic_source=EvidenceSource.from_dict(result.get("antibiotic_source")),
            clinical_team_impression=result.get("clinical_team_impression"),
            ssi_suspected_by_team=self._parse_confidence(result.get("ssi_suspected_by_team")),
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


def extract_ssi_info(
    candidate: HAICandidate,
    notes: list[ClinicalNote],
    procedure: SurgicalProcedure | None = None,
    llm_client=None,
) -> SSIExtraction:
    """Convenience function for SSI clinical extraction.

    Args:
        candidate: SSI candidate
        notes: Clinical notes
        procedure: Surgical procedure details
        llm_client: Optional LLM client

    Returns:
        SSIExtraction
    """
    extractor = SSIExtractor(llm_client=llm_client)
    return extractor.extract(candidate, notes, procedure)
