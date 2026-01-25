"""CAUTI Classifier - Orchestrates extraction + rules for CAUTI classification.

Uses the extraction + rules architecture:
1. CAUTIExtractor extracts clinical facts from notes
2. CAUTIRulesEngine applies NHSN criteria deterministically

This classifier handles the orchestration and provides a consistent
interface with other HAI classifiers.
"""

import logging
from datetime import datetime, timedelta

from .base import BaseHAIClassifier
from ..config import Config
from ..models import HAICandidate, ClinicalNote, Classification, ClassificationDecision
from ..data.factory import get_note_source
from ..extraction.cauti_extractor import CAUTIExtractor
from ..rules.cauti_engine import CAUTIRulesEngine
from ..rules.cauti_schemas import (
    CAUTIClassification,
    CAUTIStructuredData,
    CAUTIClassificationResult,
)

logger = logging.getLogger(__name__)


class CAUTIClassifier(BaseHAIClassifier):
    """CAUTI classifier using extraction + rules architecture.

    Classification flow:
    1. Retrieve clinical notes for the patient
    2. Extract clinical facts using CAUTIExtractor (LLM)
    3. Build structured data from candidate
    4. Apply NHSN criteria using CAUTIRulesEngine
    5. Convert to Classification result
    """

    def __init__(
        self,
        note_source=None,
        extractor: CAUTIExtractor | None = None,
        rules_engine: CAUTIRulesEngine | None = None,
    ):
        """Initialize the classifier.

        Args:
            note_source: Source for clinical notes
            extractor: CAUTI extractor instance
            rules_engine: CAUTI rules engine instance
        """
        self.note_source = note_source or get_note_source()
        self.extractor = extractor or CAUTIExtractor()
        self.rules_engine = rules_engine or CAUTIRulesEngine()

        # Note retrieval configuration
        self.note_lookback_days = Config.NOTE_LOOKBACK_DAYS
        self.note_types = Config.NOTE_TYPES

    def classify(self, candidate: HAICandidate) -> Classification:
        """Classify a CAUTI candidate.

        Args:
            candidate: HAICandidate to classify

        Returns:
            Classification result
        """
        start_time = datetime.now()

        try:
            # Step 1: Get clinical notes
            notes = self._get_notes(candidate)
            logger.info(f"Retrieved {len(notes)} notes for candidate {candidate.id}")

            # Step 2: Extract clinical facts
            extraction = self.extractor.extract(candidate, notes)
            logger.debug(f"Extraction complete: {extraction.documentation_quality} quality")

            # Step 3: Build structured data
            structured_data = self._build_structured_data(candidate)

            # Step 4: Apply rules engine
            result = self.rules_engine.classify(extraction, structured_data)
            logger.info(
                f"CAUTI classification: {result.classification.value} "
                f"(confidence: {result.confidence:.2f})"
            )

            # Step 5: Convert to Classification
            classification = self._build_classification(
                candidate, result, extraction, start_time
            )

            # Store result on candidate for later use
            candidate._cauti_result = result
            candidate._cauti_extraction = extraction

            return classification

        except Exception as e:
            logger.error(f"Classification failed for candidate {candidate.id}: {e}")
            return self._error_classification(candidate, str(e), start_time)

    def _get_notes(self, candidate: HAICandidate) -> list[ClinicalNote]:
        """Retrieve clinical notes for the candidate.

        Gets notes from around the culture date, focusing on:
        - A few days before (for admission/baseline symptoms)
        - Day of culture
        - A few days after (for symptom documentation)
        """
        culture_date = candidate.culture.collection_date
        start_date = culture_date - timedelta(days=self.note_lookback_days)
        end_date = culture_date + timedelta(days=3)  # Few days after for symptoms

        return self.note_source.get_notes_for_patient(
            patient_id=candidate.patient.fhir_id,
            start_date=start_date,
            end_date=end_date,
            note_types=self.note_types,
        )

    def _build_structured_data(self, candidate: HAICandidate) -> CAUTIStructuredData:
        """Build structured data from candidate for rules engine.

        Extracts discrete data from the HAICandidate and CAUTI-specific data.
        """
        cauti_data = getattr(candidate, '_cauti_data', None)

        # Calculate patient age
        patient_age = None
        birth_date = None
        if candidate.patient.birth_date:
            try:
                birth_date_dt = datetime.fromisoformat(candidate.patient.birth_date)
                birth_date = birth_date_dt.date()
                age_delta = candidate.culture.collection_date - birth_date_dt
                patient_age = age_delta.days // 365
            except (ValueError, TypeError):
                pass

        # Get catheter info
        catheter_days = None
        catheter_type = None
        catheter_insertion = None
        catheter_removal = None

        if cauti_data:
            catheter_days = cauti_data.catheter_days
            catheter_type = cauti_data.catheter_episode.catheter_type
            catheter_insertion = cauti_data.catheter_episode.insertion_date
            catheter_removal = cauti_data.catheter_episode.removal_date
            if patient_age is None:
                patient_age = cauti_data.patient_age
        elif candidate.device_info:
            if candidate.device_info.insertion_date:
                catheter_days = candidate.device_days_at_culture
                catheter_type = candidate.device_info.device_type
                catheter_insertion = candidate.device_info.insertion_date
                catheter_removal = candidate.device_info.removal_date

        # Get culture info
        culture_cfu = None
        culture_organism = candidate.culture.organism
        culture_organism_count = 1  # Default to 1 if not specified

        if cauti_data:
            culture_cfu = cauti_data.culture_cfu_ml
            if cauti_data.culture_organism_count:
                culture_organism_count = cauti_data.culture_organism_count

        return CAUTIStructuredData(
            patient_id=candidate.patient.fhir_id,
            patient_age=patient_age,
            patient_birth_date=birth_date,
            catheter_insertion_date=catheter_insertion,
            catheter_removal_date=catheter_removal,
            catheter_type=catheter_type,
            catheter_days=catheter_days,
            culture_date=candidate.culture.collection_date,
            culture_cfu_ml=culture_cfu,
            culture_organism=culture_organism,
            culture_organism_count=culture_organism_count,
            culture_fhir_id=candidate.culture.fhir_id,
        )

    def _build_classification(
        self,
        candidate: HAICandidate,
        result: CAUTIClassificationResult,
        extraction,
        start_time: datetime,
    ) -> Classification:
        """Build Classification from rules engine result.

        Maps CAUTI classification to standard ClassificationDecision.
        """
        import uuid

        # Map CAUTI classification to decision
        if result.classification == CAUTIClassification.CAUTI:
            decision = ClassificationDecision.HAI_CONFIRMED
        elif result.classification == CAUTIClassification.NOT_ELIGIBLE:
            decision = ClassificationDecision.NOT_HAI
        elif result.classification == CAUTIClassification.NOT_CAUTI:
            decision = ClassificationDecision.NOT_HAI
        elif result.classification == CAUTIClassification.ASYMPTOMATIC_BACTERIURIA:
            # Asymptomatic bacteriuria needs review
            decision = ClassificationDecision.PENDING_REVIEW
        else:  # INDETERMINATE
            decision = ClassificationDecision.PENDING_REVIEW

        # Calculate processing time
        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)

        # Build reasoning text
        reasoning = "\n".join(result.reasoning)
        if result.requires_review:
            reasoning += f"\n\nReview reasons: {', '.join(result.review_reasons)}"

        return Classification(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            decision=decision,
            confidence=result.confidence,
            alternative_source=None,  # CAUTI doesn't track alternative sources same way
            is_mbi_lcbi=False,  # Not applicable to CAUTI
            supporting_evidence=[],  # Could be populated from extraction
            contradicting_evidence=[],
            reasoning=reasoning,
            model_used=Config.LLM_MODEL,
            prompt_version=self.extractor.prompt_version,
            processing_time_ms=processing_time,
        )

    def _error_classification(
        self,
        candidate: HAICandidate,
        error_message: str,
        start_time: datetime,
    ) -> Classification:
        """Create classification for error cases."""
        import uuid

        processing_time = int((datetime.now() - start_time).total_seconds() * 1000)

        return Classification(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            decision=ClassificationDecision.PENDING_REVIEW,
            confidence=0.0,
            reasoning=f"Classification error: {error_message}",
            model_used=Config.LLM_MODEL,
            prompt_version=self.extractor.prompt_version,
            processing_time_ms=processing_time,
        )
