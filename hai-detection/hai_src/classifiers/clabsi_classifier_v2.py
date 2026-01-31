"""CLABSI classification v2 - extraction + rules architecture.

This classifier separates concerns:
1. LLM extracts clinical information (what's documented)
2. Rules engine applies NHSN criteria (deterministic logic)

This approach provides:
- Transparent, auditable decision making
- Easy updates when NHSN criteria change
- Testable rules independent of LLM
- Better explainability for IP review

Two-Stage Pipeline (optional):
    Stage 1: Fast triage with 8B model (~5 seconds)
    Stage 2: Full extraction with 70B model (~60 seconds) - only if needed

Enable with use_triage=True in __init__.
"""

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

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
from ..db import HAIDatabase
from ..extraction import CLABSIExtractor
from ..extraction.triage_extractor import (
    TriageExtractor,
    TriageExtraction,
    TriageDecision,
    should_escalate,
)
from ..extraction.training_collector import get_collector, TrainingCollector
from ..rules import (
    CLABSIRulesEngine,
    ClinicalExtraction,
    StructuredCaseData,
    CLABSIClassification,
    ClassificationResult,
    ConfidenceLevel,
)
from .base import BaseHAIClassifier

logger = logging.getLogger(__name__)


class ClassificationPath(str, Enum):
    """Tracks which pipeline path was taken."""
    TRIAGE_ONLY = "triage_only"  # Fast path, no escalation
    TRIAGE_ESCALATED = "triage_escalated"  # Triage → Full extraction
    FULL_ONLY = "full_only"  # Triage disabled, full extraction


@dataclass
class ClassificationMetrics:
    """Metrics from classification run."""
    path: ClassificationPath
    triage_ms: int | None = None
    extraction_ms: int | None = None
    total_ms: int = 0
    triage_decision: TriageDecision | None = None


