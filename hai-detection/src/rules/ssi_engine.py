"""SSI rules engine - deterministic NHSN criteria application.

This module applies NHSN SSI criteria to LLM-extracted clinical data
combined with structured EHR data. The rules are deterministic - given
the same inputs, you get the same outputs.

The engine follows the NHSN decision tree:
1. Check basic eligibility (NHSN procedure, within surveillance window)
2. Evaluate Organ/Space SSI criteria (most severe, check first)
3. Evaluate Deep Incisional SSI criteria
4. Evaluate Superficial Incisional SSI criteria
5. Return NOT_SSI if no criteria met
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from .schemas import ConfidenceLevel
from .ssi_schemas import (
    SSIExtraction,
    SSIStructuredData,
    SSIClassification,
    SSIClassificationResult,
    SSIType,
)
from .nhsn_criteria import (
    is_nhsn_operative_procedure,
    get_surveillance_window,
    SSI_SURVEILLANCE_DAYS_STANDARD,
    SSI_SURVEILLANCE_DAYS_IMPLANT,
)

logger = logging.getLogger(__name__)


class SSIRulesEngine:
    """Deterministic NHSN criteria application for SSI classification.

    This engine takes:
    1. SSIExtraction - what the LLM extracted from notes
    2. SSIStructuredData - discrete EHR data (procedure, cultures, etc.)

    And produces:
    - SSIClassificationResult with full reasoning chain

    The engine is transparent and auditable - every decision is logged
    with the specific rule that was applied.

    NHSN SSI Type Hierarchy (most severe first):
    - Organ/Space SSI > Deep Incisional SSI > Superficial Incisional SSI
    """

    def __init__(
        self,
        strict_mode: bool = True,
        review_threshold: float = 0.75,
    ):
        """Initialize the rules engine.

        Args:
            strict_mode: If True, flag borderline cases for review.
                        If False, make best-guess classification.
            review_threshold: Confidence below this triggers review.
        """
        self.strict_mode = strict_mode
        self.review_threshold = review_threshold

    def classify(
        self,
        extraction: SSIExtraction,
        structured_data: SSIStructuredData,
    ) -> SSIClassificationResult:
        """Apply NHSN rules to classify a potential SSI.

        This is the main entry point. It runs through the NHSN decision
        tree in order, checking most severe SSI type first:
        1. Basic eligibility
        2. Organ/Space SSI check
        3. Deep Incisional SSI check
        4. Superficial Incisional SSI check
        5. Default to NOT_SSI

        Args:
            extraction: LLM-extracted clinical information
            structured_data: Discrete EHR data

        Returns:
            SSIClassificationResult with classification and reasoning
        """
        reasoning = []
        review_reasons = []
        eligibility_checks = []

        # === STEP 1: Basic Eligibility ===
        eligibility_result = self._check_basic_eligibility(
            structured_data, eligibility_checks, reasoning
        )
        if eligibility_result:
            return eligibility_result

        # Track which criteria are met for each SSI type
        organ_space_criteria = []
        deep_criteria = []
        superficial_criteria = []

        # === STEP 2: Check for Organ/Space SSI (most severe) ===
        organ_space_result = self._evaluate_organ_space_ssi(
            extraction, structured_data, reasoning, review_reasons, organ_space_criteria
        )
        if organ_space_result:
            organ_space_result.eligibility_checks = eligibility_checks
            organ_space_result.organ_space_criteria_met = organ_space_criteria
            return organ_space_result

        # === STEP 3: Check for Deep Incisional SSI ===
        deep_result = self._evaluate_deep_ssi(
            extraction, structured_data, reasoning, review_reasons, deep_criteria
        )
        if deep_result:
            deep_result.eligibility_checks = eligibility_checks
            deep_result.deep_criteria_met = deep_criteria
            return deep_result

        # === STEP 4: Check for Superficial Incisional SSI ===
        superficial_result = self._evaluate_superficial_ssi(
            extraction, structured_data, reasoning, review_reasons, superficial_criteria
        )
        if superficial_result:
            superficial_result.eligibility_checks = eligibility_checks
            superficial_result.superficial_criteria_met = superficial_criteria
            return superficial_result

        # === STEP 5: No SSI Criteria Met ===
        return self._classify_as_not_ssi(
            extraction, structured_data, reasoning, review_reasons, eligibility_checks
        )

    def _check_basic_eligibility(
        self,
        data: SSIStructuredData,
        eligibility_checks: list[str],
        reasoning: list[str],
    ) -> SSIClassificationResult | None:
        """Check basic NHSN SSI eligibility criteria.

        Returns SSIClassificationResult if NOT eligible, None if eligible.
        """
        # Check 1: Must be NHSN operative procedure category
        if not is_nhsn_operative_procedure(data.nhsn_category):
            eligibility_checks.append(
                f"FAIL: {data.nhsn_category} is not an NHSN operative procedure category"
            )
            return SSIClassificationResult(
                classification=SSIClassification.NOT_ELIGIBLE,
                ssi_type=None,
                confidence=0.95,
                reasoning=[f"Procedure category {data.nhsn_category} is not on NHSN operative procedure list"],
                requires_review=False,
                review_reasons=[],
                eligibility_checks=eligibility_checks,
            )
        eligibility_checks.append(f"PASS: {data.nhsn_category} is NHSN operative procedure")

        # Check 2: Within surveillance window
        if data.days_post_op > data.surveillance_window_days:
            eligibility_checks.append(
                f"FAIL: {data.days_post_op} days post-op exceeds "
                f"{data.surveillance_window_days} day surveillance window"
            )
            return SSIClassificationResult(
                classification=SSIClassification.NOT_ELIGIBLE,
                ssi_type=None,
                confidence=0.95,
                reasoning=[
                    f"Infection signal at {data.days_post_op} days post-op, "
                    f"exceeds {data.surveillance_window_days} day surveillance window"
                ],
                requires_review=False,
                review_reasons=[],
                eligibility_checks=eligibility_checks,
            )
        eligibility_checks.append(
            f"PASS: {data.days_post_op} days post-op within "
            f"{data.surveillance_window_days} day window"
        )

        # Check 3: Infection date must be after procedure date
        if data.days_post_op < 0:
            eligibility_checks.append("FAIL: Infection signal before procedure date")
            return SSIClassificationResult(
                classification=SSIClassification.NOT_ELIGIBLE,
                ssi_type=None,
                confidence=0.95,
                reasoning=["Infection signal date is before procedure date"],
                requires_review=False,
                review_reasons=[],
                eligibility_checks=eligibility_checks,
            )
        eligibility_checks.append("PASS: Infection date after procedure date")

        reasoning.append("Case meets basic SSI eligibility criteria")
        return None  # Eligible - continue evaluation

    def _evaluate_organ_space_ssi(
        self,
        extraction: SSIExtraction,
        data: SSIStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        criteria_met: list[str],
    ) -> SSIClassificationResult | None:
        """Evaluate Organ/Space SSI criteria.

        NHSN Organ/Space SSI requires at least ONE of:
        1. Purulent drainage from drain in organ/space
        2. Organisms from culture of organ/space fluid/tissue
        3. Abscess found on exam, reoperation, imaging, or histopath
        4. Physician diagnosis of organ/space SSI

        Returns SSIClassificationResult if Organ/Space SSI, None otherwise.
        """
        os = extraction.organ_space_findings

        # Criterion 1: Purulent drainage from drain
        if os.purulent_drainage_drain in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append(f"Purulent drainage from drain ({os.drain_location or 'unspecified location'})")

        # Criterion 2: Positive culture from organ/space
        if os.organisms_from_organ_space in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            organism = os.organism_identified or "organism identified"
            criteria_met.append(f"Positive culture from organ/space ({organism})")

        # Criterion 3: Abscess on exam/reoperation/imaging/histopath
        if os.abscess_on_direct_exam in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Abscess found on direct examination")
        if os.abscess_on_reoperation in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Abscess found on reoperation")
        if os.abscess_on_imaging in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            imaging = os.imaging_type or "imaging"
            criteria_met.append(f"Abscess found on {imaging}")
        if os.abscess_on_histopath in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Abscess confirmed on histopathology")

        # Criterion 4: Physician diagnosis
        if os.physician_diagnosis_organ_space_ssi in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Physician diagnosis of organ/space SSI")

        # Check for possible findings that need review
        if os.purulent_drainage_drain == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible purulent drainage from drain - verify")
        if os.organisms_from_organ_space == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible positive culture from organ/space - verify")
        if os.abscess_on_imaging == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible abscess on imaging - verify")
        if os.physician_diagnosis_organ_space_ssi == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible physician diagnosis of organ/space SSI - verify")

        # If any criteria met, classify as Organ/Space SSI
        if criteria_met:
            reasoning.append(f"Organ/Space SSI criteria met: {len(criteria_met)} criterion/criteria")
            for criterion in criteria_met:
                reasoning.append(f"  - {criterion}")

            confidence = self._calculate_confidence(extraction, len(criteria_met), review_reasons)
            requires_review = len(review_reasons) > 0 or confidence < self.review_threshold

            return SSIClassificationResult(
                classification=SSIClassification.ORGAN_SPACE_SSI,
                ssi_type=SSIType.ORGAN_SPACE,
                confidence=confidence,
                reasoning=reasoning + [
                    f"CLASSIFICATION: Organ/Space SSI",
                    f"Procedure: {data.procedure_name} ({data.nhsn_category})",
                    f"Days post-op: {data.days_post_op}",
                    f"Organ/space involved: {os.organ_space_involved or 'not specified'}",
                ],
                requires_review=requires_review,
                review_reasons=review_reasons,
                nhsn_specific_site=os.organ_space_nhsn_code,
                organism_for_report=os.organism_identified or data.wound_culture_organism,
            )

        reasoning.append("Organ/Space SSI: No criteria met")
        return None

    def _evaluate_deep_ssi(
        self,
        extraction: SSIExtraction,
        data: SSIStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        criteria_met: list[str],
    ) -> SSIClassificationResult | None:
        """Evaluate Deep Incisional SSI criteria.

        NHSN Deep SSI requires at least ONE of:
        1. Purulent drainage from deep incision
        2. Deep incision dehisces/opened + fever/pain (unless culture-negative)
        3. Abscess involving deep incision on exam/reoperation/imaging/histopath
        4. Physician diagnosis of deep incisional SSI

        Returns SSIClassificationResult if Deep SSI, None otherwise.
        """
        deep = extraction.deep_findings

        # Criterion 1: Purulent drainage from deep incision
        if deep.purulent_drainage_deep in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Purulent drainage from deep incision")

        # Criterion 2: Dehiscence + fever/pain
        dehiscence_or_opened = (
            deep.deep_incision_dehisces in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE] or
            deep.deep_incision_opened in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]
        )
        has_fever_or_pain = (
            deep.fever_greater_38 in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE] or
            deep.localized_pain_deep in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]
        )
        if dehiscence_or_opened and has_fever_or_pain:
            symptoms = []
            if deep.fever_greater_38 in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                temp = f" ({deep.fever_value_celsius}C)" if deep.fever_value_celsius else ""
                symptoms.append(f"fever{temp}")
            if deep.localized_pain_deep in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                symptoms.append("localized pain")
            criteria_met.append(f"Deep incision dehisced/opened with {', '.join(symptoms)}")

        # Criterion 3: Abscess involving deep incision
        if deep.abscess_on_direct_exam in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Abscess of deep incision on examination")
        if deep.abscess_on_reoperation in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Abscess of deep incision found on reoperation")
        if deep.abscess_on_imaging in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            imaging = deep.imaging_type or "imaging"
            criteria_met.append(f"Abscess of deep incision on {imaging}")
        if deep.abscess_on_histopath in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Deep incision infection confirmed on histopathology")

        # Criterion 4: Physician diagnosis
        if deep.physician_diagnosis_deep_ssi in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Physician diagnosis of deep incisional SSI")

        # Check for possible findings
        if deep.purulent_drainage_deep == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible purulent drainage from deep incision - verify")
        if deep.abscess_on_imaging == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible deep abscess on imaging - verify")
        if deep.physician_diagnosis_deep_ssi == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible physician diagnosis of deep SSI - verify")

        # If any criteria met, classify as Deep SSI
        if criteria_met:
            reasoning.append(f"Deep Incisional SSI criteria met: {len(criteria_met)} criterion/criteria")
            for criterion in criteria_met:
                reasoning.append(f"  - {criterion}")

            confidence = self._calculate_confidence(extraction, len(criteria_met), review_reasons)
            requires_review = len(review_reasons) > 0 or confidence < self.review_threshold

            return SSIClassificationResult(
                classification=SSIClassification.DEEP_SSI,
                ssi_type=SSIType.DEEP_INCISIONAL,
                confidence=confidence,
                reasoning=reasoning + [
                    f"CLASSIFICATION: Deep Incisional SSI",
                    f"Procedure: {data.procedure_name} ({data.nhsn_category})",
                    f"Days post-op: {data.days_post_op}",
                ],
                requires_review=requires_review,
                review_reasons=review_reasons,
                organism_for_report=data.wound_culture_organism,
            )

        reasoning.append("Deep Incisional SSI: No criteria met")
        return None

    def _evaluate_superficial_ssi(
        self,
        extraction: SSIExtraction,
        data: SSIStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        criteria_met: list[str],
    ) -> SSIClassificationResult | None:
        """Evaluate Superficial Incisional SSI criteria.

        NHSN Superficial SSI requires at least ONE of:
        1. Purulent drainage from superficial incision
        2. Organisms from culture of superficial incision
        3. Signs (pain, swelling, erythema, heat) + incision deliberately opened
        4. Physician diagnosis of superficial incisional SSI

        Returns SSIClassificationResult if Superficial SSI, None otherwise.
        """
        sup = extraction.superficial_findings

        # Criterion 1: Purulent drainage from superficial incision
        if sup.purulent_drainage_superficial in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Purulent drainage from superficial incision")

        # Criterion 2: Positive culture from superficial incision
        if sup.organisms_from_superficial_culture in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            organism = sup.organism_identified or "organism identified"
            criteria_met.append(f"Positive culture from superficial incision ({organism})")

        # Criterion 3: Signs + incision deliberately opened
        has_signs = any([
            sup.pain_or_tenderness in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE],
            sup.localized_swelling in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE],
            sup.erythema in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE],
            sup.heat in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE],
        ])
        incision_opened = sup.incision_deliberately_opened in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]

        if has_signs and incision_opened:
            signs = []
            if sup.pain_or_tenderness in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                signs.append("pain/tenderness")
            if sup.localized_swelling in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                signs.append("swelling")
            if sup.erythema in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                signs.append("erythema")
            if sup.heat in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                signs.append("heat")
            criteria_met.append(f"Signs of infection ({', '.join(signs)}) with incision deliberately opened")

        # Criterion 4: Physician diagnosis
        if sup.physician_diagnosis_superficial_ssi in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            criteria_met.append("Physician diagnosis of superficial incisional SSI")

        # Check for possible findings
        if sup.purulent_drainage_superficial == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible purulent drainage - verify")
        if sup.organisms_from_superficial_culture == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible positive wound culture - verify")
        if sup.physician_diagnosis_superficial_ssi == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible physician diagnosis of superficial SSI - verify")

        # If any criteria met, classify as Superficial SSI
        if criteria_met:
            reasoning.append(f"Superficial Incisional SSI criteria met: {len(criteria_met)} criterion/criteria")
            for criterion in criteria_met:
                reasoning.append(f"  - {criterion}")

            confidence = self._calculate_confidence(extraction, len(criteria_met), review_reasons)
            requires_review = len(review_reasons) > 0 or confidence < self.review_threshold

            return SSIClassificationResult(
                classification=SSIClassification.SUPERFICIAL_SSI,
                ssi_type=SSIType.SUPERFICIAL_INCISIONAL,
                confidence=confidence,
                reasoning=reasoning + [
                    f"CLASSIFICATION: Superficial Incisional SSI",
                    f"Procedure: {data.procedure_name} ({data.nhsn_category})",
                    f"Days post-op: {data.days_post_op}",
                ],
                requires_review=requires_review,
                review_reasons=review_reasons,
                organism_for_report=sup.organism_identified or data.wound_culture_organism,
            )

        reasoning.append("Superficial Incisional SSI: No criteria met")
        return None

    def _classify_as_not_ssi(
        self,
        extraction: SSIExtraction,
        data: SSIStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        eligibility_checks: list[str],
    ) -> SSIClassificationResult:
        """Classify as NOT SSI when no criteria are met."""
        reasoning.append("No SSI criteria met - classifying as NOT SSI")

        # Check if there are infection signals that warrant review
        if extraction.ssi_suspected_by_team in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            review_reasons.append("Clinical team suspects SSI but criteria not met - review recommended")

        if extraction.antibiotics_for_wound_infection in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            review_reasons.append("Antibiotics given for wound infection but SSI criteria not met")

        confidence = 0.85 if not review_reasons else 0.70

        return SSIClassificationResult(
            classification=SSIClassification.NOT_SSI,
            ssi_type=None,
            confidence=confidence,
            reasoning=reasoning + [
                f"CLASSIFICATION: Not SSI",
                f"Procedure: {data.procedure_name} ({data.nhsn_category})",
                f"Days post-op: {data.days_post_op}",
                "Evaluated superficial, deep, and organ/space criteria - none met",
            ],
            requires_review=len(review_reasons) > 0,
            review_reasons=review_reasons,
            eligibility_checks=eligibility_checks,
        )

    def _calculate_confidence(
        self,
        extraction: SSIExtraction,
        criteria_count: int,
        review_reasons: list[str],
    ) -> float:
        """Calculate confidence score based on extraction quality and criteria.

        Confidence represents how certain we are in the classification,
        based on documentation quality and number of criteria met.
        """
        base_confidence = 0.80

        # Bonus for multiple criteria met
        if criteria_count >= 3:
            base_confidence += 0.10
        elif criteria_count >= 2:
            base_confidence += 0.05

        # Deductions for documentation quality
        quality_deductions = {
            "poor": 0.20,
            "limited": 0.10,
            "adequate": 0.0,
            "detailed": -0.05,  # Bonus
        }
        base_confidence -= quality_deductions.get(extraction.documentation_quality, 0)

        # Deductions for review flags
        if len(review_reasons) > 2:
            base_confidence -= 0.10
        elif len(review_reasons) > 0:
            base_confidence -= 0.05

        # Clamp to valid range
        return max(0.50, min(0.95, base_confidence))


# =============================================================================
# Convenience functions
# =============================================================================

def classify_ssi(
    extraction: SSIExtraction,
    structured_data: SSIStructuredData,
    strict_mode: bool = True,
) -> SSIClassificationResult:
    """Convenience function to classify an SSI case.

    Args:
        extraction: LLM-extracted clinical information
        structured_data: Discrete EHR data
        strict_mode: Whether to flag borderline cases for review

    Returns:
        SSIClassificationResult
    """
    engine = SSIRulesEngine(strict_mode=strict_mode)
    return engine.classify(extraction, structured_data)
