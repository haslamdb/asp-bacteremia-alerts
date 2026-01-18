"""CLABSI classification v2 - extraction + rules architecture.

This classifier separates concerns:
1. LLM extracts clinical information (what's documented)
2. Rules engine applies NHSN criteria (deterministic logic)

This approach provides:
- Transparent, auditable decision making
- Easy updates when NHSN criteria change
- Testable rules independent of LLM
- Better explainability for IP review
"""

import logging
import time
import uuid
from datetime import datetime

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
from ..db import NHSNDatabase
from ..extraction import CLABSIExtractor
from ..rules import (
    CLABSIRulesEngine,
    ClinicalExtraction,
    StructuredCaseData,
    CLABSIClassification,
    ClassificationResult,
)
from .base import BaseHAIClassifier

logger = logging.getLogger(__name__)


class CLABSIClassifierV2(BaseHAIClassifier):
    """CLABSI classifier using extraction + rules architecture.

    Pipeline:
        Notes → CLABSIExtractor (LLM) → ClinicalExtraction
        ClinicalExtraction + StructuredCaseData → CLABSIRulesEngine → Classification

    This version separates LLM-based extraction from deterministic rules,
    making the system more transparent and maintainable.
    """

    PROMPT_VERSION = "clabsi_extraction_v1"

    def __init__(
        self,
        llm_client=None,
        db: NHSNDatabase | None = None,
        strict_mode: bool = True,
    ):
        """Initialize the classifier.

        Args:
            llm_client: LLM client for extraction. Uses factory default if None.
            db: Database for audit logging and structured data. Optional.
            strict_mode: If True, flag borderline cases for review.
        """
        self.extractor = CLABSIExtractor(llm_client=llm_client, db=db)
        self.rules_engine = CLABSIRulesEngine(strict_mode=strict_mode)
        self.db = db
        self._llm_client = llm_client

    @property
    def llm_client(self):
        """Get LLM client (from extractor)."""
        return self.extractor.llm_client

    @property
    def hai_type(self) -> str:
        return HAIType.CLABSI.value

    @property
    def prompt_version(self) -> str:
        return self.PROMPT_VERSION

    def classify(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        structured_data: StructuredCaseData | None = None,
    ) -> Classification:
        """Classify a CLABSI candidate using extraction + rules.

        Args:
            candidate: The CLABSI candidate
            notes: Clinical notes for context
            structured_data: Optional pre-built structured data. If not provided,
                           will be built from candidate info.

        Returns:
            Classification with decision, confidence, and reasoning
        """
        start_time = time.time()

        # Step 1: Build structured data from candidate if not provided
        if structured_data is None:
            structured_data = self._build_structured_data(candidate)

        # Step 2: Extract clinical information using LLM
        extraction = self.extractor.extract(candidate, notes)

        # Step 3: Apply rules engine
        rules_result = self.rules_engine.classify(extraction, structured_data)

        # Step 4: Convert to Classification model
        elapsed_ms = int((time.time() - start_time) * 1000)
        classification = self._build_classification(
            candidate, extraction, rules_result, elapsed_ms
        )

        return classification

    def _build_structured_data(self, candidate: HAICandidate) -> StructuredCaseData:
        """Build StructuredCaseData from HAICandidate.

        This extracts the discrete/structured information that comes from
        the EHR (not from clinical notes).
        """
        device_info = candidate.device_info

        return StructuredCaseData(
            organism=candidate.culture.organism or "Unknown",
            culture_date=candidate.culture.collection_date,
            specimen_source="blood",
            line_present=device_info is not None,
            line_type=device_info.device_type if device_info else None,
            line_insertion_date=device_info.insertion_date if device_info else None,
            line_removal_date=device_info.removal_date if device_info else None,
            line_days_at_culture=candidate.device_days_at_culture,
            # These would come from additional EHR queries in production:
            has_second_culture_match=False,  # TODO: Query for matching cultures
            admission_date=None,  # TODO: Get from encounter
            patient_days_at_culture=None,  # TODO: Calculate
            location_at_culture=candidate.patient.location,
            anc_values_7_days=[],  # TODO: Query labs
            is_transplant_patient=False,  # TODO: Query registry
        )

    def _build_classification(
        self,
        candidate: HAICandidate,
        extraction: ClinicalExtraction,
        rules_result: ClassificationResult,
        elapsed_ms: int,
    ) -> Classification:
        """Convert rules engine result to Classification model."""

        # Map rules classification to Classification decision
        decision = self._map_classification_to_decision(rules_result.classification)

        # Build supporting evidence from extraction
        supporting = []
        contradicting = []

        # Add alternate sources as contradicting evidence for CLABSI
        for alt_site in extraction.alternate_infection_sites:
            if alt_site.confidence.value in ["definite", "probable"]:
                contradicting.append(SupportingEvidence(
                    text=alt_site.supporting_quote,
                    source=f"alternate_source_{alt_site.site}",
                    relevance=f"Possible alternate source: {alt_site.site}",
                ))

        # Add line assessment as supporting evidence
        line = extraction.line_assessment
        if line.line_infection_suspected.value in ["definite", "probable"]:
            supporting.append(SupportingEvidence(
                text="Line infection suspected by clinical team",
                source="line_assessment",
                relevance="Supports CLABSI attribution",
            ))

        # Determine alternative source
        alternative_source = None
        if rules_result.classification == CLABSIClassification.SECONDARY_BSI:
            if extraction.alternate_infection_sites:
                alternative_source = extraction.alternate_infection_sites[0].site
        elif rules_result.classification == CLABSIClassification.MBI_LCBI:
            alternative_source = "MBI-LCBI (mucosal barrier injury)"

        # Build reasoning string
        reasoning = "\n".join(rules_result.reasoning)
        if rules_result.review_reasons:
            reasoning += "\n\nReview flags:\n- " + "\n- ".join(rules_result.review_reasons)

        return Classification(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            decision=decision,
            confidence=rules_result.confidence,
            alternative_source=alternative_source,
            is_mbi_lcbi=(rules_result.classification == CLABSIClassification.MBI_LCBI),
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            reasoning=reasoning,
            model_used=self.llm_client.model_name,
            prompt_version=self.prompt_version,
            processing_time_ms=elapsed_ms,
        )

    def _map_classification_to_decision(
        self,
        classification: CLABSIClassification,
    ) -> ClassificationDecision:
        """Map rules engine classification to Classification decision."""
        mapping = {
            CLABSIClassification.CLABSI: ClassificationDecision.HAI_CONFIRMED,
            CLABSIClassification.MBI_LCBI: ClassificationDecision.NOT_HAI,  # MBI-LCBI is not CLABSI
            CLABSIClassification.SECONDARY_BSI: ClassificationDecision.NOT_HAI,
            CLABSIClassification.CONTAMINATION: ClassificationDecision.NOT_HAI,
            CLABSIClassification.NOT_ELIGIBLE: ClassificationDecision.NOT_HAI,
            CLABSIClassification.INDETERMINATE: ClassificationDecision.PENDING_REVIEW,
        }
        return mapping.get(classification, ClassificationDecision.PENDING_REVIEW)

    def build_prompt(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> str:
        """Build the extraction prompt.

        Note: This classifier uses extraction + rules, not a single classification
        prompt. This method returns the extraction prompt for compatibility with
        the base class interface.
        """
        return self.extractor._build_prompt(candidate, notes)

    def extract_only(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> ClinicalExtraction:
        """Run extraction only, without rules classification.

        Useful for debugging or when you want to inspect the extraction
        before applying rules.

        Args:
            candidate: The CLABSI candidate
            notes: Clinical notes

        Returns:
            ClinicalExtraction from LLM
        """
        return self.extractor.extract(candidate, notes)

    def classify_with_extraction(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        structured_data: StructuredCaseData | None = None,
    ) -> tuple[Classification, ClinicalExtraction, ClassificationResult]:
        """Classify and return all intermediate results.

        Useful for debugging and understanding how the classification
        was made.

        Args:
            candidate: The CLABSI candidate
            notes: Clinical notes
            structured_data: Optional pre-built structured data

        Returns:
            Tuple of (Classification, ClinicalExtraction, ClassificationResult)
        """
        start_time = time.time()

        if structured_data is None:
            structured_data = self._build_structured_data(candidate)

        extraction = self.extractor.extract(candidate, notes)
        rules_result = self.rules_engine.classify(extraction, structured_data)

        elapsed_ms = int((time.time() - start_time) * 1000)
        classification = self._build_classification(
            candidate, extraction, rules_result, elapsed_ms
        )

        return classification, extraction, rules_result
