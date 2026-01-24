"""CDI (Clostridioides difficile Infection) Classifier.

Orchestrates the CDI classification pipeline:
1. Retrieve clinical notes for the candidate
2. LLM extraction of clinical facts
3. Rules engine application of NHSN criteria
4. Return final classification

CDI classification is fundamentally different from device-associated HAIs:
- Classification is primarily time-based (specimen day)
- No device tracking required
- Simpler extraction (diarrhea usually implied)
- Recurrence tracking is critical
"""

import logging
from datetime import datetime, timedelta

from .base import BaseHAIClassifier
from ..models import HAICandidate, ClinicalNote, Classification, ClassificationDecision
from ..extraction.cdi_extractor import CDIExtractor
from ..rules.cdi_engine import CDIRulesEngine
from ..rules.cdi_schemas import CDIClassification, CDIStructuredData, CDIPriorEpisode

logger = logging.getLogger(__name__)


class CDIClassifier(BaseHAIClassifier):
    """Classifier for CDI LabID events.

    Pipeline:
    1. Get clinical notes (progress notes, GI consult, ID consult)
    2. Extract clinical facts using LLM
    3. Build structured data from candidate
    4. Apply NHSN CDI criteria via rules engine
    5. Return Classification result
    """

    # Note types relevant to CDI assessment
    RELEVANT_NOTE_TYPES = [
        "progress_note",
        "h_and_p",
        "id_consult",       # Infectious disease consult
        "gi_consult",       # GI consult
        "discharge_summary",
    ]

    def __init__(
        self,
        note_source=None,
        extractor: CDIExtractor | None = None,
        rules_engine: CDIRulesEngine | None = None,
        db=None,
    ):
        """Initialize the CDI classifier.

        Args:
            note_source: Source for retrieving clinical notes.
            extractor: CDI clinical fact extractor.
            rules_engine: NHSN CDI rules engine.
            db: Database for storing classifications.
        """
        self.note_source = note_source
        self.extractor = extractor or CDIExtractor()
        self.rules_engine = rules_engine or CDIRulesEngine()
        self.db = db

    def classify(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote] | None = None,
    ) -> Classification:
        """Classify a CDI candidate.

        Args:
            candidate: The CDI candidate to classify
            notes: Pre-fetched notes, or None to fetch automatically

        Returns:
            Classification with decision, confidence, and reasoning
        """
        import uuid

        logger.info(f"Classifying CDI candidate {candidate.id[:8]}...")

        # Step 1: Get clinical notes if not provided
        if notes is None:
            notes = self._get_notes_for_candidate(candidate)

        logger.debug(f"Found {len(notes)} relevant notes")

        # Step 2: Extract clinical facts using LLM
        extraction = self.extractor.extract(candidate, notes)

        logger.debug(
            f"Extraction: diarrhea={extraction.diarrhea.diarrhea_documented.value}, "
            f"treatment={extraction.treatment.treatment_initiated.value}, "
            f"quality={extraction.documentation_quality}"
        )

        # Step 3: Build structured data from candidate
        structured_data = self._build_structured_data(candidate)

        # Step 4: Apply rules engine
        result = self.rules_engine.classify(extraction, structured_data)

        logger.info(
            f"CDI classification: {result.classification.value}, "
            f"confidence={result.confidence:.2f}, "
            f"onset={result.onset_type}, "
            f"recurrent={result.is_recurrent}"
        )

        # Step 5: Map to Classification
        decision = self._map_decision(result.classification)

        # Build supporting/contradicting evidence
        supporting = []
        contradicting = []

        if result.test_positive:
            supporting.append(f"Positive {result.test_type} test")
        if result.specimen_day:
            supporting.append(f"Specimen day {result.specimen_day}")
        if result.diarrhea_documented:
            supporting.append("Diarrhea documented")
        if result.treatment_initiated:
            supporting.append(f"CDI treatment initiated ({result.treatment_type or 'unspecified'})")
        if result.is_recurrent:
            supporting.append(f"Recurrent episode ({result.days_since_last_cdi} days since last)")

        for reason in result.review_reasons:
            contradicting.append(reason)

        # Create Classification object
        classification = Classification(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            decision=decision,
            confidence=result.confidence,
            reasoning=result.reasoning,
            supporting_evidence=supporting,
            contradicting_evidence=contradicting,
            extraction_data=extraction.to_dict(),
            rules_result=result.to_dict(),
            created_at=datetime.now(),
        )

        # Update candidate's CDI data with classification
        cdi_data = getattr(candidate, "_cdi_data", None)
        if cdi_data:
            cdi_data.classification = result.classification.value
            cdi_data.diarrhea_documented = result.diarrhea_documented
            cdi_data.treatment_initiated = result.treatment_initiated
            cdi_data.treatment_type = result.treatment_type

        return classification

    def _get_notes_for_candidate(
        self,
        candidate: HAICandidate,
    ) -> list[ClinicalNote]:
        """Get relevant clinical notes for CDI assessment.

        Args:
            candidate: The CDI candidate

        Returns:
            List of relevant clinical notes
        """
        if not self.note_source:
            logger.warning("No note source configured")
            return []

        cdi_data = getattr(candidate, "_cdi_data", None)
        test_date = cdi_data.test_result.test_date if cdi_data else candidate.culture.collection_date

        # Look for notes around test date (±3 days)
        start_date = test_date - timedelta(days=3)
        end_date = test_date + timedelta(days=3)

        try:
            notes = self.note_source.get_notes_for_patient(
                patient_id=candidate.patient.fhir_id,
                start_date=start_date,
                end_date=end_date,
                note_types=self.RELEVANT_NOTE_TYPES,
            )
            return notes
        except Exception as e:
            logger.error(f"Failed to retrieve notes: {e}")
            return []

    def _build_structured_data(
        self,
        candidate: HAICandidate,
    ) -> CDIStructuredData:
        """Build CDIStructuredData from candidate.

        Args:
            candidate: The CDI candidate

        Returns:
            CDIStructuredData with all available discrete data
        """
        cdi_data = getattr(candidate, "_cdi_data", None)

        if not cdi_data:
            logger.warning("Candidate missing CDI-specific data")
            return CDIStructuredData(
                patient_id=candidate.patient.fhir_id,
                patient_mrn=candidate.patient.mrn,
                test_date=candidate.culture.collection_date,
                test_type="unknown",
                test_result="positive",
            )

        # Convert prior episodes
        prior_episodes = [
            CDIPriorEpisode(
                episode_id=ep.id,
                test_date=ep.test_date,
                onset_type=ep.onset_type,
                is_recurrent=ep.is_recurrent,
            )
            for ep in cdi_data.prior_episodes
        ]

        # Calculate days since prior discharge
        days_since_discharge = None
        if cdi_data.recent_discharge_date and cdi_data.admission_date:
            days_since_discharge = (
                cdi_data.admission_date.date() - cdi_data.recent_discharge_date.date()
            ).days

        return CDIStructuredData(
            patient_id=candidate.patient.fhir_id,
            patient_mrn=candidate.patient.mrn,
            admission_date=cdi_data.admission_date,
            test_date=cdi_data.test_result.test_date,
            test_type=cdi_data.test_result.test_type,
            test_result=cdi_data.test_result.result,
            loinc_code=cdi_data.test_result.loinc_code,
            fhir_observation_id=cdi_data.test_result.fhir_id,
            specimen_type=cdi_data.test_result.specimen_type,
            is_formed_stool=cdi_data.test_result.is_formed_stool,
            specimen_day=cdi_data.specimen_day,
            prior_cdi_events=prior_episodes,
            days_since_last_cdi=cdi_data.days_since_last_cdi,
            last_cdi_date=(
                cdi_data.prior_episodes[0].test_date
                if cdi_data.prior_episodes else None
            ),
            prior_discharge_date=cdi_data.recent_discharge_date,
            prior_discharge_facility=cdi_data.recent_discharge_facility,
            days_since_prior_discharge=days_since_discharge,
        )

    def _map_decision(
        self,
        classification: CDIClassification,
    ) -> ClassificationDecision:
        """Map CDI classification to standard decision.

        Args:
            classification: CDI-specific classification

        Returns:
            Standard ClassificationDecision for workflow
        """
        if classification == CDIClassification.DUPLICATE:
            return ClassificationDecision.NOT_HAI

        if classification == CDIClassification.NOT_CDI:
            return ClassificationDecision.NOT_HAI

        if classification == CDIClassification.NOT_ELIGIBLE:
            return ClassificationDecision.NOT_HAI

        if classification == CDIClassification.INDETERMINATE:
            return ClassificationDecision.PENDING_REVIEW

        # All positive CDI classifications
        if classification in (
            CDIClassification.HO_CDI,
            CDIClassification.CO_CDI,
            CDIClassification.CO_HCFA_CDI,
            CDIClassification.RECURRENT_HO,
            CDIClassification.RECURRENT_CO,
        ):
            return ClassificationDecision.HAI_CONFIRMED

        return ClassificationDecision.PENDING_REVIEW
