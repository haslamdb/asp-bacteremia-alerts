"""CLABSI classification using LLM."""

import json
import logging
import time
import uuid
from pathlib import Path

from ..config import Config
from ..models import (
    HAICandidate,
    HAIType,
    Classification,
    ClassificationDecision,
    ClinicalNote,
    SupportingEvidence,
    LLMAuditEntry,
)
from ..llm.factory import get_llm_client
from ..notes.chunker import NoteChunker
from ..db import HAIDatabase
from ..data.fhir_source import FHIRCultureSource
from .base import BaseHAIClassifier

logger = logging.getLogger(__name__)


class CLABSIClassifier(BaseHAIClassifier):
    """CLABSI classification using LLM for source attribution."""

    PROMPT_VERSION = "clabsi_v1"

    def __init__(
        self,
        llm_client=None,
        db: HAIDatabase | None = None,
        culture_source: FHIRCultureSource | None = None,
    ):
        """Initialize classifier.

        Args:
            llm_client: LLM client instance. Uses factory default if None.
            db: Database for audit logging. Optional.
            culture_source: Culture source for checking other sites. Optional.
        """
        self._llm_client = llm_client
        self.db = db
        self.chunker = NoteChunker()
        self._culture_source = culture_source
        self._prompt_template = self._load_prompt_template()

    @property
    def culture_source(self):
        """Lazy-load culture source."""
        if self._culture_source is None:
            self._culture_source = FHIRCultureSource()
        return self._culture_source

    @property
    def llm_client(self):
        """Lazy-load LLM client."""
        if self._llm_client is None:
            self._llm_client = get_llm_client()
        return self._llm_client

    @property
    def hai_type(self) -> str:
        return HAIType.CLABSI.value

    @property
    def prompt_version(self) -> str:
        return self.PROMPT_VERSION

    def _load_prompt_template(self) -> str:
        """Load prompt template from file."""
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / "clabsi_v1.txt"
        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.warning(f"Prompt template not found: {prompt_path}")
            return self._default_prompt_template()

    def _default_prompt_template(self) -> str:
        """Fallback prompt template."""
        return """Evaluate if this BSI is a CLABSI:
Patient MRN: {patient_mrn}
Organism: {organism}
Central Line Days: {device_days}

Clinical Notes:
{clinical_notes}

Respond with JSON: {{"decision": "hai_confirmed"|"not_hai"|"pending_review", "confidence": 0.0-1.0, "reasoning": "..."}}"""

    def classify(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> Classification:
        """Classify a CLABSI candidate.

        Args:
            candidate: The CLABSI candidate
            notes: Clinical notes for context

        Returns:
            Classification with decision and confidence
        """
        start_time = time.time()

        # Build prompt
        prompt = self.build_prompt(candidate, notes)

        # Define expected output schema
        output_schema = {
            "type": "object",
            "properties": {
                "decision": {"type": "string", "enum": ["hai_confirmed", "not_hai", "pending_review"]},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "alternative_source": {"type": ["string", "null"]},
                "is_mbi_lcbi": {"type": "boolean"},
                "supporting_evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "source": {"type": "string"},
                            "relevance": {"type": "string"},
                        },
                    },
                },
                "contradicting_evidence": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "text": {"type": "string"},
                            "source": {"type": "string"},
                            "relevance": {"type": "string"},
                        },
                    },
                },
                "reasoning": {"type": "string"},
            },
            "required": ["decision", "confidence", "reasoning"],
        }

        try:
            # Call LLM
            result = self.llm_client.generate_structured(
                prompt=prompt,
                output_schema=output_schema,
                temperature=0.0,
            )

            elapsed_ms = int((time.time() - start_time) * 1000)

            # Parse response
            classification = self._parse_response(candidate, result, elapsed_ms)

            # Audit log
            if self.db:
                self._log_success(candidate, elapsed_ms)

            return classification

        except Exception as e:
            logger.error(f"Classification failed: {e}")
            elapsed_ms = int((time.time() - start_time) * 1000)

            if self.db:
                self._log_error(candidate, elapsed_ms, str(e))

            # Return low-confidence result for manual review
            return Classification(
                id=str(uuid.uuid4()),
                candidate_id=candidate.id,
                decision=ClassificationDecision.PENDING_REVIEW,
                confidence=0.0,
                reasoning=f"Classification failed: {e}",
                model_used=self.llm_client.model_name,
                prompt_version=self.prompt_version,
                processing_time_ms=elapsed_ms,
            )

    def build_prompt(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> str:
        """Build the classification prompt."""
        # Extract relevant sections from notes
        notes_context = self.chunker.extract_relevant_context(notes)

        # Check for matching organisms at other sites
        other_cultures_context = self._get_other_cultures_context(candidate)

        # Format prompt
        return self._prompt_template.format(
            patient_mrn=candidate.patient.mrn,
            culture_date=candidate.culture.collection_date.strftime("%Y-%m-%d"),
            organism=candidate.culture.organism or "Pending identification",
            device_type=candidate.device_info.device_type if candidate.device_info else "Unknown",
            device_days=candidate.device_days_at_culture or "Unknown",
            device_site=candidate.device_info.site if candidate.device_info else "Unknown",
            clinical_notes=notes_context or "No clinical notes available.",
            other_cultures=other_cultures_context,
        )

    def _get_other_cultures_context(self, candidate: HAICandidate) -> str:
        """Get context about cultures from other sites with matching organisms."""
        if not candidate.culture.organism:
            return "No other culture data available."

        try:
            matching_cultures = self.culture_source.find_matching_organisms(
                patient_id=candidate.patient.fhir_id,
                blood_culture_organism=candidate.culture.organism,
                blood_culture_date=candidate.culture.collection_date,
                window_days=7,
            )

            if not matching_cultures:
                return "No matching organisms found at other culture sites."

            lines = ["Cultures from other sites with the same organism:"]
            for culture in matching_cultures:
                date_str = culture.collection_date.strftime("%Y-%m-%d")
                lines.append(
                    f"- {culture.specimen_source.upper()}: {culture.organism} ({date_str})"
                )

            return "\n".join(lines)

        except Exception as e:
            logger.warning(f"Failed to query other cultures: {e}")
            return "Unable to query other culture sites."

    def _parse_response(
        self,
        candidate: HAICandidate,
        result: dict,
        elapsed_ms: int,
    ) -> Classification:
        """Parse LLM response into Classification."""
        # Parse decision
        decision_str = result.get("decision", "pending_review")
        try:
            decision = ClassificationDecision(decision_str)
        except ValueError:
            decision = ClassificationDecision.PENDING_REVIEW

        # Parse evidence
        supporting = []
        for e in result.get("supporting_evidence", []):
            supporting.append(SupportingEvidence(
                text=e.get("text", ""),
                source=e.get("source", "unknown"),
                relevance=e.get("relevance"),
            ))

        contradicting = []
        for e in result.get("contradicting_evidence", []):
            contradicting.append(SupportingEvidence(
                text=e.get("text", ""),
                source=e.get("source", "unknown"),
                relevance=e.get("relevance"),
            ))

        return Classification(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            decision=decision,
            confidence=result.get("confidence", 0.5),
            alternative_source=result.get("alternative_source"),
            is_mbi_lcbi=result.get("is_mbi_lcbi", False),
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            reasoning=result.get("reasoning", ""),
            model_used=self.llm_client.model_name,
            prompt_version=self.prompt_version,
            processing_time_ms=elapsed_ms,
        )

    def _log_success(self, candidate: HAICandidate, elapsed_ms: int) -> None:
        """Log successful LLM call."""
        entry = LLMAuditEntry(
            candidate_id=candidate.id,
            model=self.llm_client.model_name,
            success=True,
            response_time_ms=elapsed_ms,
        )
        self.db.log_llm_call(entry)

    def _log_error(self, candidate: HAICandidate, elapsed_ms: int, error: str) -> None:
        """Log failed LLM call."""
        entry = LLMAuditEntry(
            candidate_id=candidate.id,
            model=self.llm_client.model_name,
            success=False,
            response_time_ms=elapsed_ms,
            error_message=error,
        )
        self.db.log_llm_call(entry)
