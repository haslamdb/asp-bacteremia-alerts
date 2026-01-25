"""VAE classification - extraction + rules architecture.

This classifier separates concerns:
1. LLM extracts clinical information (what's documented)
2. Rules engine applies NHSN VAE criteria (deterministic logic)

This provides transparent, auditable VAE classification for IP review.

NHSN VAE Hierarchy:
- VAC: Detected by candidate detector (FiO2/PEEP worsening)
- IVAC: VAC + fever/WBC + new antimicrobials ≥4 days
- Possible VAP: IVAC + purulent secretions OR positive culture
- Probable VAP: IVAC + purulent secretions + positive quantitative culture
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
    VAECandidate,
)
from ..llm.factory import get_llm_client
from ..db import HAIDatabase
from ..extraction.vae_extractor import VAEExtractor
from ..rules.vae_engine import VAERulesEngine
from ..rules.vae_schemas import (
    VAEExtraction,
    VAEStructuredData,
    VAEClassification,
    VAETier,
    VAEClassificationResult,
)
from .base import BaseHAIClassifier

logger = logging.getLogger(__name__)


class VAEClassifier(BaseHAIClassifier):
    """VAE classifier using extraction + rules architecture.

    Pipeline:
        Notes → VAEExtractor (LLM) → VAEExtraction
        VAEExtraction + VAEStructuredData → VAERulesEngine → VAEClassificationResult

    This separates LLM-based extraction from deterministic rules,
    making the system more transparent and maintainable.
    """

    PROMPT_VERSION = "vae_extraction_v1"

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
        self.extractor = VAEExtractor(llm_client=llm_client, db=db)
        self.rules_engine = VAERulesEngine(strict_mode=strict_mode)
        self.db = db
        self._llm_client = llm_client

    @property
    def llm_client(self):
        """Get LLM client (from extractor)."""
        return self.extractor.llm_client

    @property
    def hai_type(self) -> str:
        return HAIType.VAE.value

    @property
    def prompt_version(self) -> str:
        return self.PROMPT_VERSION

    def classify(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        structured_data: VAEStructuredData | None = None,
    ) -> Classification:
        """Classify a VAE candidate using extraction + rules.

        Args:
            candidate: The VAE candidate
            notes: Clinical notes for context
            structured_data: Optional pre-built structured data. If not provided,
                           will be built from candidate info.

        Returns:
            Classification with decision, confidence, and reasoning
        """
        start_time = time.time()

        # Get VAE-specific data from candidate
        vae_data = getattr(candidate, "_vae_data", None)
        if vae_data is None:
            logger.warning(f"No VAE data on candidate {candidate.id}")
            # Return low-confidence classification
            return Classification(
                id=str(uuid.uuid4()),
                candidate_id=candidate.id,
                decision=ClassificationDecision.PENDING_REVIEW,
                confidence=0.3,
                reasoning="No VAE data available for classification",
                model_used=self.llm_client.model_name if self._llm_client else "unknown",
                prompt_version=self.prompt_version,
                processing_time_ms=int((time.time() - start_time) * 1000),
            )

        # Step 1: Build structured data from candidate if not provided
        if structured_data is None:
            structured_data = self._build_structured_data(candidate, vae_data)

        # Step 2: Extract clinical information using LLM
        extraction = self.extractor.extract(candidate, notes, vae_data)

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
        vae_data: VAECandidate,
    ) -> VAEStructuredData:
        """Build VAEStructuredData from HAICandidate and VAE data.

        This extracts the discrete/structured information that comes from
        the EHR (not from clinical notes).
        """
        episode = vae_data.episode

        return VAEStructuredData(
            patient_id=candidate.patient.fhir_id,
            intubation_date=episode.intubation_date,
            extubation_date=episode.extubation_date,
            ventilator_days=episode.get_ventilator_days(),
            vac_onset_date=vae_data.vac_onset_date,
            baseline_period_start=vae_data.baseline_start_date,
            baseline_period_end=vae_data.baseline_end_date,
            baseline_min_fio2=vae_data.baseline_min_fio2,
            baseline_min_peep=vae_data.baseline_min_peep,
            worsening_start_date=vae_data.worsening_start_date,
            fio2_increase=vae_data.fio2_increase,
            peep_increase=vae_data.peep_increase,
            location_at_vac=episode.location_code,
        )

    def _build_classification(
        self,
        candidate: HAICandidate,
        extraction: VAEExtraction,
        rules_result: VAEClassificationResult,
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

        # Add temperature findings as evidence
        temp = extraction.temperature
        if temp.fever_documented.value in ["definite", "probable"]:
            temp_text = f"Fever: {temp.max_temp_celsius}°C" if temp.max_temp_celsius else "Fever documented"
            supporting.append(SupportingEvidence(
                text=temp_text,
                source=format_source(temp.fever_source),
                relevance="IVAC temperature criterion",
            ))

        if temp.hypothermia_documented.value in ["definite", "probable"]:
            temp_text = f"Hypothermia: {temp.min_temp_celsius}°C" if temp.min_temp_celsius else "Hypothermia documented"
            supporting.append(SupportingEvidence(
                text=temp_text,
                source=format_source(temp.hypothermia_source),
                relevance="IVAC temperature criterion",
            ))

        # Add WBC findings
        wbc = extraction.wbc
        if wbc.leukocytosis_documented.value in ["definite", "probable"]:
            wbc_text = f"Leukocytosis: {wbc.max_wbc}" if wbc.max_wbc else "Leukocytosis documented"
            supporting.append(SupportingEvidence(
                text=wbc_text,
                source=format_source(wbc.leukocytosis_source),
                relevance="IVAC WBC criterion",
            ))

        if wbc.leukopenia_documented.value in ["definite", "probable"]:
            wbc_text = f"Leukopenia: {wbc.min_wbc}" if wbc.min_wbc else "Leukopenia documented"
            supporting.append(SupportingEvidence(
                text=wbc_text,
                source=format_source(wbc.leukopenia_source),
                relevance="IVAC WBC criterion",
            ))

        # Add antimicrobial findings
        for abx in extraction.antimicrobials:
            if abx.new_antimicrobial_started.value in ["definite", "probable"]:
                drug_names = ", ".join(abx.antimicrobial_names) if abx.antimicrobial_names else "antimicrobial"
                indication = f" for {abx.indication}" if abx.indication else ""
                duration = f" ({abx.duration_days} days)" if abx.duration_days else ""
                supporting.append(SupportingEvidence(
                    text=f"New antimicrobial: {drug_names}{indication}{duration}",
                    source=format_source(abx.source),
                    relevance="IVAC antimicrobial criterion",
                ))

        # Add secretion findings
        sec = extraction.secretions
        if sec.purulent_secretions.value in ["definite", "probable"]:
            sec_text = sec.secretion_description or "Purulent secretions"
            supporting.append(SupportingEvidence(
                text=sec_text,
                source=format_source(sec.source),
                relevance="VAP purulent secretions criterion",
            ))

        # Add culture findings
        for cx in extraction.cultures:
            if cx.culture_positive.value in ["definite", "probable"]:
                cx_text = f"Positive culture: {cx.organism_identified or 'organism'}"
                cx_text += f" from {cx.specimen_type}" if cx.specimen_type else ""
                if cx.colony_count:
                    cx_text += f" ({cx.colony_count})"
                supporting.append(SupportingEvidence(
                    text=cx_text,
                    source=format_source(cx.source),
                    relevance="VAP culture criterion",
                ))

        # Add ventilator status findings
        vent = extraction.ventilator_status
        if vent.increased_fio2_documented.value in ["definite", "probable"]:
            supporting.append(SupportingEvidence(
                text="Increased FiO2 documented",
                source=format_source(vent.source),
                relevance="VAC respiratory deterioration",
            ))

        if vent.increased_peep_documented.value in ["definite", "probable"]:
            supporting.append(SupportingEvidence(
                text="Increased PEEP documented",
                source=format_source(vent.source),
                relevance="VAC respiratory deterioration",
            ))

        # Add contradicting evidence if NOT VAE
        if rules_result.classification == VAEClassification.NOT_VAE:
            if extraction.alternative_diagnoses:
                for dx in extraction.alternative_diagnoses:
                    contradicting.append(SupportingEvidence(
                        text=f"Alternative diagnosis considered: {dx}",
                        source="clinical notes",
                        relevance="Non-infectious cause of respiratory deterioration",
                    ))

        # Build reasoning string - VAE-specific
        reasoning_parts = []

        # Add VAE classification tier
        if rules_result.vae_tier:
            tier_names = {
                VAETier.TIER_1: "Tier 1 (VAC)",
                VAETier.TIER_2: "Tier 2 (IVAC)",
                VAETier.TIER_3: "Tier 3 (VAP)",
            }
            reasoning_parts.append(f"VAE Classification: {tier_names.get(rules_result.vae_tier, 'Unknown')}")

        # Add VAC details
        if rules_result.vac_met:
            reasoning_parts.append("VAC Criteria:")
            if rules_result.vac_onset_date:
                reasoning_parts.append(f"  - Onset date: {rules_result.vac_onset_date}")
            if rules_result.baseline_period:
                reasoning_parts.append(f"  - Baseline period: {rules_result.baseline_period}")
            if rules_result.fio2_increase_details:
                reasoning_parts.append(f"  - FiO2: {rules_result.fio2_increase_details}")
            if rules_result.peep_increase_details:
                reasoning_parts.append(f"  - PEEP: {rules_result.peep_increase_details}")

        # Add IVAC details
        if rules_result.ivac_met:
            reasoning_parts.append("IVAC Criteria:")
            if rules_result.temperature_criterion_met:
                reasoning_parts.append("  - Temperature criterion met")
            if rules_result.wbc_criterion_met:
                reasoning_parts.append("  - WBC criterion met")
            if rules_result.antimicrobial_criterion_met:
                abx = ", ".join(rules_result.qualifying_antimicrobials) if rules_result.qualifying_antimicrobials else "antimicrobials"
                reasoning_parts.append(f"  - Antimicrobial criterion met: {abx}")

        # Add VAP details
        if rules_result.vap_met:
            reasoning_parts.append("VAP Criteria:")
            if rules_result.purulent_secretions_met:
                reasoning_parts.append("  - Purulent secretions documented")
            if rules_result.positive_culture_met:
                organism = rules_result.organism_identified or "organism"
                specimen = rules_result.specimen_type or "respiratory specimen"
                reasoning_parts.append(f"  - Positive culture: {organism} from {specimen}")
            if rules_result.quantitative_threshold_met:
                reasoning_parts.append("  - Quantitative culture threshold met")

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
            alternative_source=None,  # VAE doesn't have alternate sources like CLABSI
            is_mbi_lcbi=False,  # Not applicable to VAE
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            reasoning=reasoning,
            model_used=self.llm_client.model_name,
            prompt_version=self.prompt_version,
            processing_time_ms=elapsed_ms,
        )

    def _map_classification_to_decision(
        self,
        classification: VAEClassification,
    ) -> ClassificationDecision:
        """Map rules engine classification to Classification decision."""
        mapping = {
            VAEClassification.PROBABLE_VAP: ClassificationDecision.HAI_CONFIRMED,
            VAEClassification.POSSIBLE_VAP: ClassificationDecision.HAI_CONFIRMED,
            VAEClassification.IVAC: ClassificationDecision.HAI_CONFIRMED,
            VAEClassification.VAC: ClassificationDecision.HAI_CONFIRMED,
            VAEClassification.NOT_VAE: ClassificationDecision.NOT_HAI,
            VAEClassification.NOT_ELIGIBLE: ClassificationDecision.NOT_HAI,
            VAEClassification.INDETERMINATE: ClassificationDecision.PENDING_REVIEW,
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
        vae_data = getattr(candidate, "_vae_data", None)
        return self.extractor._build_prompt(candidate, notes, vae_data)

    def extract_only(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> VAEExtraction:
        """Run extraction only, without rules classification.

        Useful for debugging or when you want to inspect the extraction
        before applying rules.

        Args:
            candidate: The VAE candidate
            notes: Clinical notes

        Returns:
            VAEExtraction from LLM
        """
        vae_data = getattr(candidate, "_vae_data", None)
        return self.extractor.extract(candidate, notes, vae_data)

    def classify_with_extraction(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        structured_data: VAEStructuredData | None = None,
    ) -> tuple[Classification, VAEExtraction, VAEClassificationResult]:
        """Classify and return all intermediate results.

        Useful for debugging and understanding how the classification
        was made.

        Args:
            candidate: The VAE candidate
            notes: Clinical notes
            structured_data: Optional pre-built structured data

        Returns:
            Tuple of (Classification, VAEExtraction, VAEClassificationResult)
        """
        start_time = time.time()

        vae_data = getattr(candidate, "_vae_data", None)
        if vae_data is None:
            raise ValueError("No VAE data on candidate")

        if structured_data is None:
            structured_data = self._build_structured_data(candidate, vae_data)

        extraction = self.extractor.extract(candidate, notes, vae_data)
        rules_result = self.rules_engine.classify(extraction, structured_data)

        elapsed_ms = int((time.time() - start_time) * 1000)
        classification = self._build_classification(
            candidate, extraction, rules_result, elapsed_ms
        )

        return classification, extraction, rules_result
