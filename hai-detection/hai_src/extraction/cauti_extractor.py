"""CAUTI clinical information extractor.

Uses LLM to extract CAUTI-relevant clinical facts from clinical notes.
The extractor answers factual questions - it does NOT make classification decisions.

Extracts:
- Urinary symptoms (fever, dysuria, urgency, frequency, suprapubic pain, CVA tenderness)
- Catheter status (if mentioned in notes)
- Culture results (if mentioned in notes)
- Clinical team's impression (UTI suspected/diagnosed?)
- Alternative diagnoses (renal colic, urethritis, vaginitis, etc.)
"""

import json
import logging
from pathlib import Path

from ..config import Config
from ..models import HAICandidate, ClinicalNote
from ..rules.cauti_schemas import (
    CAUTIExtraction,
    UrinarySymptomExtraction,
    UrineCultureExtraction,
    CatheterStatusExtraction,
)
from ..rules.schemas import ConfidenceLevel, EvidenceSource

logger = logging.getLogger(__name__)


class CAUTIExtractor:
    """Extract CAUTI-relevant clinical information from notes.

    Uses a structured LLM prompt to extract factual information about:
    - Urinary symptoms
    - Catheter documentation
    - Culture results
    - Clinical impressions

    The extraction is then used by CAUTIRulesEngine to apply NHSN criteria.
    """

    def __init__(self, llm_client=None, prompt_version: str = "v1"):
        """Initialize the extractor.

        Args:
            llm_client: LLM client for extraction. Uses default if None.
            prompt_version: Version of extraction prompt to use.
        """
        self.llm_client = llm_client
        self.prompt_version = prompt_version
        self.prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load the extraction prompt template."""
        prompt_path = Path(__file__).parent.parent.parent / "prompts" / f"cauti_extraction_{self.prompt_version}.txt"
        if prompt_path.exists():
            return prompt_path.read_text()
        else:
            # Return inline template if file not found
            return self._get_default_prompt()

    def _get_default_prompt(self) -> str:
        """Get default extraction prompt."""
        return """You are a clinical information extraction system. Your task is to extract
factual information from clinical notes about potential urinary tract infections.

DO NOT make diagnostic decisions. Only extract what is documented.

Patient Context:
- MRN: {mrn}
- Catheter type: {catheter_type}
- Catheter days: {catheter_days}
- Urine culture: {culture_result}
- Patient age: {patient_age}

Clinical Notes:
{notes}

Extract the following information in JSON format:

{{
    "symptoms": {{
        "fever_documented": "definite|probable|possible|not_found|explicitly_absent",
        "fever_temp_celsius": <number or null>,
        "suprapubic_tenderness": "definite|probable|possible|not_found|explicitly_absent",
        "cva_tenderness": "definite|probable|possible|not_found|explicitly_absent",
        "urgency": "definite|probable|possible|not_found|explicitly_absent",
        "frequency": "definite|probable|possible|not_found|explicitly_absent",
        "dysuria": "definite|probable|possible|not_found|explicitly_absent"
    }},
    "catheter_status": {{
        "catheter_in_place": "definite|probable|possible|not_found|explicitly_absent",
        "catheter_type": "<string or null>",
        "days_in_place": <number or null>
    }},
    "clinical_impression": {{
        "uti_suspected": "definite|probable|possible|not_found|explicitly_absent",
        "uti_diagnosed": "definite|probable|possible|not_found|explicitly_absent",
        "clinical_team_impression": "<string or null>"
    }},
    "alternative_diagnoses": ["<diagnosis1>", "<diagnosis2>"],
    "documentation_quality": "poor|limited|adequate|detailed",
    "extraction_notes": "<any important context>"
}}

Important:
- "definite" = explicitly stated and unambiguous
- "probable" = strongly implied or likely based on context
- "possible" = mentioned as possibility or unclear
- "not_found" = not mentioned in the notes
- "explicitly_absent" = explicitly documented as absent/negative