class CLABSIClassifierV2(BaseHAIClassifier):
    """CLABSI classifier using extraction + rules architecture.

    Pipeline (standard):
        Notes → CLABSIExtractor (LLM) → ClinicalExtraction
        ClinicalExtraction + StructuredCaseData → CLABSIRulesEngine → Classification

    Pipeline (two-stage, use_triage=True):
        Notes → TriageExtractor (8B) → TriageExtraction
            ↓ needs_full_analysis?
            No → Rules Engine (simplified)
            Yes → CLABSIExtractor (70B) → Rules Engine

    This version separates LLM-based extraction from deterministic rules,
    making the system more transparent and maintainable.
    """

    PROMPT_VERSION = "clabsi_extraction_v1"

    def __init__(
        self,
        llm_client=None,
        db: HAIDatabase | None = None,
        strict_mode: bool = True,
        use_triage: bool = True,
        triage_model: str | None = None,
        collect_training_data: bool = True,
    ):
        """Initialize the classifier.

        Args:
            llm_client: LLM client for extraction. Uses factory default if None.
            db: Database for audit logging and structured data. Optional.
            strict_mode: If True, flag borderline cases for review.
            use_triage: If True, use two-stage pipeline with fast triage first.
            triage_model: Model for triage. Defaults to qwen2.5:7b.
            collect_training_data: If True, log extractions for future fine-tuning.
        """
        self.extractor = CLABSIExtractor(llm_client=llm_client, db=db)
        self.rules_engine = CLABSIRulesEngine(strict_mode=strict_mode)
        self.db = db
        self._llm_client = llm_client
        self.use_triage = use_triage
        self.collect_training_data = collect_training_data

        # Initialize triage extractor if enabled
        self._triage_extractor: TriageExtractor | None = None
        if use_triage:
            self._triage_extractor = TriageExtractor(model=triage_model)

        # Training data collector
        self._training_collector: TrainingCollector | None = None
        if collect_training_data:
            self._training_collector = get_collector()

        # Track metrics for analysis
        self._last_metrics: ClassificationMetrics | None = None
        self._last_triage_result: TriageExtraction | None = None

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

        If use_triage is enabled, runs a fast triage pass first and only
        escalates to full extraction when needed.

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

        # Step 2: Triage or full extraction
        if self.use_triage and self._triage_extractor:
            classification = self._classify_with_triage(
                candidate, notes, structured_data, start_time
            )
        else:
            classification = self._classify_full(
                candidate, notes, structured_data, start_time
            )

        return classification

    def _classify_full(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        structured_data: StructuredCaseData,
        start_time: float,
    ) -> Classification:
        """Full classification without triage."""
        # Extract clinical information using LLM
        extraction = self.extractor.extract(candidate, notes)

        # Apply rules engine
        rules_result = self.rules_engine.classify(extraction, structured_data)

        # Convert to Classification model
        elapsed_ms = int((time.time() - start_time) * 1000)
        classification = self._build_classification(
            candidate, extraction, rules_result, elapsed_ms
        )

        # Track metrics
        self._last_metrics = ClassificationMetrics(
            path=ClassificationPath.FULL_ONLY,
            extraction_ms=elapsed_ms,
            total_ms=elapsed_ms,
        )
        self._last_triage_result = None

        # Log training data
        self._log_training_data(
            candidate=candidate,
            notes=notes,
            extraction=extraction,
            classification=classification,
            triage_result=None,
        )

        return classification

    def _classify_with_triage(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        structured_data: StructuredCaseData,
        start_time: float,
    ) -> Classification:
        """Classification with two-stage triage pipeline."""
        # Stage 1: Fast triage
        triage_start = time.time()
        triage_result = self._triage_extractor.extract(
            candidate, notes, hai_type=HAIType.CLABSI
        )
        triage_ms = int((time.time() - triage_start) * 1000)

        logger.info(
            f"Triage complete: decision={triage_result.decision.value} "
            f"in {triage_ms}ms"
        )

        if should_escalate(triage_result):
            # Stage 2: Full extraction needed
            logger.info("Escalating to full extraction")
            extraction = self.extractor.extract(candidate, notes)
            rules_result = self.rules_engine.classify(extraction, structured_data)

            elapsed_ms = int((time.time() - start_time) * 1000)
            classification = self._build_classification(
                candidate, extraction, rules_result, elapsed_ms
            )

            # Add triage info to reasoning
            classification.reasoning = (
                f"[Triage → Escalated: {triage_result.quick_reasoning}]\n\n"
                + classification.reasoning
            )

            self._last_metrics = ClassificationMetrics(
                path=ClassificationPath.TRIAGE_ESCALATED,
                triage_ms=triage_ms,
                extraction_ms=elapsed_ms - triage_ms,
                total_ms=elapsed_ms,
                triage_decision=triage_result.decision,
            )
            self._last_triage_result = triage_result

            # Log training data (full extraction after triage)
            self._log_training_data(
                candidate=candidate,
                notes=notes,
                extraction=extraction,
                classification=classification,
                triage_result=triage_result,
            )
        else:
            # Use triage results directly
            extraction = self._triage_to_extraction(triage_result)
            rules_result = self.rules_engine.classify(extraction, structured_data)

            elapsed_ms = int((time.time() - start_time) * 1000)
            classification = self._build_classification(
                candidate, extraction, rules_result, elapsed_ms
            )

            # Note that this was triage-only
            classification.reasoning = (
                f"[Triage → Fast Path: {triage_result.quick_reasoning}]\n\n"
                + classification.reasoning
            )

            self._last_metrics = ClassificationMetrics(
                path=ClassificationPath.TRIAGE_ONLY,
                triage_ms=triage_ms,
                total_ms=elapsed_ms,
                triage_decision=triage_result.decision,
            )
            self._last_triage_result = triage_result

            # Log training data (triage only, no full extraction)
            self._log_training_data(
                candidate=candidate,
                notes=notes,
                extraction=extraction,
                classification=classification,
                triage_result=triage_result,
            )

            logger.info(
                f"Triage fast path: classified in {elapsed_ms}ms "
                f"(saved ~{60000 - elapsed_ms}ms)"
            )

        return classification

    def _triage_to_extraction(self, triage: TriageExtraction) -> ClinicalExtraction:
        """Convert triage results to ClinicalExtraction for rules engine.

        This creates a minimal ClinicalExtraction that the rules engine can use.
        Since triage only runs for clear cases, we can make confident assertions.
        """
        from ..rules.schemas import (
            DocumentedInfectionSite,
            SymptomExtraction,
            MBIFactors,
            LineAssessment,
            ContaminationAssessment,
        )

        # Build minimal extraction based on triage decision
        alternate_sites = []
        if triage.alternate_source_mentioned and triage.primary_impression:
            alternate_sites.append(DocumentedInfectionSite(
                site=triage.primary_impression,
                confidence=ConfidenceLevel.PROBABLE,
                supporting_quote=triage.quick_reasoning,
            ))

        contamination = ContaminationAssessment()
        if triage.contamination_mentioned:
            contamination.treated_as_contaminant = ConfidenceLevel.PROBABLE
            contamination.clinical_note_quote = triage.quick_reasoning

        line_assessment = LineAssessment()
        if triage.obvious_hai_signals:
            line_assessment.line_infection_suspected = ConfidenceLevel.PROBABLE

        return ClinicalExtraction(
            alternate_infection_sites=alternate_sites,
            primary_diagnosis_if_stated=triage.primary_impression,
            symptoms=SymptomExtraction(),  # Minimal
            mbi_factors=MBIFactors(),  # Minimal (triage would escalate if MBI)
            line_assessment=line_assessment,
            contamination=contamination,
            clinical_context_summary=triage.quick_reasoning,
            documentation_quality=triage.documentation_quality,
            notes_reviewed_count=1,  # Triage uses abbreviated context
            extraction_notes=f"Triage extraction (fast path): {triage.decision.value}",
        )

    def _log_training_data(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
        extraction: ClinicalExtraction,
        classification: Classification,
        triage_result: TriageExtraction | None,
    ) -> None:
        """Log extraction for training data collection."""
        if not self.collect_training_data or not self._training_collector:
            return

        try:
            # Combine notes for input
            notes_text = "\n\n---\n\n".join(
                f"[{n.note_type} - {n.date.strftime('%Y-%m-%d')}]\n{n.content}"
                for n in notes[:20]  # Limit to prevent huge inputs
            )

            # Build input context
            input_context = {
                "patient_mrn": candidate.patient.mrn if candidate.patient else None,
                "organism": candidate.culture.organism if candidate.culture else None,
                "device_days": candidate.device_days_at_culture,
            }

            # Get extraction as dict
            extraction_dict = {}
            if hasattr(extraction, 'to_dict'):
                extraction_dict = extraction.to_dict()
            elif hasattr(extraction, '__dict__'):
                extraction_dict = {
                    k: v for k, v in extraction.__dict__.items()
                    if not k.startswith('_')
                }

            self._training_collector.log_extraction(
                case_id=candidate.id,
                hai_type=HAIType.CLABSI,
                input_notes=notes_text,
                input_context=input_context,
                extraction=extraction_dict,
                model=self.llm_client.model_name,
                latency_ms=self._last_metrics.total_ms if self._last_metrics else 0,
                triage_result=triage_result,
                classification_decision=classification.decision.value,
                classification_confidence=classification.confidence,
                classification_path=self._last_metrics.path.value if self._last_metrics else None,
            )
        except Exception as e:
            logger.warning(f"Failed to log training data: {e}")

    @property
    def last_metrics(self) -> ClassificationMetrics | None:
        """Get metrics from the last classification run."""
        return self._last_metrics

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

        # Add alternate sources as contradicting evidence for CLABSI
        for alt_site in extraction.alternate_infection_sites:
            if alt_site.confidence.value in ["definite", "probable"]:
                contradicting.append(SupportingEvidence(
                    text=alt_site.supporting_quote or f"Documented {alt_site.site}",
                    source=format_source(alt_site.source),
                    relevance=f"Possible alternate source: {alt_site.site}",
                ))

        # Add line assessment as supporting evidence
        line = extraction.line_assessment
        if line.line_infection_suspected.value in ["definite", "probable"]:
            supporting.append(SupportingEvidence(
                text="Line infection suspected by clinical team",
                source=format_source(line.line_infection_suspected_source),
                relevance="Supports CLABSI attribution",
            ))

        # Add exit site findings as supporting evidence
        if line.exit_site_erythema.value in ["definite", "probable"] or line.exit_site_purulence.value in ["definite", "probable"]:
            findings = []
            if line.exit_site_erythema.value in ["definite", "probable"]:
                findings.append("erythema")
            if line.exit_site_purulence.value in ["definite", "probable"]:
                findings.append("purulence")
            supporting.append(SupportingEvidence(
                text=f"Exit site findings: {', '.join(findings)}",
                source=format_source(line.exit_site_source),
                relevance="Exit site findings support line-related infection",
            ))

        # Add MBI factors as evidence
        mbi = extraction.mbi_factors
        if mbi.mucositis_documented.value in ["definite", "probable"]:
            grade_info = f" (Grade {mbi.mucositis_grade})" if mbi.mucositis_grade else ""
            supporting.append(SupportingEvidence(
                text=f"Mucositis documented{grade_info}",
                source=format_source(mbi.mucositis_source),
                relevance="MBI-LCBI: Mucosal barrier injury factor",
            ))

        if mbi.neutropenia_documented.value in ["definite", "probable"]:
            anc_info = f" (ANC: {mbi.anc_value})" if mbi.anc_value else ""
            supporting.append(SupportingEvidence(
                text=f"Neutropenia documented{anc_info}",
                source=format_source(mbi.neutropenia_source),
                relevance="MBI-LCBI: Immunocompromised status",
            ))

        if mbi.stem_cell_transplant.value in ["definite", "probable"]:
            transplant_info = f" ({mbi.transplant_type})" if mbi.transplant_type else ""
            supporting.append(SupportingEvidence(
                text=f"Stem cell transplant{transplant_info}",
                source=format_source(mbi.transplant_source),
                relevance="MBI-LCBI: Transplant status",
            ))

        # Add contamination evidence
        contam = extraction.contamination
        if contam.treated_as_contaminant.value in ["definite", "probable"]:
            contradicting.append(SupportingEvidence(
                text=contam.clinical_note_quote or "Team treating as contaminant",
                source=format_source(contam.source),
                relevance="Suggests contamination rather than true infection",
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
