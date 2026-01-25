"""VAE rules engine - deterministic NHSN criteria application.

This module applies NHSN VAE criteria to LLM-extracted clinical data
combined with structured EHR data. The rules are deterministic - given
the same inputs, you get the same outputs.

NHSN VAE Hierarchy (most specific first):
1. Probable VAP - IVAC + purulent secretions + positive quantitative culture
2. Possible VAP - IVAC + purulent secretions OR positive respiratory culture
3. IVAC - VAC + temperature/WBC abnormality + new antimicrobial ≥4 days
4. VAC - ≥2 days stable followed by ≥2 days sustained worsening (handled by detector)

The engine follows this decision tree:
1. Verify VAC criteria (from candidate detector)
2. Check IVAC criteria (infection indicators)
3. Check Probable VAP criteria (most specific)
4. Check Possible VAP criteria
5. Default to VAC only or NOT_VAE
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, date, timedelta

from .schemas import ConfidenceLevel
from .vae_schemas import (
    VAEExtraction,
    VAEStructuredData,
    VAEClassification,
    VAETier,
    VAEClassificationResult,
)
from .nhsn_criteria import (
    VAE_MIN_VENT_DAYS,
    VAE_FIO2_INCREASE_THRESHOLD,
    VAE_PEEP_INCREASE_THRESHOLD,
    IVAC_FEVER_THRESHOLD_CELSIUS,
    IVAC_HYPOTHERMIA_THRESHOLD_CELSIUS,
    IVAC_LEUKOCYTOSIS_THRESHOLD,
    IVAC_LEUKOPENIA_THRESHOLD,
    IVAC_ANTIMICROBIAL_MIN_DAYS,
    IVAC_ANTIMICROBIAL_WINDOW_DAYS_BEFORE,
    IVAC_ANTIMICROBIAL_WINDOW_DAYS_AFTER,
    is_qualifying_antimicrobial,
    meets_vap_quantitative_threshold,
    VAP_PURULENT_PMN_THRESHOLD,
    VAP_PURULENT_EPITHELIAL_MAX,
)

logger = logging.getLogger(__name__)


class VAERulesEngine:
    """Deterministic NHSN criteria application for VAE classification.

    This engine takes:
    1. VAEExtraction - what the LLM extracted from notes
    2. VAEStructuredData - discrete EHR data (ventilator params, labs, etc.)

    And produces:
    - VAEClassificationResult with full reasoning chain

    The engine is transparent and auditable - every decision is logged
    with the specific rule that was applied.

    NHSN VAE Classification Hierarchy (most specific first):
    - Probable VAP > Possible VAP > IVAC > VAC
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
        extraction: VAEExtraction,
        structured_data: VAEStructuredData,
    ) -> VAEClassificationResult:
        """Apply NHSN rules to classify a potential VAE.

        This is the main entry point. It runs through the NHSN decision
        tree in order:
        1. Verify VAC (baseline eligibility)
        2. Check IVAC criteria
        3. Check Probable VAP (most specific, check first)
        4. Check Possible VAP
        5. Return VAC only or NOT_VAE if no higher criteria met

        Args:
            extraction: LLM-extracted clinical information
            structured_data: Discrete EHR data

        Returns:
            VAEClassificationResult with classification and reasoning
        """
        reasoning = []
        review_reasons = []

        # === STEP 1: Verify VAC (Baseline Eligibility) ===
        vac_result = self._verify_vac(structured_data, reasoning, review_reasons)
        if vac_result is None:
            # VAC not verified - classify as NOT_VAE
            return VAEClassificationResult(
                classification=VAEClassification.NOT_ELIGIBLE,
                vae_tier=None,
                confidence=0.90,
                reasoning=reasoning + ["VAC criteria not verified - not eligible for VAE"],
                requires_review=False,
                review_reasons=review_reasons,
                vac_met=False,
            )

        # VAC is verified
        reasoning.append("VAC criteria verified by candidate detector")
        vac_onset_date = structured_data.vac_onset_date

        # Track IVAC criteria
        ivac_criteria = {
            "temperature_met": False,
            "wbc_met": False,
            "antimicrobial_met": False,
            "qualifying_antimicrobials": [],
        }

        # === STEP 2: Check IVAC Criteria ===
        ivac_met = self._evaluate_ivac_criteria(
            extraction, structured_data, reasoning, review_reasons, ivac_criteria
        )

        if not ivac_met:
            # VAC only - no IVAC criteria met
            return self._classify_as_vac(
                structured_data, reasoning, review_reasons, extraction
            )

        # IVAC criteria met - check for VAP

        # Track VAP criteria
        vap_criteria = {
            "purulent_secretions": False,
            "positive_culture": False,
            "quantitative_threshold": False,
            "organism": None,
            "specimen_type": None,
        }

        # === STEP 3: Check Probable VAP Criteria ===
        probable_vap = self._evaluate_probable_vap(
            extraction, structured_data, reasoning, review_reasons, vap_criteria
        )
        if probable_vap:
            return self._classify_as_probable_vap(
                structured_data, reasoning, review_reasons,
                ivac_criteria, vap_criteria, extraction
            )

        # === STEP 4: Check Possible VAP Criteria ===
        possible_vap = self._evaluate_possible_vap(
            extraction, structured_data, reasoning, review_reasons, vap_criteria
        )
        if possible_vap:
            return self._classify_as_possible_vap(
                structured_data, reasoning, review_reasons,
                ivac_criteria, vap_criteria, extraction
            )

        # === STEP 5: IVAC Only ===
        return self._classify_as_ivac(
            structured_data, reasoning, review_reasons,
            ivac_criteria, extraction
        )

    def _verify_vac(
        self,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> bool | None:
        """Verify VAC criteria from structured data.

        VAC is detected by the candidate detector based on:
        - ≥2 days on mechanical ventilation
        - ≥2 days stable/decreasing FiO2 or PEEP (baseline)
        - ≥2 days of sustained increase in FiO2 ≥20% or PEEP ≥3 cmH2O

        Returns True if VAC verified, None if not.
        """
        # Check ventilator days
        if data.ventilator_days < VAE_MIN_VENT_DAYS:
            reasoning.append(
                f"Insufficient ventilator days: {data.ventilator_days} < {VAE_MIN_VENT_DAYS}"
            )
            return None

        reasoning.append(f"Ventilator days: {data.ventilator_days}")

        # Check that VAC onset was identified
        if data.vac_onset_date is None:
            reasoning.append("No VAC onset date identified")
            return None

        reasoning.append(f"VAC onset date: {data.vac_onset_date}")

        # Check FiO2/PEEP thresholds
        fio2_met = (
            data.fio2_increase is not None and
            data.fio2_increase >= VAE_FIO2_INCREASE_THRESHOLD
        )
        peep_met = (
            data.peep_increase is not None and
            data.peep_increase >= VAE_PEEP_INCREASE_THRESHOLD
        )

        if fio2_met:
            reasoning.append(
                f"FiO2 increase: {data.fio2_increase}% (threshold: {VAE_FIO2_INCREASE_THRESHOLD}%)"
            )
        if peep_met:
            reasoning.append(
                f"PEEP increase: {data.peep_increase} cmH2O (threshold: {VAE_PEEP_INCREASE_THRESHOLD})"
            )

        if not fio2_met and not peep_met:
            reasoning.append("Neither FiO2 nor PEEP threshold met")
            return None

        return True

    def _evaluate_ivac_criteria(
        self,
        extraction: VAEExtraction,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        ivac_criteria: dict,
    ) -> bool:
        """Evaluate IVAC (Infection-Related VAC) criteria.

        IVAC requires ALL of:
        1. VAC criteria met (verified above)
        2. Temperature >38°C or <36°C
        3. WBC ≥12,000 or ≤4,000 cells/mm³
        4. New qualifying antimicrobial started ±2 days from VAC onset,
           continued for ≥4 calendar days

        Note: NHSN requires EITHER temp OR WBC criterion (#2 or #3),
        not both. The antimicrobial criterion (#4) is always required.

        Returns True if IVAC criteria met.
        """
        # Check temperature criterion
        temp_met = self._check_temperature_criterion(
            extraction, data, reasoning, review_reasons
        )
        ivac_criteria["temperature_met"] = temp_met

        # Check WBC criterion
        wbc_met = self._check_wbc_criterion(
            extraction, data, reasoning, review_reasons
        )
        ivac_criteria["wbc_met"] = wbc_met

        # Need at least one of temperature or WBC
        if not temp_met and not wbc_met:
            reasoning.append("IVAC: Neither temperature nor WBC criterion met")
            return False

        # Check antimicrobial criterion
        abx_met, qualifying_abx = self._check_antimicrobial_criterion(
            extraction, data, reasoning, review_reasons
        )
        ivac_criteria["antimicrobial_met"] = abx_met
        ivac_criteria["qualifying_antimicrobials"] = qualifying_abx

        if not abx_met:
            reasoning.append("IVAC: Antimicrobial criterion not met")
            return False

        reasoning.append("IVAC criteria met")
        return True

    def _check_temperature_criterion(
        self,
        extraction: VAEExtraction,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> bool:
        """Check temperature criterion for IVAC.

        Criterion: Temperature >38°C or <36°C
        """
        temp = extraction.temperature

        # Check for fever
        if temp.fever_documented in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            if temp.max_temp_celsius and temp.max_temp_celsius > IVAC_FEVER_THRESHOLD_CELSIUS:
                reasoning.append(
                    f"Temperature criterion met: fever {temp.max_temp_celsius}°C > {IVAC_FEVER_THRESHOLD_CELSIUS}°C"
                )
                return True

        # Check for hypothermia
        if temp.hypothermia_documented in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            if temp.min_temp_celsius and temp.min_temp_celsius < IVAC_HYPOTHERMIA_THRESHOLD_CELSIUS:
                reasoning.append(
                    f"Temperature criterion met: hypothermia {temp.min_temp_celsius}°C < {IVAC_HYPOTHERMIA_THRESHOLD_CELSIUS}°C"
                )
                return True

        # Check structured data for temps
        for temp_date, temp_value in data.temperatures:
            if temp_value > IVAC_FEVER_THRESHOLD_CELSIUS:
                reasoning.append(
                    f"Temperature criterion met (from EHR): {temp_value}°C on {temp_date.date()}"
                )
                return True
            if temp_value < IVAC_HYPOTHERMIA_THRESHOLD_CELSIUS:
                reasoning.append(
                    f"Temperature criterion met (from EHR): {temp_value}°C on {temp_date.date()}"
                )
                return True

        # Check for possible findings
        if temp.fever_documented == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible fever documented - verify temperature values")
        if temp.hypothermia_documented == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible hypothermia documented - verify temperature values")

        return False

    def _check_wbc_criterion(
        self,
        extraction: VAEExtraction,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> bool:
        """Check WBC criterion for IVAC.

        Criterion: WBC ≥12,000 or ≤4,000 cells/mm³
        """
        wbc = extraction.wbc

        # Check for leukocytosis
        if wbc.leukocytosis_documented in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            if wbc.max_wbc and wbc.max_wbc >= IVAC_LEUKOCYTOSIS_THRESHOLD:
                reasoning.append(
                    f"WBC criterion met: leukocytosis {wbc.max_wbc} >= {IVAC_LEUKOCYTOSIS_THRESHOLD}"
                )
                return True

        # Check for leukopenia
        if wbc.leukopenia_documented in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            if wbc.min_wbc and wbc.min_wbc <= IVAC_LEUKOPENIA_THRESHOLD:
                reasoning.append(
                    f"WBC criterion met: leukopenia {wbc.min_wbc} <= {IVAC_LEUKOPENIA_THRESHOLD}"
                )
                return True

        # Check structured data for WBC
        for wbc_date, wbc_value in data.wbc_values:
            if wbc_value >= IVAC_LEUKOCYTOSIS_THRESHOLD:
                reasoning.append(
                    f"WBC criterion met (from EHR): {wbc_value} on {wbc_date.date()}"
                )
                return True
            if wbc_value <= IVAC_LEUKOPENIA_THRESHOLD:
                reasoning.append(
                    f"WBC criterion met (from EHR): {wbc_value} on {wbc_date.date()}"
                )
                return True

        # Check for possible findings
        if wbc.leukocytosis_documented == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible leukocytosis documented - verify WBC values")
        if wbc.leukopenia_documented == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible leukopenia documented - verify WBC values")

        return False

    def _check_antimicrobial_criterion(
        self,
        extraction: VAEExtraction,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> tuple[bool, list[str]]:
        """Check antimicrobial criterion for IVAC.

        Criterion: New qualifying antimicrobial agent(s) started
        ±2 days from VAC onset and continued for ≥4 calendar days.

        Returns (criterion_met, list of qualifying antimicrobials)
        """
        qualifying = []
        vac_onset = data.vac_onset_date

        if vac_onset is None:
            return False, []

        # Check extracted antimicrobials
        for abx in extraction.antimicrobials:
            if abx.new_antimicrobial_started in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                for drug_name in abx.antimicrobial_names:
                    if is_qualifying_antimicrobial(drug_name):
                        # Check if continued ≥4 days
                        duration_ok = (
                            abx.continued_four_or_more_days in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE] or
                            (abx.duration_days is not None and abx.duration_days >= IVAC_ANTIMICROBIAL_MIN_DAYS)
                        )

                        if duration_ok:
                            qualifying.append(drug_name)
                            reasoning.append(
                                f"Qualifying antimicrobial: {drug_name} (≥{IVAC_ANTIMICROBIAL_MIN_DAYS} days)"
                            )

        # Check structured data for antimicrobials
        for abx_info in data.qualifying_antimicrobials:
            drug = abx_info.get("drug", "")
            days = abx_info.get("days_on_drug", 0)

            if is_qualifying_antimicrobial(drug) and days >= IVAC_ANTIMICROBIAL_MIN_DAYS:
                if drug not in qualifying:
                    qualifying.append(drug)
                    reasoning.append(
                        f"Qualifying antimicrobial (from EHR): {drug} ({days} days)"
                    )

        # Check for possible findings
        for abx in extraction.antimicrobials:
            if abx.new_antimicrobial_started == ConfidenceLevel.POSSIBLE:
                review_reasons.append("Possible new antimicrobial - verify start date and duration")
            if abx.continued_four_or_more_days == ConfidenceLevel.POSSIBLE:
                review_reasons.append("Uncertain antimicrobial duration - verify ≥4 days")

        if qualifying:
            return True, qualifying
        else:
            reasoning.append("No qualifying antimicrobials found for ≥4 days")
            return False, []

    def _evaluate_probable_vap(
        self,
        extraction: VAEExtraction,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        vap_criteria: dict,
    ) -> bool:
        """Evaluate Probable VAP criteria.

        Probable VAP requires IVAC criteria PLUS:
        1. Purulent secretions (≥25 PMNs and ≤10 epithelial cells per LPF)
        2. Positive quantitative respiratory culture meeting threshold

        Returns True if Probable VAP criteria met.
        """
        # Check purulent secretions
        purulent = self._check_purulent_secretions(extraction, reasoning, review_reasons)
        vap_criteria["purulent_secretions"] = purulent

        if not purulent:
            return False

        # Check quantitative culture
        quant_met, organism, specimen = self._check_quantitative_culture(
            extraction, data, reasoning, review_reasons
        )
        vap_criteria["quantitative_threshold"] = quant_met
        vap_criteria["organism"] = organism
        vap_criteria["specimen_type"] = specimen

        if not quant_met:
            return False

        reasoning.append("Probable VAP criteria met: purulent secretions + quantitative culture")
        return True

    def _evaluate_possible_vap(
        self,
        extraction: VAEExtraction,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        vap_criteria: dict,
    ) -> bool:
        """Evaluate Possible VAP criteria.

        Possible VAP requires IVAC criteria PLUS one of:
        1. Purulent secretions (≥25 PMNs and ≤10 epithelial cells per LPF)
        2. Positive respiratory culture (qualitative - any growth)

        Returns True if Possible VAP criteria met.
        """
        # Already checked purulent secretions in probable VAP
        if vap_criteria["purulent_secretions"]:
            reasoning.append("Possible VAP criteria met: purulent secretions")
            return True

        # Check for positive respiratory culture (qualitative)
        positive_culture, organism, specimen = self._check_positive_culture(
            extraction, data, reasoning, review_reasons
        )
        vap_criteria["positive_culture"] = positive_culture
        if organism:
            vap_criteria["organism"] = organism
        if specimen:
            vap_criteria["specimen_type"] = specimen

        if positive_culture:
            reasoning.append("Possible VAP criteria met: positive respiratory culture")
            return True

        return False

    def _check_purulent_secretions(
        self,
        extraction: VAEExtraction,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> bool:
        """Check for purulent secretions per NHSN definition.

        Purulent = ≥25 PMNs and ≤10 epithelial cells per LPF on gram stain.
        """
        sec = extraction.secretions

        # Check gram stain criteria
        if sec.gram_stain_positive in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            # Verify PMN and epithelial counts if available
            if sec.pmn_count is not None and sec.epithelial_count is not None:
                if sec.pmn_count >= VAP_PURULENT_PMN_THRESHOLD and sec.epithelial_count <= VAP_PURULENT_EPITHELIAL_MAX:
                    reasoning.append(
                        f"Purulent secretions met: {sec.pmn_count} PMNs, {sec.epithelial_count} epithelial cells"
                    )
                    return True
            else:
                # Gram stain positive but no counts - trust documentation
                reasoning.append("Purulent secretions documented (gram stain positive)")
                return True

        # Check descriptive purulent secretions
        if sec.purulent_secretions in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
            reasoning.append(f"Purulent secretions documented: {sec.secretion_description or 'purulent'}")
            return True

        # Check for possible findings
        if sec.purulent_secretions == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible purulent secretions - verify character of secretions")
        if sec.gram_stain_positive == ConfidenceLevel.POSSIBLE:
            review_reasons.append("Possible gram stain criteria met - verify PMN/epithelial counts")

        return False

    def _check_quantitative_culture(
        self,
        extraction: VAEExtraction,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> tuple[bool, str | None, str | None]:
        """Check for positive quantitative culture meeting threshold.

        Returns (met, organism, specimen_type)
        """
        # Check extracted cultures
        for cx in extraction.cultures:
            if cx.meets_quantitative_threshold in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                reasoning.append(
                    f"Quantitative culture threshold met: {cx.organism_identified or 'organism'} "
                    f"from {cx.specimen_type or 'respiratory specimen'} ({cx.colony_count or 'threshold met'})"
                )
                return True, cx.organism_identified, cx.specimen_type

            # Check if we can calculate threshold ourselves
            if cx.culture_positive in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                if cx.specimen_type and cx.colony_count:
                    # Parse colony count (e.g., "10^5 CFU/mL")
                    try:
                        count = self._parse_colony_count(cx.colony_count)
                        if count and meets_vap_quantitative_threshold(cx.specimen_type, count):
                            reasoning.append(
                                f"Quantitative culture threshold met: {cx.organism_identified or 'organism'} "
                                f"from {cx.specimen_type} ({cx.colony_count})"
                            )
                            return True, cx.organism_identified, cx.specimen_type
                    except ValueError:
                        pass

        # Check structured data cultures
        for cx_data in data.respiratory_cultures:
            specimen = cx_data.get("specimen_type", "")
            count = cx_data.get("count", 0)
            organism = cx_data.get("organism", "")

            if meets_vap_quantitative_threshold(specimen, count):
                reasoning.append(
                    f"Quantitative culture threshold met (from EHR): {organism} "
                    f"from {specimen} ({count} CFU/mL)"
                )
                return True, organism, specimen

        return False, None, None

    def _check_positive_culture(
        self,
        extraction: VAEExtraction,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
    ) -> tuple[bool, str | None, str | None]:
        """Check for any positive respiratory culture (qualitative).

        Returns (met, organism, specimen_type)
        """
        # Check extracted cultures
        for cx in extraction.cultures:
            if cx.culture_positive in [ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE]:
                reasoning.append(
                    f"Positive respiratory culture: {cx.organism_identified or 'organism'} "
                    f"from {cx.specimen_type or 'respiratory specimen'}"
                )
                return True, cx.organism_identified, cx.specimen_type

        # Check structured data cultures
        for cx_data in data.respiratory_cultures:
            organism = cx_data.get("organism", "")
            specimen = cx_data.get("specimen_type", "")
            if organism:
                reasoning.append(
                    f"Positive respiratory culture (from EHR): {organism} from {specimen}"
                )
                return True, organism, specimen

        # Check for possible findings
        for cx in extraction.cultures:
            if cx.culture_positive == ConfidenceLevel.POSSIBLE:
                review_reasons.append("Possible positive respiratory culture - verify results")

        return False, None, None

    def _parse_colony_count(self, count_str: str) -> int | None:
        """Parse colony count string to integer.

        Examples: "10^5 CFU/mL" -> 100000, "1e6" -> 1000000
        """
        import re

        if not count_str:
            return None

        # Try scientific notation (10^5, 1e5)
        sci_match = re.search(r'10\^(\d+)|(\d+)[eE](\d+)', count_str)
        if sci_match:
            if sci_match.group(1):
                return 10 ** int(sci_match.group(1))
            elif sci_match.group(2) and sci_match.group(3):
                return int(sci_match.group(2)) * (10 ** int(sci_match.group(3)))

        # Try plain number
        num_match = re.search(r'(\d+)', count_str.replace(',', ''))
        if num_match:
            return int(num_match.group(1))

        return None

    def _classify_as_vac(
        self,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        extraction: VAEExtraction,
    ) -> VAEClassificationResult:
        """Classify as VAC only (no IVAC criteria met)."""
        reasoning.append("CLASSIFICATION: VAC (Ventilator-Associated Condition)")
        reasoning.append("IVAC criteria not met - infection-related criteria absent")

        confidence = self._calculate_confidence(extraction, "vac", review_reasons)

        return VAEClassificationResult(
            classification=VAEClassification.VAC,
            vae_tier=VAETier.TIER_1,
            confidence=confidence,
            reasoning=reasoning,
            requires_review=len(review_reasons) > 0 or confidence < self.review_threshold,
            review_reasons=review_reasons,
            vac_met=True,
            vac_onset_date=data.vac_onset_date,
            baseline_period=f"{data.baseline_period_start} to {data.baseline_period_end}" if data.baseline_period_start else None,
            fio2_increase_details=f"{data.fio2_increase}% increase" if data.fio2_increase else None,
            peep_increase_details=f"{data.peep_increase} cmH2O increase" if data.peep_increase else None,
        )

    def _classify_as_ivac(
        self,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        ivac_criteria: dict,
        extraction: VAEExtraction,
    ) -> VAEClassificationResult:
        """Classify as IVAC (no VAP criteria met)."""
        reasoning.append("CLASSIFICATION: IVAC (Infection-related VAC)")
        reasoning.append("VAP criteria not met - no purulent secretions or positive culture")

        confidence = self._calculate_confidence(extraction, "ivac", review_reasons)

        return VAEClassificationResult(
            classification=VAEClassification.IVAC,
            vae_tier=VAETier.TIER_2,
            confidence=confidence,
            reasoning=reasoning,
            requires_review=len(review_reasons) > 0 or confidence < self.review_threshold,
            review_reasons=review_reasons,
            vac_met=True,
            vac_onset_date=data.vac_onset_date,
            baseline_period=f"{data.baseline_period_start} to {data.baseline_period_end}" if data.baseline_period_start else None,
            fio2_increase_details=f"{data.fio2_increase}% increase" if data.fio2_increase else None,
            peep_increase_details=f"{data.peep_increase} cmH2O increase" if data.peep_increase else None,
            ivac_met=True,
            temperature_criterion_met=ivac_criteria["temperature_met"],
            wbc_criterion_met=ivac_criteria["wbc_met"],
            antimicrobial_criterion_met=ivac_criteria["antimicrobial_met"],
            qualifying_antimicrobials=ivac_criteria["qualifying_antimicrobials"],
        )

    def _classify_as_possible_vap(
        self,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        ivac_criteria: dict,
        vap_criteria: dict,
        extraction: VAEExtraction,
    ) -> VAEClassificationResult:
        """Classify as Possible VAP."""
        reasoning.append("CLASSIFICATION: Possible VAP")

        confidence = self._calculate_confidence(extraction, "possible_vap", review_reasons)

        return VAEClassificationResult(
            classification=VAEClassification.POSSIBLE_VAP,
            vae_tier=VAETier.TIER_3,
            confidence=confidence,
            reasoning=reasoning,
            requires_review=len(review_reasons) > 0 or confidence < self.review_threshold,
            review_reasons=review_reasons,
            vac_met=True,
            vac_onset_date=data.vac_onset_date,
            baseline_period=f"{data.baseline_period_start} to {data.baseline_period_end}" if data.baseline_period_start else None,
            fio2_increase_details=f"{data.fio2_increase}% increase" if data.fio2_increase else None,
            peep_increase_details=f"{data.peep_increase} cmH2O increase" if data.peep_increase else None,
            ivac_met=True,
            temperature_criterion_met=ivac_criteria["temperature_met"],
            wbc_criterion_met=ivac_criteria["wbc_met"],
            antimicrobial_criterion_met=ivac_criteria["antimicrobial_met"],
            qualifying_antimicrobials=ivac_criteria["qualifying_antimicrobials"],
            vap_met=True,
            purulent_secretions_met=vap_criteria["purulent_secretions"],
            positive_culture_met=vap_criteria["positive_culture"],
            organism_identified=vap_criteria["organism"],
            specimen_type=vap_criteria["specimen_type"],
        )

    def _classify_as_probable_vap(
        self,
        data: VAEStructuredData,
        reasoning: list[str],
        review_reasons: list[str],
        ivac_criteria: dict,
        vap_criteria: dict,
        extraction: VAEExtraction,
    ) -> VAEClassificationResult:
        """Classify as Probable VAP."""
        reasoning.append("CLASSIFICATION: Probable VAP")

        confidence = self._calculate_confidence(extraction, "probable_vap", review_reasons)

        return VAEClassificationResult(
            classification=VAEClassification.PROBABLE_VAP,
            vae_tier=VAETier.TIER_3,
            confidence=confidence,
            reasoning=reasoning,
            requires_review=len(review_reasons) > 0 or confidence < self.review_threshold,
            review_reasons=review_reasons,
            vac_met=True,
            vac_onset_date=data.vac_onset_date,
            baseline_period=f"{data.baseline_period_start} to {data.baseline_period_end}" if data.baseline_period_start else None,
            fio2_increase_details=f"{data.fio2_increase}% increase" if data.fio2_increase else None,
            peep_increase_details=f"{data.peep_increase} cmH2O increase" if data.peep_increase else None,
            ivac_met=True,
            temperature_criterion_met=ivac_criteria["temperature_met"],
            wbc_criterion_met=ivac_criteria["wbc_met"],
            antimicrobial_criterion_met=ivac_criteria["antimicrobial_met"],
            qualifying_antimicrobials=ivac_criteria["qualifying_antimicrobials"],
            vap_met=True,
            purulent_secretions_met=True,  # Required for probable
            positive_culture_met=True,      # Required for probable
            quantitative_threshold_met=True,  # Required for probable
            organism_identified=vap_criteria["organism"],
            specimen_type=vap_criteria["specimen_type"],
        )

    def _calculate_confidence(
        self,
        extraction: VAEExtraction,
        classification: str,
        review_reasons: list[str],
    ) -> float:
        """Calculate confidence score based on extraction quality and classification.

        Confidence represents how certain we are in the classification,
        based on documentation quality.
        """
        base_confidence = {
            "vac": 0.80,
            "ivac": 0.75,
            "possible_vap": 0.75,
            "probable_vap": 0.85,  # Higher because both criteria met
        }.get(classification, 0.75)

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

def classify_vae(
    extraction: VAEExtraction,
    structured_data: VAEStructuredData,
    strict_mode: bool = True,
) -> VAEClassificationResult:
    """Convenience function to classify a VAE case.

    Args:
        extraction: LLM-extracted clinical information
        structured_data: Discrete EHR data
        strict_mode: Whether to flag borderline cases for review

    Returns:
        VAEClassificationResult
    """
    engine = VAERulesEngine(strict_mode=strict_mode)
    return engine.classify(extraction, structured_data)
