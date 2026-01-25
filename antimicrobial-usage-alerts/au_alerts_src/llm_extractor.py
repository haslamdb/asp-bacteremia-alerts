"""LLM-based indication extraction from clinical notes.

Uses a local LLM (via Ollama) to extract antibiotic indications from
clinical notes when ICD-10 classification results in N or U.
"""

import json
import logging
import time
from pathlib import Path
from typing import Any

import requests

from .config import config
from .models import IndicationExtraction

logger = logging.getLogger(__name__)


class IndicationExtractor:
    """Extract antibiotic indications from clinical notes using LLM."""

    PROMPT_VERSION = "indication_extraction_v1"

    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
    ):
        """Initialize the extractor.

        Args:
            model: LLM model name (e.g., "llama3.2"). Uses config default if None.
            base_url: Ollama API base URL. Uses config default if None.
        """
        self.model = model or config.LLM_MODEL
        self.base_url = base_url or config.LLM_BASE_URL
        self._prompt_template = self._load_prompt_template()

    def _load_prompt_template(self) -> str:
        """Load extraction prompt template from file."""
        prompt_path = (
            Path(__file__).parent.parent / "prompts" / f"{self.PROMPT_VERSION}.txt"
        )
        try:
            return prompt_path.read_text()
        except FileNotFoundError:
            logger.warning(f"Prompt template not found: {prompt_path}")
            return self._default_prompt_template()

    def _default_prompt_template(self) -> str:
        """Fallback prompt if file not found."""
        return """Extract antibiotic indications from these clinical notes for {antibiotic}:

{notes}

Respond with JSON containing:
- documented_indication: string or null
- supporting_quotes: list of relevant quotes
- confidence: HIGH, MEDIUM, or LOW
"""

    def is_available(self) -> bool:
        """Check if the LLM is available.

        Returns:
            True if the LLM can be reached and model is available.
        """
        try:
            response = requests.get(
                f"{self.base_url}/api/tags",
                timeout=5,
            )
            if response.status_code != 200:
                return False

            models = response.json().get("models", [])
            # Get full model names and base names (without tag)
            full_names = [m.get("name", "") for m in models]
            base_names = [name.split(":")[0] for name in full_names]

            # Check if our model matches (with or without tag)
            if self.model in full_names:
                return True
            if self.model in base_names:
                return True
            if f"{self.model}:latest" in full_names:
                return True

            return False
        except Exception as e:
            logger.debug(f"LLM availability check failed: {e}")
            return False

    def extract(
        self,
        notes: list[str],
        medication: str,
    ) -> IndicationExtraction:
        """Extract potential indications from notes.

        Args:
            notes: List of clinical note texts.
            medication: The antibiotic name.

        Returns:
            IndicationExtraction with findings.
        """
        start_time = time.time()

        # Combine notes with truncation
        combined_notes = self._prepare_notes(notes)

        # Build prompt
        prompt = self._prompt_template.format(
            antibiotic=medication,
            notes=combined_notes,
        )

        try:
            # Call LLM
            result = self._call_llm(prompt)
            elapsed_ms = int((time.time() - start_time) * 1000)

            # Parse response
            return self._parse_response(result, elapsed_ms)

        except Exception as e:
            logger.error(f"LLM extraction failed: {e}")
            elapsed_ms = int((time.time() - start_time) * 1000)

            return IndicationExtraction(
                found_indications=[],
                supporting_quotes=[],
                confidence="LOW",
                model_used=self.model,
                prompt_version=self.PROMPT_VERSION,
            )

    def _prepare_notes(self, notes: list[str], max_chars: int = 8000) -> str:
        """Prepare notes for LLM input with truncation.

        Args:
            notes: List of note texts.
            max_chars: Maximum characters to include.

        Returns:
            Combined and truncated note text.
        """
        # Join notes with separators
        combined = "\n\n---\n\n".join(notes)

        # Truncate if needed
        if len(combined) > max_chars:
            combined = combined[:max_chars] + "\n\n[Note truncated...]"

        return combined

    def _call_llm(self, prompt: str) -> dict:
        """Call the LLM API.

        Args:
            prompt: The prompt to send.

        Returns:
            Parsed JSON response.

        Raises:
            Exception on API or parsing errors.
        """
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.0,  # Deterministic
                    "num_predict": 1024,
                },
            },
            timeout=60,
        )

        if response.status_code != 200:
            raise Exception(f"LLM API error: {response.status_code} - {response.text}")

        result = response.json()
        response_text = result.get("response", "")

        # Parse JSON from response
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM JSON response: {e}")
            # Try to extract JSON from response
            return self._extract_json(response_text)

    def _extract_json(self, text: str) -> dict:
        """Try to extract JSON from text that may have surrounding content.

        Args:
            text: Text that may contain JSON.

        Returns:
            Parsed JSON dict or empty dict on failure.
        """
        import re

        # First, try direct parsing (in case it's valid JSON with whitespace)
        try:
            return json.loads(text.strip())
        except json.JSONDecodeError:
            pass

        # Look for JSON object pattern - find the outermost braces
        # Handle nested objects by finding matching braces
        brace_count = 0
        start_idx = -1
        end_idx = -1

        for i, char in enumerate(text):
            if char == "{":
                if brace_count == 0:
                    start_idx = i
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0 and start_idx >= 0:
                    end_idx = i + 1
                    break

        if start_idx >= 0 and end_idx > start_idx:
            json_str = text[start_idx:end_idx]
            try:
                return json.loads(json_str)
            except json.JSONDecodeError as e:
                logger.debug(f"Failed to parse extracted JSON: {e}")

        # Fallback: try regex for simpler pattern
        match = re.search(r"\{[^{}]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                pass

        logger.warning(f"Could not extract JSON from LLM response (length={len(text)})")
        return {}

    def _parse_response(
        self,
        result: dict,
        elapsed_ms: int,
    ) -> IndicationExtraction:
        """Parse LLM response into IndicationExtraction.

        Args:
            result: Parsed JSON from LLM.
            elapsed_ms: Response time in milliseconds.

        Returns:
            IndicationExtraction dataclass.
        """
        # Extract found indications
        found_indications = []

        # Check documented_indication
        doc_ind = result.get("documented_indication", {})
        if doc_ind.get("found") and doc_ind.get("indication"):
            found_indications.append(doc_ind["indication"])

        # Check overall_assessment
        overall = result.get("overall_assessment", {})
        if overall.get("indication_documented") and overall.get("primary_indication"):
            if overall["primary_indication"] not in found_indications:
                found_indications.append(overall["primary_indication"])

        # Get supporting quotes
        supporting_quotes = result.get("supporting_quotes", [])
        if isinstance(supporting_quotes, str):
            supporting_quotes = [supporting_quotes]

        # Determine confidence
        confidence = "LOW"
        if overall.get("confidence"):
            confidence = overall["confidence"].upper()
        elif doc_ind.get("confidence"):
            confidence = doc_ind["confidence"].upper()

        # Ensure confidence is valid
        if confidence not in ("HIGH", "MEDIUM", "LOW"):
            confidence = "LOW"

        return IndicationExtraction(
            found_indications=found_indications,
            supporting_quotes=supporting_quotes,
            confidence=confidence,
            model_used=self.model,
            prompt_version=self.PROMPT_VERSION,
            tokens_used=None,  # Ollama doesn't always report this
        )


def get_indication_extractor() -> IndicationExtractor | None:
    """Factory function to get configured indication extractor.

    Returns:
        IndicationExtractor if LLM is available, None otherwise.
    """
    extractor = IndicationExtractor()
    if extractor.is_available():
        return extractor

    logger.warning(
        f"LLM model {extractor.model} not available at {extractor.base_url}. "
        "Indication extraction will be skipped."
    )
    return None


def check_llm_availability() -> tuple[bool, str]:
    """Check if LLM is available for extraction.

    Returns:
        Tuple of (is_available, status_message).
    """
    extractor = IndicationExtractor()
    if extractor.is_available():
        return True, f"LLM available: {extractor.model} at {extractor.base_url}"
    return False, f"LLM not available: {extractor.model} at {extractor.base_url}"


if __name__ == "__main__":
    # Test LLM availability
    logging.basicConfig(level=logging.INFO)

    available, msg = check_llm_availability()
    print(msg)

    if available:
        extractor = IndicationExtractor()

        # Test extraction with sample notes
        test_notes = [
            """
            Assessment/Plan:
            1. Pneumonia - started on ceftriaxone for community-acquired pneumonia.
               Patient has fever, productive cough, and infiltrate on CXR.
               Will continue IV antibiotics and monitor response.
            """
        ]

        result = extractor.extract(test_notes, "Ceftriaxone")
        print(f"\nExtraction result:")
        print(f"  Found indications: {result.found_indications}")
        print(f"  Confidence: {result.confidence}")
        print(f"  Supporting quotes: {result.supporting_quotes}")
