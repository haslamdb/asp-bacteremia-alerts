"""CDI (Clostridioides difficile Infection) clinical note extractor.

Extracts clinical facts relevant to CDI classification from EHR notes.

CDI extraction is simpler than device-associated HAIs because:
1. The classification is primarily time-based (specimen day)
2. Device tracking is not needed
3. Symptom documentation (diarrhea) is usually implied by the test order

Key extracted elements:
- Diarrhea documentation (frequency, consistency)
- Prior CDI history mentioned in notes
- CDI treatment initiated
- Clinical team's impression
- Alternative diagnoses (non-CDI causes of diarrhea)
- Recent antibiotic use (risk factor)
"""

import json
import logging
from pathlib import Path

from ..models import HAICandidate, ClinicalNote
from ..rules.schemas import ConfidenceLevel, EvidenceSource
from ..rules.cdi_schemas import (
    CDIExtraction,
    DiarrheaExtraction,
    CDIHistoryExtraction,
    CDITreatmentExtraction,
)

logger = logging.getLogger(__name__)


class CDIExtractor:
    """Extract CDI-relevant clinical facts from notes using LLM.

    The extractor performs FACTUAL extraction only - it identifies what
    is documented in the notes but does NOT make classification decisions.
    The rules engine applies NHSN criteria to the extracted facts.
    """

    def __init__(
        self,
        llm_client=None,
        prompt_version: str = "v1",
    ):
        """Initialize the CDI extractor.

        Args:
            llm_client: LLM client for extraction. Uses default if None.
            prompt_version: Version of prompt template to use.
        """
        self.llm_client = llm_client
        self.prompt_version = prompt_version
        self.prompt_template = self._load_prompt_template()

    def extract(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> CDIExtraction:
        """Extract CDI-relevant facts from clinical notes.

        Args:
            candidate: The CDI candidate being evaluated
            notes: Clinical notes to extract from

        Returns:
            CDIExtraction with all extracted clinical facts
        """
        if not notes:
            logger.warning(f"No notes provided for CDI extraction")
            return CDIExtraction(
                documentation_quality="poor",
                notes_reviewed_count=0,
                extraction_notes="No clinical notes available",
            )

        # Format notes for prompt
        notes_text = self._format_notes(notes)

        # Get CDI-specific context from candidate
        cdi_data = getattr(candidate, "_cdi_data", None)
        test_date = candidate.culture.collection_date.strftime("%Y-%m-%d")
        test_type = cdi_data.test_result.test_type if cdi_data else "toxin"

        # Build prompt
        prompt = self.prompt_template.format(
            patient_mrn=candidate.patient.mrn,
            test_date=test_date,
            test_type=test_type,
            notes=notes_text,
        )

        # Call LLM
        try:
            if self.llm_client:
                response = self.llm_client.extract(prompt)
                extraction = self._parse_response(response)
            else:
                # No LLM client - return minimal extraction
                logger.warning("No LLM client configured, returning minimal extraction")
                extraction = CDIExtraction(
                    documentation_quality="not_extracted",
                    notes_reviewed_count=len(notes),
                    extraction_notes="LLM extraction not configured",
                )
        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            extraction = CDIExtraction(
                documentation_quality="error",
                notes_reviewed_count=len(notes),
                extraction_notes=f"Extraction error: {str(e)}",
            )

        extraction.notes_reviewed_count = len(notes)
        return extraction

    def _format_notes(self, notes: list[ClinicalNote]) -> str:
        """Format clinical notes for the prompt."""
        formatted = []

        for note in notes:
            header = f"=== {note.note_type.upper()} ({note.date.strftime('%Y-%m-%d')}) ==="
            if note.author:
                header += f" by {note.author}"

            # Truncate very long notes
            content = note.content
            if len(content) > 4000:
                content = content[:4000] + "\n... [truncated]"

            formatted.append(f"{header}\n{content}")

        return "\n\n".join(formatted)

    def _parse_response(self, response: str) -> CDIExtraction:
        """Parse LLM response into CDIExtraction."""
        try:
            # Try to parse as JSON
            data = json.loads(response)

            # Parse diarrhea findings
            diarrhea = DiarrheaExtraction(
                diarrhea_documented=self._parse_confidence(
                    data.get("diarrhea", {}).get("documented")
                ),
                diarrhea_date=data.get("diarrhea", {}).get("date"),
                stool_frequency=data.get("diarrhea", {}).get("frequency"),
                stool_consistency=data.get("diarrhea", {}).get("consistency"),
            )

            # Parse prior history
            prior_history = CDIHistoryExtraction(
                prior_cdi_mentioned=self._parse_confidence(
                    data.get("prior_history", {}).get("mentioned")
                ),
                prior_cdi_date=data.get("prior_history", {}).get("date"),
                prior_cdi_treatment=data.get("prior_history", {}).get("treatment"),
            )

            # Parse treatment
            treatment = CDITreatmentExtraction(
                treatment_initiated=self._parse_confidence(
                    data.get("treatment", {}).get("initiated")
                ),
                treatment_type=data.get("treatment", {}).get("type"),
                treatment_route=data.get("treatment", {}).get("route"),
                treatment_start_date=data.get("treatment", {}).get("start_date"),
            )

            return CDIExtraction(
                diarrhea=diarrhea,
                prior_history=prior_history,
                treatment=treatment,
                clinical_team_impression=data.get("clinical_impression"),
                cdi_suspected_by_team=self._parse_confidence(
                    data.get("cdi_suspected")
                ),
                cdi_diagnosed=self._parse_confidence(
                    data.get("cdi_diagnosed")
                ),
                recent_antibiotic_use=self._parse_confidence(
                    data.get("recent_antibiotics", {}).get("documented")
                ),
                recent_hospitalization=self._parse_confidence(
                    data.get("recent_hospitalization")
                ),
                recent_antibiotics_list=data.get("recent_antibiotics", {}).get("list", []),
                alternative_diagnoses=data.get("alternative_diagnoses", []),
                documentation_quality=data.get("documentation_quality", "adequate"),
            )

        except json.JSONDecodeError:
            logger.warning("Could not parse LLM response as JSON")
            return CDIExtraction(
                documentation_quality="parse_error",
                extraction_notes="Could not parse LLM response",
            )

    def _parse_confidence(self, value: str | None) -> ConfidenceLevel:
        """Parse a confidence level string to enum."""
        if not value:
            return ConfidenceLevel.NOT_FOUND

        value_lower = value.lower().strip()
        mapping = {
            "definite": ConfidenceLevel.DEFINITE,
            "probable": ConfidenceLevel.PROBABLE,
            "possible": ConfidenceLevel.POSSIBLE,
            "not_found": ConfidenceLevel.NOT_FOUND,
            "ruled_out": ConfidenceLevel.RULED_OUT,
            "yes": ConfidenceLevel.DEFINITE,
            "no": ConfidenceLevel.NOT_FOUND,
        }
        return mapping.get(value_lower, ConfidenceLevel.NOT_FOUND)

    def _load_prompt_template(self) -> str:
        """Load the prompt template from file or use default."""
        # Try to load from prompts directory
        prompts_dir = Path(__file__).parent.parent.parent / "prompts"
        template_file = prompts_dir / f"cdi_extraction_{self.prompt_version}.txt"

        if template_file.exists():
            try:
                return template_file.read_text()
            except Exception as e:
                logger.warning(f"Could not load prompt template: {e}")

        # Return default prompt
        return self._get_default_prompt()

    def _get_default_prompt(self) -> str:
        """Get the default CDI extraction prompt."""
        return """You are a clinical data extractor. Review the clinical notes for a patient with a positive C. difficile test and extract relevant clinical facts.

PATIENT: {patient_mrn}
C. DIFF TEST DATE: {test_date}
TEST TYPE: {test_type}

IMPORTANT: Extract only what is DOCUMENTED in the notes. Do NOT make inferences.

Return a JSON object with these fields:

{{
    "diarrhea": {{
        "documented": "definite|probable|possible|not_found|ruled_out",
        "date": "YYYY-MM-DD or null",
        "frequency": number or null,
        "consistency": "liquid|watery|loose|soft|formed|null"
    }},
    "prior_history": {{
        "mentioned": "definite|probable|possible|not_found",
        "date": "YYYY-MM-DD or approximate or null",
        "treatment": "medication name or null"
    }},
    "treatment": {{
        "initiated": "definite|probable|possible|not_found",
        "type": "vancomycin|fidaxomicin|metronidazole|null",
        "route": "oral|iv|rectal|null",
        "start_date": "YYYY-MM-DD or null"
    }},
    "clinical_impression": "free text summary of clinical team's assessment or null",
    "cdi_suspected": "definite|probable|possible|not_found",
    "cdi_diagnosed": "definite|probable|possible|not_found",
    "recent_antibiotics": {{
        "documented": "definite|probable|possible|not_found",
        "list": ["antibiotic names"]
    }},
    "recent_hospitalization": "definite|probable|possible|not_found",
    "alternative_diagnoses": ["list of alternative diarrhea causes mentioned"],
    "documentation_quality": "detailed|adequate|limited|poor"
}}

CLINICAL NOTES:
{notes}

Extract the facts and return ONLY the JSON object."""
