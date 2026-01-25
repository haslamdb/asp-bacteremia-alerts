"""CAUTI Rules Engine - Deterministic NHSN CAUTI criteria application.

This module applies NHSN CAUTI criteria deterministically to structured
data (from FHIR/EHR) combined with LLM-extracted clinical facts.

The LLM's job is extraction (what symptoms are documented, clinical
team's impression). The rules engine applies the NHSN criteria.

NHSN CAUTI Criteria:
1. Indwelling urinary catheter in place >2 calendar days
2. Positive urine culture >=10^5 CFU/mL with <=2 organisms
3. At least one sign/symptom: fever >38C, suprapubic tenderness,
   CVA pain/tenderness, urinary urgency, frequency, or dysuria
4. Not asymptomatic bacteriuria

Age-Based Fever Rule:
- Patient <=65 years: Fever can be used alone
- Patient >65 years: Fever alone requires catheter >2 days; other symptoms always valid
"""

import logging
from datetime import datetime

from .cauti_schemas import (
    CAUTIClassification,
    CAUTIExtraction,
    CAUTIStructuredData,
    CAUTIClassificationResult,
    UrinarySymptomExtraction,
)
from .schemas import ConfidenceLevel
from .nhsn_criteria import (
    CAUTI_MIN_CATHETER_DAYS,
    CAUTI_MIN_CFU_ML,
    CAUTI_MAX_ORGANISMS,
    CAUTI_FEVER_THRESHOLD_CELSIUS,
    CAUTI_FEVER_AGE_THRESHOLD,
    is_cauti_excluded_organism,
    is_valid_cauti_culture,
    is_cauti_fever_eligible,
)

logger = logging.getLogger(__name__)


