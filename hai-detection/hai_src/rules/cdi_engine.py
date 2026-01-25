"""CDI (Clostridioides difficile Infection) Rules Engine.

Applies NHSN CDI LabID Event criteria deterministically to classify CDI cases.

The rules engine receives:
1. CDIExtraction (from LLM) - clinical facts from notes
2. CDIStructuredData (from EHR) - discrete data fields

And produces:
- CDIClassificationResult with classification, confidence, and reasoning

NHSN CDI Classification (Time-Based):
- Healthcare-Facility Onset (HO-CDI): Specimen >3 days after admission
- Community Onset (CO-CDI): Specimen ≤3 days after admission
- CO-HCFA: CO-CDI with prior discharge within 4 weeks

Recurrence Rules:
- ≤14 days since last event = Duplicate (not reported)
- 15-56 days = Recurrent
- >56 days = Incident

Reference: 2024 NHSN Patient Safety Component Manual, Chapter 12
"""

import logging
from datetime import datetime

from .cdi_schemas import (
    CDIClassification,
    CDIExtraction,
    CDIStructuredData,
    CDIClassificationResult,
)
from .nhsn_criteria import (
    is_valid_cdi_test,
    calculate_specimen_day,
    get_cdi_onset_type,
    is_cdi_duplicate,
    is_cdi_recurrent,
    is_cdi_incident,
    is_cdi_co_hcfa,
    get_cdi_recurrence_status,
    CDI_HO_MIN_DAYS,
    CDI_DUPLICATE_WINDOW_DAYS,
    CDI_RECURRENCE_MIN_DAYS,
    CDI_RECURRENCE_MAX_DAYS,
    CDI_CO_HCFA_DISCHARGE_WINDOW_DAYS,
)
from .schemas import ConfidenceLevel

logger = logging.getLogger(__name__)