Extract only what is documented. Do not infer or assume.
"""

    def extract(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> CAUTIExtraction:
        """Extract CAUTI-relevant information from clinical notes.

        Args:
            candidate: The CAUTI candidate being evaluated
            notes: Clinical notes to analyze

        Returns:
            CAUTIExtraction with extracted information
        """
        if not notes:
            logger.warning(f"No notes provided for candidate {candidate.id}")
            return self._empty_extraction(0)

        # Get CAUTI-specific data if available
        cauti_data = getattr(candidate, '_cauti_data', None)

        # Prepare context
        context = {
            "mrn": candidate.patient.mrn,
            "catheter_type": cauti_data.catheter_episode.catheter_type if cauti_data else "Unknown",
            "catheter_days": cauti_data.catheter_days if cauti_data else "Unknown",
            "culture_result": self._format_culture(candidate),
            "patient_age": cauti_data.patient_age if cauti_data else "Unknown",
        }

        # Combine relevant notes
        notes_text = self._prepare_notes(notes)
        context["notes"] = notes_text

        # Build prompt
        prompt = self.prompt_template.format(**context)

        # Call LLM
        try:
            response = self._call_llm(prompt)
            extraction = self._parse_response(response, len(notes))
            return extraction
        except Exception as e:
            logger.error(f"Extraction failed for candidate {candidate.id}: {e}")
            return self._empty_extraction(len(notes))

    def _format_culture(self, candidate: HAICandidate) -> str:
        """Format culture result for prompt context."""
        culture = candidate.culture
        cauti_data = getattr(candidate, '_cauti_data', None)

        parts = []
        if culture.organism:
            parts.append(f"Organism: {culture.organism}")
        if cauti_data and cauti_data.culture_cfu_ml:
            parts.append(f"CFU/mL: {cauti_data.culture_cfu_ml:,}")
        if culture.collection_date:
            parts.append(f"Date: {culture.collection_date.date()}")

        return "; ".join(parts) if parts else "Positive urine culture"

    def _prepare_notes(self, notes: list[ClinicalNote]) -> str:
        """Prepare notes for LLM input.

        Sorts by date and formats with metadata.
        """
        # Sort by date, most recent first
        sorted_notes = sorted(notes, key=lambda n: n.date, reverse=True)

        formatted = []
        for note in sorted_notes[:Config.MAX_NOTES_PER_PATIENT]:
            header = f"--- {note.note_type.upper()} ({note.date.date()}) ---"
            # Truncate very long notes
            content = note.content[:8000] if len(note.content) > 8000 else note.content
            formatted.append(f"{header}\n{content}")

        return "\n\n".join(formatted)

    def _call_llm(self, prompt: str) -> str:
        """Call LLM for extraction.

        Uses configured LLM client or falls back to default.
        """
        if self.llm_client:
            return self.llm_client.complete(prompt)

        # Use default client from config
        from ..llm import get_llm_client
        client = get_llm_client()
        return client.complete(prompt)

    def _parse_response(self, response: str, notes_count: int) -> CAUTIExtraction:
        """Parse LLM response to CAUTIExtraction.

        Args:
            response: Raw LLM response
            notes_count: Number of notes analyzed

        Returns:
            Parsed CAUTIExtraction
        """
        try:
            # Extract JSON from response (may be wrapped in markdown)
            json_str = response
            if "```json" in response:
                start = response.find("```json") + 7
                end = response.find("```", start)
                json_str = response[start:end].strip()
            elif "```" in response:
                start = response.find("```") + 3
                end = response.find("```", start)
                json_str = response[start:end].strip()

            data = json.loads(json_str)

            # Parse symptoms
            symptoms_data = data.get("symptoms", {})
            symptoms = UrinarySymptomExtraction(
                fever_documented=self._parse_confidence(symptoms_data.get("fever_documented")),
                fever_temp_celsius=symptoms_data.get("fever_temp_celsius"),
                suprapubic_tenderness=self._parse_confidence(symptoms_data.get("suprapubic_tenderness")),
                cva_tenderness=self._parse_confidence(symptoms_data.get("cva_tenderness")),
                urgency=self._parse_confidence(symptoms_data.get("urgency")),
                frequency=self._parse_confidence(symptoms_data.get("frequency")),
                dysuria=self._parse_confidence(symptoms_data.get("dysuria")),
            )

            # Parse catheter status
            catheter_data = data.get("catheter_status", {})
            catheter_status = CatheterStatusExtraction(
                catheter_in_place=self._parse_confidence(catheter_data.get("catheter_in_place")),
                catheter_type=catheter_data.get("catheter_type"),
                days_in_place=catheter_data.get("days_in_place"),
            )

            # Parse clinical impression
            impression_data = data.get("clinical_impression", {})
            uti_suspected = self._parse_confidence(impression_data.get("uti_suspected"))
            uti_diagnosed = self._parse_confidence(impression_data.get("uti_diagnosed"))
            clinical_impression = impression_data.get("clinical_team_impression")

            return CAUTIExtraction(
                symptoms=symptoms,
                catheter_status=catheter_status,
                clinical_team_impression=clinical_impression,
                uti_suspected_by_team=uti_suspected,
                uti_diagnosed=uti_diagnosed,
                alternative_diagnoses=data.get("alternative_diagnoses", []),
                documentation_quality=data.get("documentation_quality", "adequate"),
                notes_reviewed_count=notes_count,
                extraction_notes=data.get("extraction_notes"),
            )

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"Failed to parse LLM response: {e}")
            return self._empty_extraction(notes_count)

    def _parse_confidence(self, value: str | None) -> ConfidenceLevel:
        """Parse confidence level string to enum."""
        if not value:
            return ConfidenceLevel.NOT_FOUND

        value_lower = value.lower().strip()
        confidence_map = {
            "definite": ConfidenceLevel.DEFINITE,
            "probable": ConfidenceLevel.PROBABLE,
            "possible": ConfidenceLevel.POSSIBLE,
            "not_found": ConfidenceLevel.NOT_FOUND,
            "explicitly_absent": ConfidenceLevel.EXPLICITLY_ABSENT,
        }
        return confidence_map.get(value_lower, ConfidenceLevel.NOT_FOUND)

    def _empty_extraction(self, notes_count: int) -> CAUTIExtraction:
        """Create empty extraction result."""
        return CAUTIExtraction(
            symptoms=UrinarySymptomExtraction(),
            catheter_status=CatheterStatusExtraction(),
            documentation_quality="limited" if notes_count > 0 else "poor",
            notes_reviewed_count=notes_count,
            extraction_notes="Extraction failed or no relevant information found",
        )
