"""CLABSI rules engine - deterministic NHSN criteria application.

This module applies NHSN CLABSI criteria to LLM-extracted clinical data
combined with structured EHR data. The rules are deterministic - given
the same inputs, you get the same outputs.

The engine follows the NHSN decision tree:
1. Check basic eligibility (line present, days, etc.)
2. Check for MBI-LCBI (immunocompromised + GI organism + mucosal injury)
3. Check for secondary BSI (alternate source with same organism)
4. Check for contamination (commensals without matching culture)
5. Default to CLABSI if no exclusions apply
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .schemas import (
    ConfidenceLevel,
    ClinicalExtraction,
    StructuredCaseData,
    CLABSIClassification,
    ClassificationResult,
    DocumentedInfectionSite,
)
from .nhsn_criteria import (
    MIN_LINE_DAYS,
    POST_REMOVAL_ATTRIBUTION_DAYS,
    MIN_PATIENT_DAYS_FOR_HAI,
    NEUTROPENIA_ANC_THRESHOLD,
    ALLO_HSCT_MBI_WINDOW_DAYS,
    is_commensal_organism,
    is_mbi_eligible_organism,
    is_recognized_pathogen,
)

logger = logging.getLogger(__name__)


class CLABSIRulesEngine:
    """Deterministic NHSN criteria application for CLABSI classification.

    This engine takes:
    1. ClinicalExtraction - what the LLM extracted from notes
    2. StructuredCaseData - discrete EHR data (labs, dates, etc.)

    And produces:
    - ClassificationResult with full reasoning chain

    The engine is transparent and auditable - every decision is logged
    with the specific rule that was applied.
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
        extraction: ClinicalExtraction,
        structured_data: StructuredCaseData,
    ) -> ClassificationResult:
        """Apply NHSN rules to classify a potential CLABSI.

        This is the main entry point. It runs through the NHSN decision
        tree in order:
        1. Basic eligibility
        2. MBI-LCBI check
        3. Secondary BSI check
        4. Contamination check
        5. Default to CLABSI

        Args:
            extraction: LLM-extracted clinical information
            structured_data: Discrete EHR data

        Returns:
            ClassificationResult with classification and reasoning
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

        # === STEP 2: Check for MBI-LCBI ===
        mbi_result = self._evaluate_mbi_lcbi(
            extraction, structured_data, reasoning, review_reasons
        )
        if mbi_result:
            return mbi_result

        # === STEP 3: Check for Secondary BSI ===
        secondary_result = self._evaluate_secondary_bsi(
            extraction, structured_data, reasoning, review_reasons
        )
        if secondary_result:
            return secondary_result

        # === STEP 4: Check for Contamination ===
        contamination_result = self._evaluate_contamination(
            extraction, structured_data, reasoning, review_reasons
        )
        if contamination_result:
            return contamination_result

        # === STEP 5: Default to CLABSI ===
        return self._classify_as_clabsi(
            extraction, structured_data, reasoning, review_reasons, eligibility_checks
        )

    def _check_basic_eligibility(
        self,
        data: StructuredCaseData,
        eligibility_checks: list[str],
        reasoning: list[str],
    ) -> ClassificationResult | None:
        """Check basic NHSN CLABSI eligibility criteria.

        Returns ClassificationResult if NOT eligible, None if eligible.
        """
        # Check 1: Central line present
        if not data.line_present:
            eligibility_checks.append("FAIL: No central line documented")
            return ClassificationResult(
                classification=CLABSIClassification.NOT_ELIGIBLE,
                confidence=0.95,
                reasoning=["No central line documented at time of positive culture"],
                requires_review=False,
                review_reasons=[],
                eligibility_checks=eligibility_checks,
            )
        eligibility_checks.append("PASS: Central line present")

        # Check 2: Minimum line days
        line_days = data.line_days_at_culture
        if line_days is not None and line_days < MIN_LINE_DAYS:
            eligibility_checks.append(
                f"FAIL: Line days ({line_days}) < minimum ({MIN_LINE_DAYS})"
            )
            return ClassificationResult(
                classification=CLABSIClassification.NOT_ELIGIBLE,
                confidence=0.95,
                reasoning=[
                    f"Central line in place for {line_days} days, "
                    f"less than required {MIN_LINE_DAYS} days for CLABSI"
                ],
                requires_review=False,
                review_reasons=[],
                eligibility_checks=eligibility_checks,
            )
        eligibility_checks.append(f"PASS: Line days ({line_days}) >= {MIN_LINE_DAYS}")

        # Check 3: Line removal timing (if removed)
        if data.line_removal_date and data.culture_date:
            removal_date = data.line_removal_date
            culture_date = data.culture_date

            # Culture must be on day of or day after removal
            days_after_removal = (culture_date - removal_date).days

            if days_after_removal > POST_REMOVAL_ATTRIBUTION_DAYS:
                eligibility_checks.append(
                    f"FAIL: Culture {days_after_removal} days after line removal "
                    f"(max {POST_REMOVAL_ATTRIBUTION_DAYS})"
                )
                return ClassificationResult(
                    classification=CLABSIClassification.NOT_ELIGIBLE,
                    confidence=0.95,
                    reasoning=[
                        f"Culture drawn {days_after_removal} days after line removal. "
                        f"NHSN requires culture within {POST_REMOVAL_ATTRIBUTION_DAYS} "
                        f"day(s) of removal for CLABSI attribution."
                    ],
                    requires_review=False,
                    review_reasons=[],
                    eligibility_checks=eligibility_checks,
                )
            eligibility_checks.append(
                f"PASS: Culture within {POST_REMOVAL_ATTRIBUTION_DAYS} day(s) of line removal"
            )

        # Check 4: Patient days (not present on admission)
        patient_days = data.patient_days_at_culture
        if patient_days is not None and patient_days < MIN_PATIENT_DAYS_FOR_HAI:
            eligibility_checks.append(
                f"FAIL: Patient day {patient_days} < {MIN_PATIENT_DAYS_FOR_HAI} (POA)"
            )
            return ClassificationResult(
                classification=CLABSIClassification.NOT_ELIGIBLE,
                confidence=0.95,
                reasoning=[
                    f"Positive culture on hospital day {patient_days}. "
                    f"Infections on days 1-{MIN_PATIENT_DAYS_FOR_HAI - 1} are "
                    f"considered present on admission."
                ],
                requires_review=False,
                review_reasons=[],
                eligibility_checks=eligibility_checks,
            )
        eligibility_checks.append(f"PASS: Patient day {patient_days} >= {MIN_PATIENT_DAYS_FOR_HAI}")

        reasoning.append("Case meets basic CLABSI eligibility criteria")
        return None  # Eligible - continue evaluation

    def _evaluate_mbi_lcbi(
        self,
        extraction: ClinicalExtraction,
        data: StructuredCaseData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> ClassificationResult | None:
        """Evaluate MBI-LCBI criteria.

        MBI-LCBI requires:
        1. Eligible organism (intestinal/oral flora)
        2. Eligible patient (allo-HSCT <=365 days OR neutropenic ANC<500)
        3. Documented mucosal barrier injury (mucositis, GI GVHD, NEC)

        Returns ClassificationResult if MBI-LCBI, None otherwise.
        """
        organism = data.organism
        mbi = extraction.mbi_factors

        # Step 1: Check organism eligibility
        if not is_mbi_eligible_organism(organism):
            reasoning.append(f"MBI-LCBI: {organism} is not an MBI-eligible organism")
            return None

        reasoning.append(f"MBI-LCBI: {organism} IS an MBI-eligible organism")

        # Step 2: Check patient population eligibility
        population_eligible = False
        population_reason = None

        # Check for neutropenia (ANC < 500)
        neutropenic_from_labs = any(
            anc < NEUTROPENIA_ANC_THRESHOLD for anc in data.anc_values_7_days
        )
        neutropenic_from_notes = mbi.neutropenia_documented in [
            ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE
        ]
        neutropenic_anc = mbi.anc_value

        if neutropenic_from_labs:
            population_eligible = True
            min_anc = min(data.anc_values_7_days)
            population_reason = f"Neutropenic (ANC {min_anc} from labs)"
        elif neutropenic_from_notes and neutropenic_anc and neutropenic_anc < NEUTROPENIA_ANC_THRESHOLD:
            population_eligible = True
            population_reason = f"Neutropenic (ANC {neutropenic_anc} per notes)"
        elif neutropenic_from_notes:
            # Notes say neutropenic but no value - flag for review
            population_eligible = True
            population_reason = "Neutropenia documented in notes (ANC value not extracted)"
            review_reasons.append("Verify ANC value for MBI-LCBI neutropenia criterion")

        # Check for allogeneic HSCT within window
        if data.is_transplant_patient and data.transplant_type == "allogeneic":
            if data.transplant_date:
                days_post = (data.culture_date - data.transplant_date).days
                if days_post <= ALLO_HSCT_MBI_WINDOW_DAYS:
                    population_eligible = True
                    population_reason = f"Allogeneic HSCT day +{days_post}"

        # Check notes for transplant if not in structured data
        if not population_eligible:
            if mbi.stem_cell_transplant in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                if mbi.transplant_type == "allogeneic" or mbi.transplant_type == "allo":
                    days_post = mbi.days_post_transplant
                    if days_post and days_post <= ALLO_HSCT_MBI_WINDOW_DAYS:
                        population_eligible = True
                        population_reason = f"Allogeneic HSCT day +{days_post} (per notes)"

        if not population_eligible:
            reasoning.append("MBI-LCBI: Patient does not meet population criteria (not neutropenic, not allo-HSCT)")
            return None

        reasoning.append(f"MBI-LCBI: Patient meets population criteria - {population_reason}")

        # Step 3: Check for mucosal barrier injury
        has_mbi = False
        mbi_type = None

        # Check mucositis
        if mbi.mucositis_documented in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            has_mbi = True
            grade = f" (grade {mbi.mucositis_grade})" if mbi.mucositis_grade else ""
            mbi_type = f"mucositis{grade}"

        # Check GI GVHD
        if mbi.gi_gvhd_documented in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            has_mbi = True
            grade = f" (grade {mbi.gi_gvhd_grade})" if mbi.gi_gvhd_grade else ""
            mbi_type = f"GI GVHD{grade}"

        # Check NEC (for neonates)
        if mbi.nec_documented in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            has_mbi = True
            mbi_type = "necrotizing enterocolitis"

        if not has_mbi:
            # Check for possible MBI - flag for review
            if mbi.mucositis_documented == ConfidenceLevel.POSSIBLE:
                review_reasons.append("Possible mucositis mentioned - verify for MBI-LCBI")
            if mbi.gi_gvhd_documented == ConfidenceLevel.POSSIBLE:
                review_reasons.append("Possible GI GVHD mentioned - verify for MBI-LCBI")
            if mbi.severe_diarrhea in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                review_reasons.append("Severe diarrhea documented - consider MBI-LCBI")

            reasoning.append("MBI-LCBI: No definite mucosal barrier injury documented")
            return None

        reasoning.append(f"MBI-LCBI: Mucosal barrier injury documented - {mbi_type}")

        # All MBI-LCBI criteria met
        review_reasons.append("MBI-LCBI classification requires IP verification")

        return ClassificationResult(
            classification=CLABSIClassification.MBI_LCBI,
            confidence=0.80,  # MBI-LCBI always moderate confidence
            reasoning=reasoning + [
                f"CLASSIFICATION: MBI-LCBI",
                f"- Organism ({organism}) is intestinal/oral flora",
                f"- Patient meets population criteria ({population_reason})",
                f"- Mucosal barrier injury documented ({mbi_type})",
                "Per NHSN, this is MBI-LCBI, not CLABSI"
            ],
            requires_review=True,
            review_reasons=review_reasons,
            mbi_lcbi_evaluation=f"MBI-LCBI criteria met: {organism}, {population_reason}, {mbi_type}",
        )

    def _evaluate_secondary_bsi(
        self,
        extraction: ClinicalExtraction,
        data: StructuredCaseData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> ClassificationResult | None:
        """Evaluate for secondary BSI (alternate infection source).

        A BSI is secondary if:
        1. An infection at another site is documented
        2. The same organism is identified at that site
        3. The infection window timing is appropriate

        Returns ClassificationResult if secondary BSI, None otherwise.
        """
        organism = data.organism.lower() if data.organism else ""

        # Check structured data for matching cultures at other sites
        if data.matching_organism_other_sites:
            sites = ", ".join(data.matching_organism_other_sites)
            reasoning.append(f"Secondary BSI: Same organism found at other site(s): {sites}")

            return ClassificationResult(
                classification=CLABSIClassification.SECONDARY_BSI,
                confidence=0.90,
                reasoning=reasoning + [
                    f"CLASSIFICATION: Secondary BSI",
                    f"Same organism ({data.organism}) isolated from: {sites}",
                    "BSI is secondary to infection at other site per NHSN criteria"
                ],
                requires_review=False,
                review_reasons=[],
                secondary_bsi_evaluation=f"Same organism at: {sites}",
            )

        # Check LLM-extracted alternate sources
        high_confidence_sources = []
        possible_sources = []

        for alt_site in extraction.alternate_infection_sites:
            if alt_site.confidence == ConfidenceLevel.DEFINITE:
                if alt_site.same_organism_mentioned or alt_site.culture_from_site_positive:
                    high_confidence_sources.append(alt_site)
                else:
                    possible_sources.append(alt_site)

            elif alt_site.confidence == ConfidenceLevel.PROBABLE:
                if alt_site.same_organism_mentioned or alt_site.culture_from_site_positive:
                    high_confidence_sources.append(alt_site)
                else:
                    possible_sources.append(alt_site)

            elif alt_site.confidence == ConfidenceLevel.POSSIBLE:
                possible_sources.append(alt_site)

        # High confidence secondary source
        if high_confidence_sources:
            source = high_confidence_sources[0]
            reasoning.append(
                f"Secondary BSI: {source.site} documented with same organism"
            )

            confidence = 0.90 if source.confidence == ConfidenceLevel.DEFINITE else 0.80

            return ClassificationResult(
                classification=CLABSIClassification.SECONDARY_BSI,
                confidence=confidence,
                reasoning=reasoning + [
                    f"CLASSIFICATION: Secondary BSI",
                    f"Primary infection source: {source.site}",
                    f"Documentation: {source.supporting_quote[:200]}..." if len(source.supporting_quote) > 200 else f"Documentation: {source.supporting_quote}",
                    "BSI attributed to this infection source per NHSN criteria"
                ],
                requires_review=source.confidence != ConfidenceLevel.DEFINITE,
                review_reasons=[f"Verify {source.site} as primary source"] if source.confidence != ConfidenceLevel.DEFINITE else [],
                secondary_bsi_evaluation=f"Primary source: {source.site}",
            )

        # Possible sources - flag for review but don't classify
        if possible_sources:
            for source in possible_sources:
                review_reasons.append(
                    f"Possible alternate source ({source.site}) mentioned - verify"
                )
            reasoning.append(f"Secondary BSI: {len(possible_sources)} possible alternate source(s) identified")

        return None

    def _evaluate_contamination(
        self,
        extraction: ClinicalExtraction,
        data: StructuredCaseData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> ClassificationResult | None:
        """Evaluate for contamination.

        A culture is likely contamination if:
        1. Organism is a common commensal AND
        2. Only one positive culture (no matching second culture)

        Also considers clinical signals of contamination.

        Returns ClassificationResult if contamination, None otherwise.
        """
        organism = data.organism
        is_commensal = is_commensal_organism(organism)

        if is_commensal:
            reasoning.append(f"Contamination check: {organism} is a common commensal organism")

            if not data.has_second_culture_match:
                reasoning.append("Contamination: No second matching culture found")

                return ClassificationResult(
                    classification=CLABSIClassification.CONTAMINATION,
                    confidence=0.90,
                    reasoning=reasoning + [
                        f"CLASSIFICATION: Contamination",
                        f"Single positive culture with common commensal ({organism})",
                        "NHSN requires two positive cultures from separate blood draws "
                        "on separate days for common commensals"
                    ],
                    requires_review=False,
                    review_reasons=[],
                )

            # Has matching second culture - meets criterion
            reasoning.append(
                f"Contamination: Two matching cultures for {organism} - meets LCBI criterion"
            )

        # Check clinical signals of contamination
        contam = extraction.contamination

        if contam.documented_as_contaminant == ConfidenceLevel.DEFINITE:
            review_reasons.append("Clinical team documented as contamination - verify")
            reasoning.append("Contamination: Team explicitly documented as contaminant")

        if contam.treated_as_contaminant == ConfidenceLevel.DEFINITE:
            review_reasons.append("No antibiotics given for this culture - verify if treated as contaminant")

        if contam.antibiotics_stopped_early in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            review_reasons.append("Antibiotics stopped early - possible contamination")

        return None

    def _classify_as_clabsi(
        self,
        extraction: ClinicalExtraction,
        data: StructuredCaseData,
        reasoning: list[str],
        review_reasons: list[str],
        eligibility_checks: list[str],
    ) -> ClassificationResult:
        """Default classification as CLABSI.

        If no exclusion criteria are met, the case is classified as CLABSI.
        """
        reasoning.append("No exclusion criteria met - classifying as CLABSI")

        # Calculate confidence based on documentation quality and flags
        confidence = self._calculate_confidence(extraction, review_reasons)

        # Add line assessment to reasoning if relevant
        line = extraction.line_assessment
        if line.line_infection_suspected in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            reasoning.append("Line infection explicitly suspected by clinical team")

        if line.line_removed_for_infection in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            reasoning.append("Line was removed due to suspected infection")

        # Final reasoning
        final_reasoning = reasoning + [
            f"CLASSIFICATION: CLABSI",
            f"- Central line in place {data.line_days_at_culture} days at time of culture",
            f"- Organism: {data.organism}",
            "- No alternate infection source identified",
            "- Meets NHSN CLABSI criteria"
        ]

        requires_review = (
            len(review_reasons) > 0 or
            confidence < self.review_threshold or
            (self.strict_mode and extraction.documentation_quality in ["poor", "limited"])
        )

        if extraction.documentation_quality == "poor":
            review_reasons.append("Documentation quality is poor - limited clinical context")

        return ClassificationResult(
            classification=CLABSIClassification.CLABSI,
            confidence=confidence,
            reasoning=final_reasoning,
            requires_review=requires_review,
            review_reasons=review_reasons,
            eligibility_checks=eligibility_checks,
        )

    def _calculate_confidence(
        self,
        extraction: ClinicalExtraction,
        review_reasons: list[str],
    ) -> float:
        """Calculate confidence score based on extraction quality and flags.

        Confidence represents how certain we are in the classification,
        not the probability that it's a CLABSI.
        """
        base_confidence = 0.85

        # Deductions for documentation quality
        quality_deductions = {
            "poor": 0.20,
            "limited": 0.10,
            "adequate": 0.0,
            "detailed": -0.05,  # Bonus for detailed docs
        }
        base_confidence -= quality_deductions.get(extraction.documentation_quality, 0)

        # Deductions for review flags
        if len(review_reasons) > 3:
            base_confidence -= 0.15
        elif len(review_reasons) > 1:
            base_confidence -= 0.10
        elif len(review_reasons) > 0:
            base_confidence -= 0.05

        # Boost for clear-cut cases
        if (len(extraction.alternate_infection_sites) == 0 and
            extraction.contamination.treated_as_contaminant == ConfidenceLevel.NOT_FOUND and
            extraction.line_assessment.line_infection_suspected in [
                ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE
            ]):
            base_confidence += 0.05

        # Clamp to valid range
        return max(0.50, min(0.95, base_confidence))


# =============================================================================
# Convenience functions
# =============================================================================

def classify_clabsi(
    extraction: ClinicalExtraction,
    structured_data: StructuredCaseData,
    strict_mode: bool = True,
) -> ClassificationResult:
    """Convenience function to classify a CLABSI case.

    Args:
        extraction: LLM-extracted clinical information
        structured_data: Discrete EHR data
        strict_mode: Whether to flag borderline cases for review

    Returns:
        ClassificationResult
    """
    engine = CLABSIRulesEngine(strict_mode=strict_mode)
    return engine.classify(extraction, structured_data)