class CDIRulesEngine:
    """Apply NHSN CDI criteria deterministically.

    Unlike device-associated HAIs, CDI classification is primarily
    based on timing (specimen day) and test result. The extraction
    provides clinical context but doesn't drive the classification.

    Decision Flow:
    1. Is test positive for toxin/toxin-producing organism?
       → If no, NOT_CDI
    2. Is specimen from formed stool?
       → If yes, NOT_ELIGIBLE
    3. Is specimen ≤14 days after last CDI event?
       → If yes, DUPLICATE
    4. Is specimen 15-56 days after last CDI event?
       → Mark as RECURRENT
    5. Is specimen_day > 3?
       → HO-CDI
    6. Else CO-CDI
       → If discharged from facility within 4 weeks, CO-HCFA-CDI
    """

    def classify(
        self,
        extraction: CDIExtraction,
        structured_data: CDIStructuredData,
    ) -> CDIClassificationResult:
        """Apply NHSN CDI criteria to classify the case.

        Args:
            extraction: LLM-extracted clinical facts from notes
            structured_data: Discrete EHR data (test, timing, prior episodes)

        Returns:
            CDIClassificationResult with classification and full reasoning
        """
        reasoning = []
        review_reasons = []
        confidence = 1.0

        # Step 1: Verify test qualifies
        test_eligible = False
        if structured_data.test_result and structured_data.test_type:
            test_eligible = is_valid_cdi_test(
                structured_data.test_type,
                structured_data.test_result,
            )

        if not test_eligible:
            reasoning.append(
                f"Test type '{structured_data.test_type}' with result "
                f"'{structured_data.test_result}' does not qualify for CDI LabID event"
            )
            return CDIClassificationResult(
                classification=CDIClassification.NOT_CDI,
                onset_type="unknown",
                is_recurrent=False,
                confidence=0.95,
                reasoning=reasoning,
                requires_review=False,
                review_reasons=[],
                test_eligible=False,
                test_type=structured_data.test_type,
                test_positive=False,
            )

        reasoning.append(
            f"Positive {structured_data.test_type} test qualifies for CDI LabID event"
        )

        # Step 2: Check specimen type
        if structured_data.is_formed_stool:
            reasoning.append(
                "Specimen was formed stool - does not qualify for CDI LabID event"
            )
            return CDIClassificationResult(
                classification=CDIClassification.NOT_ELIGIBLE,
                onset_type="unknown",
                is_recurrent=False,
                confidence=0.95,
                reasoning=reasoning,
                requires_review=False,
                review_reasons=[],
                test_eligible=True,
                test_type=structured_data.test_type,
                test_positive=True,
            )

        reasoning.append("Specimen was unformed stool (qualifies)")

        # Step 3: Calculate specimen day
        if structured_data.admission_date and structured_data.test_date:
            specimen_day = calculate_specimen_day(
                structured_data.admission_date,
                structured_data.test_date,
            )
        else:
            specimen_day = structured_data.specimen_day or 1
            reasoning.append(
                f"Using provided specimen day: {specimen_day}"
            )
            confidence -= 0.1
            review_reasons.append("Admission date not available - verify specimen day")

        reasoning.append(f"Specimen collected on day {specimen_day} of admission")

        # Step 4: Check for duplicate (≤14 days since last)
        is_duplicate = False
        is_recurrent = False
        recurrence_status = "incident"

        if structured_data.days_since_last_cdi is not None:
            days = structured_data.days_since_last_cdi
            recurrence_status = get_cdi_recurrence_status(days)

            if is_cdi_duplicate(days):
                is_duplicate = True
                reasoning.append(
                    f"Last CDI event was {days} days ago (≤{CDI_DUPLICATE_WINDOW_DAYS}) - "
                    "DUPLICATE, not reportable"
                )
                return CDIClassificationResult(
                    classification=CDIClassification.DUPLICATE,
                    onset_type="duplicate",
                    is_recurrent=False,
                    confidence=0.95,
                    reasoning=reasoning,
                    requires_review=False,
                    review_reasons=[],
                    test_eligible=True,
                    test_type=structured_data.test_type,
                    test_positive=True,
                    specimen_day=specimen_day,
                    days_since_last_cdi=days,
                    recurrence_status="duplicate",
                )

            elif is_cdi_recurrent(days):
                is_recurrent = True
                reasoning.append(
                    f"Last CDI event was {days} days ago "
                    f"({CDI_RECURRENCE_MIN_DAYS}-{CDI_RECURRENCE_MAX_DAYS} days) - "
                    "RECURRENT episode"
                )
            else:
                reasoning.append(
                    f"Last CDI event was {days} days ago (>{CDI_RECURRENCE_MAX_DAYS}) - "
                    "New INCIDENT episode"
                )
        else:
            reasoning.append("No prior CDI events found - INCIDENT episode")

        # Step 5: Determine onset type
        onset_type_code = get_cdi_onset_type(specimen_day)

        if onset_type_code == "healthcare_facility":
            onset_type = "ho"
            reasoning.append(
                f"Specimen day {specimen_day} > 3 = "
                "Healthcare-Facility Onset (HO-CDI)"
            )
        else:
            onset_type = "co"
            reasoning.append(
                f"Specimen day {specimen_day} ≤ 3 = Community Onset (CO-CDI)"
            )

            # Step 6: Check for CO-HCFA
            if structured_data.days_since_prior_discharge is not None:
                days_discharge = structured_data.days_since_prior_discharge
                if days_discharge <= CDI_CO_HCFA_DISCHARGE_WINDOW_DAYS:
                    onset_type = "co_hcfa"
                    reasoning.append(
                        f"Prior discharge {days_discharge} days ago "
                        f"(≤{CDI_CO_HCFA_DISCHARGE_WINDOW_DAYS}) - "
                        "CO-HCFA (Healthcare Facility-Associated)"
                    )

        # Step 7: Determine final classification
        if is_recurrent:
            if onset_type == "ho":
                classification = CDIClassification.RECURRENT_HO
            else:
                classification = CDIClassification.RECURRENT_CO
        elif onset_type == "ho":
            classification = CDIClassification.HO_CDI
        elif onset_type == "co_hcfa":
            classification = CDIClassification.CO_HCFA_CDI
        else:
            classification = CDIClassification.CO_CDI

        reasoning.append(f"Final classification: {classification.value}")

        # Step 8: Check extraction for clinical context
        diarrhea_documented = extraction.diarrhea.diarrhea_documented in (
            ConfidenceLevel.DEFINITE,
            ConfidenceLevel.PROBABLE,
        )
        treatment_initiated = extraction.treatment.treatment_initiated in (
            ConfidenceLevel.DEFINITE,
            ConfidenceLevel.PROBABLE,
        )
        treatment_type = extraction.treatment.treatment_type

        if diarrhea_documented:
            reasoning.append("Diarrhea documented in clinical notes")
        else:
            review_reasons.append("Diarrhea not clearly documented - verify symptoms")
            confidence -= 0.05

        if treatment_initiated:
            reasoning.append(f"CDI treatment initiated ({treatment_type or 'type not specified'})")
        else:
            review_reasons.append("Treatment not documented - verify management")

        # Check for alternative diagnoses
        if extraction.alternative_diagnoses:
            alt_dx = ", ".join(extraction.alternative_diagnoses)
            reasoning.append(f"Alternative diagnoses mentioned: {alt_dx}")
            review_reasons.append(f"Alternative diagnoses documented: {alt_dx}")
            confidence -= 0.1

        # Documentation quality affects confidence
        if extraction.documentation_quality == "poor":
            confidence -= 0.15
            review_reasons.append("Poor documentation quality")
        elif extraction.documentation_quality == "limited":
            confidence -= 0.1
            review_reasons.append("Limited documentation")

        # Clamp confidence
        confidence = max(0.5, min(1.0, confidence))

        # Require review for low confidence or specific issues
        requires_review = len(review_reasons) > 0 or confidence < 0.85

        return CDIClassificationResult(
            classification=classification,
            onset_type=onset_type,
            is_recurrent=is_recurrent,
            confidence=confidence,
            reasoning=reasoning,
            requires_review=requires_review,
            review_reasons=review_reasons,
            test_eligible=True,
            test_type=structured_data.test_type,
            test_positive=True,
            specimen_day=specimen_day,
            admission_date=structured_data.admission_date,
            test_date=structured_data.test_date,
            days_since_last_cdi=structured_data.days_since_last_cdi,
            recurrence_status=recurrence_status,
            is_co_hcfa=(onset_type == "co_hcfa"),
            prior_discharge_days=structured_data.days_since_prior_discharge,
            diarrhea_documented=diarrhea_documented,
            treatment_initiated=treatment_initiated,
            treatment_type=treatment_type,
        )

    def classify_from_candidate(
        self,
        extraction: CDIExtraction,
        candidate,
    ) -> CDIClassificationResult:
        """Convenience method to classify using HAICandidate with CDI data.

        Args:
            extraction: LLM-extracted clinical facts
            candidate: HAICandidate with _cdi_data attached

        Returns:
            CDIClassificationResult
        """
        from ..models import CDICandidate
        from .cdi_schemas import CDIStructuredData, CDIPriorEpisode

        cdi_data = getattr(candidate, "_cdi_data", None)
        if not cdi_data:
            raise ValueError("Candidate missing _cdi_data")

        # Build structured data from candidate
        prior_episodes = [
            CDIPriorEpisode(
                episode_id=ep.id,
                test_date=ep.test_date,
                onset_type=ep.onset_type,
                is_recurrent=ep.is_recurrent,
            )
            for ep in cdi_data.prior_episodes
        ]

        structured = CDIStructuredData(
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
            prior_discharge_date=cdi_data.recent_discharge_date,
            prior_discharge_facility=cdi_data.recent_discharge_facility,
            days_since_prior_discharge=(
                (cdi_data.admission_date.date() - cdi_data.recent_discharge_date.date()).days
                if cdi_data.recent_discharge_date and cdi_data.admission_date
                else None
            ),
        )

        return self.classify(extraction, structured)
