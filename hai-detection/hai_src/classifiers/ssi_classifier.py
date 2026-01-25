"""SSI classification - extraction + rules architecture.

This classifier separates concerns:
1. LLM extracts clinical information (what's documented)
2. Rules engine applies NHSN SSI criteria (deterministic logic)

This provides transparent, auditable SSI classification for IP review.
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
)
from ..llm.factory import get_llm_client
from ..db import HAIDatabase
from ..extraction.ssi_extractor import SSIExtractor
from ..rules.ssi_engine import SSIRulesEngine
from ..rules.ssi_schemas import (
    SSIExtraction,
    SSIStructuredData,
    SSIClassification,
    SSIClassificationResult,
    SSIType,
)
from .base import BaseHAIClassifier

logger = logging.getLogger(__name__)


class SSIClassifierV2(BaseHAIClassifier):
    """SSI classifier using extraction + rules architecture.

    Pipeline:
        Notes → SSIExtractor (LLM) → SSIExtraction
        SSIExtraction + SSIStructuredData → SSIRulesEngine → SSIClassificationResult

    This separates LLM-based extraction from deterministic rules,
    making the system more transparent and maintainable.
    """

    PROMPT_VERSION = "ssi_extraction_v1"

    def __init__(
        self,
        llm_client=None,
        db: HAIDatabase | None = None,
        strict_mode: bool = True,
    ):
        """Initialize the classifier.

        Args:
            llm_client: LLM client for extraction. Uses factory default if None.
            db: Database for audit logging and structured data. Optional.
            strict_mode: If True, flag borderline cases for review.
        """
        self.extractor = SSIExtractor(llm_client=llm_client, db=db)
        self.rules_engine = SSIRulesEngine(strict_mode=strict_mode)
        self.db = db
        self._llm_client = llm_client

    @property
    def llm_client(self):
        """Get LLM client (from extractor)."""
        return self.extractor.llm_client

    @property
    def hai_type(self) -> str:
        return HAIType.SSI.value

    @property
    def prompt_version(self) -> str:
        return self.PROMPT_VERSION

    def classify(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        structured_data: SSIStructuredData | None = None,
    ) -> Classification:
        """Classify an SSI candidate using extraction + rules.

        Args:
            candidate: The SSI candidate
            notes: Clinical notes for context
            structured_data: Optional pre-built structured data. If not provided,
                           will be built from candidate info.

        Returns:
            Classification with decision, confidence, and reasoning
        """
        start_time = time.time()

        # Get SSI-specific data from candidate
        ssi_data = getattr(candidate, "_ssi_data", None)
        if ssi_data is None:
            logger.warning(f"No SSI data on candidate {candidate.id}")
            # Return low-confidence classification
            return Classification(
                id=str(uuid.uuid4()),
                candidate_id=candidate.id,
                decision=ClassificationDecision.PENDING_REVIEW,
                confidence=0.3,
                reasoning="No SSI procedure data available for classification",
                model_used=self.llm_client.model_name if self._llm_client else "unknown",
                prompt_version=self.prompt_version,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        # Step 1: Build structured data from candidate if not provided
        if structured_data is None:
            structured_data = self._build_structured_data(candidate, ssi_data)

        # Step 2: Extract clinical information using LLM
        extraction = self.extractor.extract(candidate, notes, ssi_data.procedure)

        # Step 3: Apply rules engine
        rules_result = self.rules_engine.classify(extraction, structured_data)

        # Step 4: Convert to Classification model
        elapsed_ms = int((time.time() - start_time) * 1000)
        classification = self._build_classification(
            candidate, extraction, rules_result, elapsed_ms
        )

        return classification

    def _build_structured_data(
        self,
        candidate: HAICandidate,
        ssi_data,
    ) -> SSIStructuredData:
        """Build SSIStructuredData from HAICandidate and SSI data.

        This extracts the discrete/structured information that comes from
        the EHR (not from clinical notes).
        """
        procedure = ssi_data.procedure

        return SSIStructuredData(
            procedure_code=procedure.procedure_code,
            procedure_name=procedure.procedure_name,
            nhsn_category=procedure.nhsn_category or "Unknown",
            procedure_date=procedure.procedure_date,
            wound_class=procedure.wound_class,
            implant_used=procedure.implant_used,
            implant_type=procedure.implant_type,
            days_post_op=ssi_data.days_post_op,
            surveillance_window_days=procedure.get_surveillance_days(),
            wound_culture_positive=bool(ssi_data.wound_culture_organism),
            wound_culture_date=ssi_data.wound_culture_date,
            wound_culture_organism=ssi_data.wound_culture_organism,
        )

    def _build_classification(
        self,
        candidate: HAICandidate,
        extraction: SSIExtraction,
        rules_result: SSIClassificationResult,
        elapsed_ms: int,
    ) -> Classification:
        """Convert rules engine result to Classification model."""

        # Map rules classification to Classification decision
        decision = self._map_classification_to_decision(rules_result.classification)

        # Build supporting evidence from extraction
        supporting = []
        contradicting = []

        # Helper to format source attribution
        def format_source(source_obj) -> str:
            """Format EvidenceSource object to readable string."""
            if source_obj is None:
                return "clinical notes"
            parts = []
            if source_obj.note_type:
                parts.append(source_obj.note_type)
            if source_obj.note_date:
                parts.append(source_obj.note_date)
            if source_obj.author:
                parts.append(source_obj.author)
            return ": ".join(parts) if parts else "clinical notes"

        # Add wound assessment findings as evidence
        for wa in extraction.wound_assessments:
            if wa.drainage_present.value in ["definite", "probable"]:
                drainage_text = f"Drainage: {wa.drainage_type or 'present'}"
                if wa.drainage_amount:
                    drainage_text += f" ({wa.drainage_amount})"
                supporting.append(SupportingEvidence(
                    text=drainage_text,
                    source=format_source(wa.drainage_source),
                    relevance="Wound drainage supports SSI",
                ))

            if wa.wound_dehisced.value in ["definite", "probable"]:
                supporting.append(SupportingEvidence(
                    text=f"Wound dehiscence: {wa.dehiscence_type or 'documented'}",
                    source=format_source(wa.dehiscence_source),
                    relevance="Dehiscence may indicate deep SSI",
                ))

        # Add superficial SSI findings
        sup = extraction.superficial_findings
        if sup.purulent_drainage_superficial.value in ["definite", "probable"]:
            text = sup.purulent_drainage_quote or "Purulent drainage from superficial incision"
            supporting.append(SupportingEvidence(
                text=text,
                source=format_source(sup.purulent_drainage_source),
                relevance="NHSN Superficial SSI criterion",
            ))

        if sup.organisms_from_superficial_culture.value in ["definite", "probable"]:
            organism = sup.organism_identified or "organism identified"
            supporting.append(SupportingEvidence(
                text=f"Positive wound culture: {organism}",
                source=format_source(sup.culture_source),
                relevance="NHSN Superficial SSI criterion - positive culture",
            ))

        # Add deep SSI findings
        deep = extraction.deep_findings
        if deep.purulent_drainage_deep.value in ["definite", "probable"]:
            text = deep.purulent_drainage_quote or "Purulent drainage from deep incision"
            supporting.append(SupportingEvidence(
                text=text,
                source=format_source(deep.purulent_drainage_source),
                relevance="NHSN Deep SSI criterion",
            ))

        if deep.abscess_on_imaging.value in ["definite", "probable"]:
            imaging = deep.imaging_type or "imaging"
            supporting.append(SupportingEvidence(
                text=f"Abscess seen on {imaging}",
                source=format_source(deep.abscess_source),
                relevance="NHSN Deep SSI criterion - abscess on imaging",
            ))

        # Add organ/space findings
        os = extraction.organ_space_findings
        if os.organisms_from_organ_space.value in ["definite", "probable"]:
            organism = os.organism_identified or "organism identified"
            specimen = os.specimen_type or "organ/space specimen"
            supporting.append(SupportingEvidence(
                text=f"Positive culture from {specimen}: {organism}",
                source=format_source(os.culture_source),
                relevance="NHSN Organ/Space SSI criterion",
            ))

        if os.abscess_on_imaging.value in ["definite", "probable"]:
            imaging = os.imaging_type or "imaging"
            findings = os.imaging_findings or "abscess"
            supporting.append(SupportingEvidence(
                text=f"{imaging}: {findings}",
                source=format_source(os.abscess_source),
                relevance="NHSN Organ/Space SSI criterion - abscess",
            ))

        # Add reoperation findings
        reop = extraction.reoperation
        if reop.reoperation_performed.value in ["definite", "probable"]:
            indication = reop.reoperation_indication or "infection-related"
            supporting.append(SupportingEvidence(
                text=f"Reoperation for {indication}",
                source=format_source(reop.reoperation_source),
                relevance="Reoperation may indicate SSI",
            ))

        # Add contradicting evidence if NOT SSI
        if rules_result.classification == SSIClassification.NOT_SSI:
            if extraction.antibiotics_for_wound_infection.value == "not_found":
                contradicting.append(SupportingEvidence(
                    text="No antibiotics documented for wound infection",
                    source="clinical notes",
                    relevance="Absence of treatment suggests no SSI",
                ))

        # Build reasoning string - SSI-specific
        reasoning_parts = []

        # Add SSI type information
        if rules_result.ssi_type:
            reasoning_parts.append(f"SSI Type: {rules_result.ssi_type.value.replace('_', ' ').title()}")

        # Add eligibility checks
        if rules_result.eligibility_checks:
            reasoning_parts.append("Eligibility:")
            for check in rules_result.eligibility_checks:
                reasoning_parts.append(f"  - {check}")

        # Add criteria met for each SSI type
        if rules_result.superficial_criteria_met:
            reasoning_parts.append("Superficial SSI criteria:")
            for c in rules_result.superficial_criteria_met:
                reasoning_parts.append(f"  - {c}")

        if rules_result.deep_criteria_met:
            reasoning_parts.append("Deep SSI criteria:")
            for c in rules_result.deep_criteria_met:
                reasoning_parts.append(f"  - {c}")

        if rules_result.organ_space_criteria_met:
            reasoning_parts.append("Organ/Space SSI criteria:")
            for c in rules_result.organ_space_criteria_met:
                reasoning_parts.append(f"  - {c}")

        # Add general reasoning
        if rules_result.reasoning:
            reasoning_parts.extend(rules_result.reasoning)

        if rules_result.review_reasons:
            reasoning_parts.append("Review flags:")
            for r in rules_result.review_reasons:
                reasoning_parts.append(f"  - {r}")

        reasoning = "\n".join(reasoning_parts)

        return Classification(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            decision=decision,
            confidence=rules_result.confidence,
            alternative_source=None,  # SSI doesn't have alternate sources like CLABSI
            is_mbi_lcbi=False,  # Not applicable to SSI
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            reasoning=reasoning,
            model_used=self.llm_client.model_name,
            prompt_version=self.prompt_version,
            processing_time_ms=elapsed_ms,
        )

    def _map_classification_to_decision(
        self,
        classification: SSIClassification,
    ) -> ClassificationDecision:
        """Map rules engine classification to Classification decision."""
        mapping = {
            SSIClassification.SUPERFICIAL_SSI: ClassificationDecision.HAI_CONFIRMED,
            SSIClassification.DEEP_SSI: ClassificationDecision.HAI_CONFIRMED,
            SSIClassification.ORGAN_SPACE_SSI: ClassificationDecision.HAI_CONFIRMED,
            SSIClassification.NOT_SSI: ClassificationDecision.NOT_HAI,
            SSIClassification.NOT_ELIGIBLE: ClassificationDecision.NOT_HAI,
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
        ssi_data = getattr(candidate, "_ssi_data", None)
        procedure = ssi_data.procedure if ssi_data else None
        return self.extractor._build_prompt(candidate, notes, procedure)

    def extract_only(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> SSIExtraction:
        """Run extraction only, without rules classification.

        Useful for debugging or when you want to inspect the extraction
        before applying rules.

        Args:
            candidate: The SSI candidate
            notes: Clinical notes

        Returns:
            SSIExtraction from LLM
        """
        ssi_data = getattr(candidate, "_ssi_data", None)
        procedure = ssi_data.procedure if ssi_data else None
        return self.extractor.extract(candidate, notes, procedure)

    def classify_with_extraction(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        structured_data: SSIStructuredData | None = None,
    ) -> tuple[Classification, SSIExtraction, SSIClassificationResult]:
        """Classify and return all intermediate results.

        Useful for debugging and understanding how the classification
        was made.

        Args:
            candidate: The SSI candidate
            notes: Clinical notes
            structured_data: Optional pre-built structured data

        Returns:
            Tuple of (Classification, SSIExtraction, SSIClassificationResult)
        """
        start_time = time.time()

        ssi_data = getattr(candidate, "_ssi_data", None)
        if ssi_data is None:
            raise ValueError("No SSI data on candidate")

        if structured_data is None:
            structured_data = self._build_structured_data(candidate, ssi_data)

        extraction = self.extractor.extract(candidate, notes, ssi_data.procedure)
        rules_result = self.rules_engine.classify(extraction, structured_data)

        elapsed_ms = int((time.time() - start_time) * 1000)
        classification = self._build_classification(
            candidate, extraction, rules_result, elapsed_ms
        )

        return classification, extraction, rules_result