class CAUTIRulesEngine:
    """Deterministic NHSN CAUTI criteria application.

    Takes LLM extraction (symptoms, clinical impression) and structured
    EHR data (catheter info, culture results, patient age) and applies
    NHSN criteria to produce a classification.

    Classification Flow:
    1. Verify catheter eligibility (>2 days)
    2. Verify culture criteria (>=10^5 CFU/mL, <=2 organisms)
    3. Check for at least one symptom
    4. Apply age-based fever rule (>65 years)
    5. Classify as CAUTI, asymptomatic bacteriuria, or not CAUTI
    """

    def __init__(self):
        self.min_catheter_days = CAUTI_MIN_CATHETER_DAYS
        self.min_cfu_ml = CAUTI_MIN_CFU_ML
        self.max_organisms = CAUTI_MAX_ORGANISMS
        self.fever_threshold = CAUTI_FEVER_THRESHOLD_CELSIUS
        self.fever_age_threshold = CAUTI_FEVER_AGE_THRESHOLD

    def classify(
        self,
        extraction: CAUTIExtraction,
        structured_data: CAUTIStructuredData,
    ) -> CAUTIClassificationResult:
        """Apply NHSN CAUTI criteria to produce classification.

        Args:
            extraction: LLM-extracted clinical facts
            structured_data: EHR discrete data (catheter, culture, patient)

        Returns:
            CAUTIClassificationResult with classification and reasoning
        """
        reasoning = []
        review_reasons = []

        # Step 1: Check catheter eligibility
        catheter_eligible = self._check_catheter_eligibility(structured_data, reasoning)

        # Step 2: Check culture eligibility
        culture_eligible = self._check_culture_eligibility(structured_data, reasoning)

        # Early return if not eligible
        if not catheter_eligible or not culture_eligible:
            return CAUTIClassificationResult(
                classification=CAUTIClassification.NOT_ELIGIBLE,
                confidence=0.95,
                reasoning=reasoning,
                requires_review=False,
                review_reasons=[],
                catheter_eligible=catheter_eligible,
                catheter_days=structured_data.catheter_days,
                catheter_type=structured_data.catheter_type,
                culture_eligible=culture_eligible,
                culture_cfu_ml=structured_data.culture_cfu_ml,
                culture_organism=structured_data.culture_organism,
                culture_organism_count=structured_data.culture_organism_count,
            )

        # Step 3: Evaluate symptoms
        symptom_result = self._evaluate_symptoms(
            extraction.symptoms,
            structured_data,
            reasoning,
        )

        (
            symptom_criterion_met,
            fever_documented,
            suprapubic_documented,
            cva_documented,
            urgency_documented,
            frequency_documented,
            dysuria_documented,
            fever_eligible_per_age_rule,
        ) = symptom_result

        # Step 4: Determine classification
        if symptom_criterion_met:
            classification = CAUTIClassification.CAUTI
            confidence = self._calculate_confidence(extraction, structured_data)
            reasoning.append("CAUTI criteria met: catheter >2 days + positive culture + symptoms")
        else:
            classification = CAUTIClassification.ASYMPTOMATIC_BACTERIURIA
            confidence = 0.85
            reasoning.append("Asymptomatic bacteriuria: positive culture but no qualifying symptoms documented")

        # Step 5: Determine if review needed
        requires_review, review_reasons = self._determine_review_need(
            classification, extraction, structured_data, confidence
        )

        return CAUTIClassificationResult(
            classification=classification,
            confidence=confidence,
            reasoning=reasoning,
            requires_review=requires_review,
            review_reasons=review_reasons,
            catheter_eligible=catheter_eligible,
            catheter_days=structured_data.catheter_days,
            catheter_type=structured_data.catheter_type,
            culture_eligible=culture_eligible,
            culture_cfu_ml=structured_data.culture_cfu_ml,
            culture_organism=structured_data.culture_organism,
            culture_organism_count=structured_data.culture_organism_count,
            symptom_criterion_met=symptom_criterion_met,
            fever_documented=fever_documented,
            suprapubic_tenderness_documented=suprapubic_documented,
            cva_tenderness_documented=cva_documented,
            urgency_documented=urgency_documented,
            frequency_documented=frequency_documented,
            dysuria_documented=dysuria_documented,
            patient_age=structured_data.patient_age,
            fever_eligible_per_age_rule=fever_eligible_per_age_rule,
        )

    def _check_catheter_eligibility(
        self,
        structured_data: CAUTIStructuredData,
        reasoning: list[str],
    ) -> bool:
        """Check if catheter eligibility criteria met.

        NHSN requires catheter in place >2 calendar days.
        """
        catheter_days = structured_data.catheter_days

        if catheter_days is None:
            reasoning.append("Unable to determine catheter days - not eligible")
            return False

        if catheter_days <= self.min_catheter_days:
            reasoning.append(
                f"Catheter days ({catheter_days}) <= minimum required ({self.min_catheter_days}) - not eligible"
            )
            return False

        reasoning.append(
            f"Catheter eligibility met: {catheter_days} days (> {self.min_catheter_days} required)"
        )
        return True

    def _check_culture_eligibility(
        self,
        structured_data: CAUTIStructuredData,
        reasoning: list[str],
    ) -> bool:
        """Check if culture eligibility criteria met.

        NHSN requires:
        - >=10^5 CFU/mL
        - <=2 organisms (no mixed flora)
        - Not excluded organism (Candida, yeast)
        """
        # Check CFU threshold
        cfu_ml = structured_data.culture_cfu_ml
        if cfu_ml is not None and cfu_ml < self.min_cfu_ml:
            reasoning.append(
                f"CFU/mL ({cfu_ml}) < minimum required ({self.min_cfu_ml}) - not eligible"
            )
            return False

        # Check organism count
        organism_count = structured_data.culture_organism_count
        if organism_count is not None and organism_count > self.max_organisms:
            reasoning.append(
                f"Mixed flora ({organism_count} organisms > {self.max_organisms}) - not eligible"
            )
            return False

        # Check excluded organisms
        organism = structured_data.culture_organism
        if organism and is_cauti_excluded_organism(organism):
            reasoning.append(f"Excluded organism ({organism}) - not eligible for CAUTI")
            return False

        # Build eligibility message
        eligibility_parts = []
        if cfu_ml is not None:
            eligibility_parts.append(f"{cfu_ml:,} CFU/mL")
        if organism_count is not None:
            eligibility_parts.append(f"{organism_count} organism(s)")
        if organism:
            eligibility_parts.append(f"organism: {organism}")

        reasoning.append(
            f"Culture eligibility met: {', '.join(eligibility_parts) if eligibility_parts else 'positive culture'}"
        )
        return True

    def _evaluate_symptoms(
        self,
        symptoms: UrinarySymptomExtraction,
        structured_data: CAUTIStructuredData,
        reasoning: list[str],
    ) -> tuple[bool, bool, bool, bool, bool, bool, bool, bool]:
        """Evaluate symptom criteria including age-based fever rule.

        NHSN requires at least one of:
        - Fever >38C
        - Suprapubic tenderness
        - CVA pain/tenderness
        - Urinary urgency
        - Urinary frequency
        - Dysuria

        Age-based fever rule:
        - Patient <=65: Fever alone is sufficient
        - Patient >65: Fever alone only valid if catheter >2 days

        Returns:
            Tuple of (symptom_criterion_met, fever, suprapubic, cva, urgency,
                     frequency, dysuria, fever_eligible_per_age_rule)
        """
        # Extract documented symptoms (DEFINITE or PROBABLE)
        positive_levels = {ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE}

        fever_documented = symptoms.fever_documented in positive_levels
        suprapubic_documented = symptoms.suprapubic_tenderness in positive_levels
        cva_documented = symptoms.cva_tenderness in positive_levels
        urgency_documented = symptoms.urgency in positive_levels
        frequency_documented = symptoms.frequency in positive_levels
        dysuria_documented = symptoms.dysuria in positive_levels

        # Check if any non-fever symptom is documented
        has_non_fever_symptom = any([
            suprapubic_documented,
            cva_documented,
            urgency_documented,
            frequency_documented,
            dysuria_documented,
        ])

        # Apply age-based fever rule
        patient_age = structured_data.patient_age
        catheter_days = structured_data.catheter_days or 0

        fever_eligible_per_age_rule = is_cauti_fever_eligible(patient_age, catheter_days)

        # Determine if symptom criterion is met
        if has_non_fever_symptom:
            symptom_criterion_met = True
            documented_symptoms = []
            if suprapubic_documented:
                documented_symptoms.append("suprapubic tenderness")
            if cva_documented:
                documented_symptoms.append("CVA tenderness")
            if urgency_documented:
                documented_symptoms.append("urinary urgency")
            if frequency_documented:
                documented_symptoms.append("urinary frequency")
            if dysuria_documented:
                documented_symptoms.append("dysuria")
            if fever_documented:
                documented_symptoms.append("fever")
            reasoning.append(f"Symptom criterion met: {', '.join(documented_symptoms)}")

        elif fever_documented:
            if fever_eligible_per_age_rule:
                symptom_criterion_met = True
                if patient_age and patient_age > self.fever_age_threshold:
                    reasoning.append(
                        f"Symptom criterion met: fever alone (patient age {patient_age}, "
                        f"catheter {catheter_days} days > {self.min_catheter_days})"
                    )
                else:
                    reasoning.append(
                        f"Symptom criterion met: fever alone "
                        f"(patient age {patient_age or 'unknown'} <= {self.fever_age_threshold})"
                    )
            else:
                symptom_criterion_met = False
                reasoning.append(
                    f"Fever documented but not eligible as sole symptom "
                    f"(patient age {patient_age} > {self.fever_age_threshold}, "
                    f"catheter {catheter_days} days <= {self.min_catheter_days})"
                )
        else:
            symptom_criterion_met = False
            reasoning.append("No qualifying symptoms documented")

        return (
            symptom_criterion_met,
            fever_documented,
            suprapubic_documented,
            cva_documented,
            urgency_documented,
            frequency_documented,
            dysuria_documented,
            fever_eligible_per_age_rule,
        )

    def _calculate_confidence(
        self,
        extraction: CAUTIExtraction,
        structured_data: CAUTIStructuredData,
    ) -> float:
        """Calculate confidence in the CAUTI classification.

        Factors affecting confidence:
        - Documentation quality
        - CFU/mL value (higher = more confident)
        - Multiple symptoms vs single symptom
        - Clinical team's impression
        """
        confidence = 0.7  # Base confidence

        # Documentation quality
        if extraction.documentation_quality == "detailed":
            confidence += 0.1
        elif extraction.documentation_quality == "adequate":
            confidence += 0.05
        elif extraction.documentation_quality == "poor":
            confidence -= 0.1

        # CFU level (higher is more definitive)
        cfu = structured_data.culture_cfu_ml
        if cfu and cfu >= 1000000:  # >= 10^6
            confidence += 0.05
        elif cfu and cfu >= self.min_cfu_ml:
            confidence += 0.02

        # Multiple symptoms increase confidence
        symptoms = extraction.symptoms
        positive_levels = {ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE}
        symptom_count = sum([
            symptoms.fever_documented in positive_levels,
            symptoms.suprapubic_tenderness in positive_levels,
            symptoms.cva_tenderness in positive_levels,
            symptoms.urgency in positive_levels,
            symptoms.frequency in positive_levels,
            symptoms.dysuria in positive_levels,
        ])
        if symptom_count >= 3:
            confidence += 0.1
        elif symptom_count >= 2:
            confidence += 0.05

        # Clinical team impression
        if extraction.uti_diagnosed in positive_levels:
            confidence += 0.1
        elif extraction.uti_suspected_by_team in positive_levels:
            confidence += 0.05

        # Alternative diagnoses reduce confidence
        if extraction.alternative_diagnoses:
            confidence -= 0.05 * min(len(extraction.alternative_diagnoses), 3)

        return min(max(confidence, 0.3), 0.95)

    def _determine_review_need(
        self,
        classification: CAUTIClassification,
        extraction: CAUTIExtraction,
        structured_data: CAUTIStructuredData,
        confidence: float,
    ) -> tuple[bool, list[str]]:
        """Determine if IP review is needed.

        Review triggers:
        - Low confidence
        - Borderline catheter days
        - Alternative diagnoses mentioned
        - Clinical team disagreement
        - Poor documentation quality
        """
        review_reasons = []

        # Low confidence always triggers review
        if confidence < 0.6:
            review_reasons.append(f"Low confidence ({confidence:.2f})")

        # Borderline catheter days
        if structured_data.catheter_days == self.min_catheter_days + 1:
            review_reasons.append(f"Borderline catheter days ({structured_data.catheter_days})")

        # Alternative diagnoses
        if extraction.alternative_diagnoses:
            review_reasons.append(
                f"Alternative diagnoses mentioned: {', '.join(extraction.alternative_diagnoses[:3])}"
            )

        # Clinical team suspects different diagnosis
        if extraction.uti_suspected_by_team == ConfidenceLevel.NOT_FOUND:
            review_reasons.append("UTI not suspected by clinical team")

        # Poor documentation
        if extraction.documentation_quality == "poor":
            review_reasons.append("Poor documentation quality")

        # Fever-only in older patient (borderline case)
        positive_levels = {ConfidenceLevel.DEFINITE, ConfidenceLevel.PROBABLE}
        if (
            extraction.symptoms.fever_documented in positive_levels
            and not extraction.symptoms.has_non_fever_symptom()
            and structured_data.patient_age
            and structured_data.patient_age > self.fever_age_threshold - 5  # Within 5 years of threshold
        ):
            review_reasons.append(
                f"Fever-only symptom in patient near age threshold ({structured_data.patient_age})"
            )

        requires_review = len(review_reasons) > 0 or classification == CAUTIClassification.ASYMPTOMATIC_BACTERIURIA
        if classification == CAUTIClassification.ASYMPTOMATIC_BACTERIURIA:
            review_reasons.append("Asymptomatic bacteriuria requires clinical review")

        return requires_review, review_reasons
