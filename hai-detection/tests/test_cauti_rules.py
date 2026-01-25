"""Unit tests for CAUTI rules engine.

Tests NHSN CAUTI criteria application including:
- Clear CAUTI cases (catheter >2d, positive culture, symptoms)
- Asymptomatic bacteriuria (positive culture, no symptoms)
- Age-based fever rule (>65 years vs <=65 years)
- Culture exclusions (mixed flora, Candida-only)
- Catheter eligibility
"""

import pytest
from datetime import datetime, date, timedelta

from hai_src.rules.cauti_schemas import (
    CAUTIClassification,
    CAUTIExtraction,
    CAUTIStructuredData,
    CAUTIClassificationResult,
    UrinarySymptomExtraction,
)
from hai_src.rules.cauti_engine import CAUTIRulesEngine
from hai_src.rules.schemas import ConfidenceLevel
from hai_src.rules.nhsn_criteria import (
    CAUTI_MIN_CATHETER_DAYS,
    CAUTI_MIN_CFU_ML,
    CAUTI_MAX_ORGANISMS,
    CAUTI_FEVER_AGE_THRESHOLD,
    is_cauti_excluded_organism,
    is_valid_cauti_culture,
    is_cauti_fever_eligible,
)


class TestCAUTINHSNCriteria:
    """Test NHSN criteria helper functions."""

    def test_excluded_organism_candida(self):
        """Candida species should be excluded."""
        assert is_cauti_excluded_organism("Candida albicans") is True
        assert is_cauti_excluded_organism("Candida glabrata") is True
        assert is_cauti_excluded_organism("candida") is True

    def test_excluded_organism_yeast(self):
        """Yeast should be excluded."""
        assert is_cauti_excluded_organism("yeast") is True
        assert is_cauti_excluded_organism("Yeast") is True

    def test_not_excluded_common_uropathogens(self):
        """Common uropathogens should not be excluded."""
        assert is_cauti_excluded_organism("Escherichia coli") is False
        assert is_cauti_excluded_organism("Klebsiella pneumoniae") is False
        assert is_cauti_excluded_organism("Enterococcus faecalis") is False
        assert is_cauti_excluded_organism("Pseudomonas aeruginosa") is False

    def test_valid_culture_meets_threshold(self):
        """Culture meeting threshold should be valid."""
        assert is_valid_cauti_culture(organism_count=1, cfu_ml=100000) is True
        assert is_valid_cauti_culture(organism_count=2, cfu_ml=100000) is True
        assert is_valid_cauti_culture(organism_count=1, cfu_ml=1000000) is True

    def test_invalid_culture_below_threshold(self):
        """Culture below CFU threshold should be invalid."""
        assert is_valid_cauti_culture(organism_count=1, cfu_ml=10000) is False
        assert is_valid_cauti_culture(organism_count=1, cfu_ml=99999) is False

    def test_invalid_culture_mixed_flora(self):
        """Culture with >2 organisms (mixed flora) should be invalid."""
        assert is_valid_cauti_culture(organism_count=3, cfu_ml=100000) is False
        assert is_valid_cauti_culture(organism_count=5, cfu_ml=100000) is False

    def test_fever_eligible_young_patient(self):
        """Patients <=65 years can always use fever alone."""
        assert is_cauti_fever_eligible(patient_age=50, catheter_days=1) is True
        assert is_cauti_fever_eligible(patient_age=65, catheter_days=1) is True
        assert is_cauti_fever_eligible(patient_age=30, catheter_days=2) is True

    def test_fever_eligible_older_patient_with_catheter(self):
        """Patients >65 years need catheter >2 days for fever alone."""
        assert is_cauti_fever_eligible(patient_age=70, catheter_days=3) is True
        assert is_cauti_fever_eligible(patient_age=80, catheter_days=5) is True

    def test_fever_not_eligible_older_patient_short_catheter(self):
        """Patients >65 with catheter <=2 days cannot use fever alone."""
        assert is_cauti_fever_eligible(patient_age=70, catheter_days=2) is False
        assert is_cauti_fever_eligible(patient_age=66, catheter_days=1) is False


class TestCAUTIRulesEngine:
    """Test CAUTIRulesEngine classification logic."""

    @pytest.fixture
    def engine(self):
        return CAUTIRulesEngine()

    @pytest.fixture
    def base_extraction(self):
        """Base extraction with no symptoms."""
        return CAUTIExtraction(
            symptoms=UrinarySymptomExtraction(),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

    @pytest.fixture
    def base_structured_data(self):
        """Base structured data meeting catheter and culture criteria."""
        return CAUTIStructuredData(
            patient_id="patient-123",
            patient_age=50,
            catheter_days=5,
            catheter_type="foley_catheter",
            culture_cfu_ml=100000,
            culture_organism="Escherichia coli",
            culture_organism_count=1,
            culture_date=datetime.now(),
        )

    def test_clear_cauti_dysuria(self, engine, base_extraction, base_structured_data):
        """Clear CAUTI: catheter >2d + culture + dysuria."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.DEFINITE

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.CAUTI
        assert result.catheter_eligible is True
        assert result.culture_eligible is True
        assert result.symptom_criterion_met is True
        assert result.dysuria_documented is True

    def test_clear_cauti_fever_young_patient(self, engine, base_extraction, base_structured_data):
        """Clear CAUTI: catheter >2d + culture + fever (patient <=65)."""
        base_extraction.symptoms.fever_documented = ConfidenceLevel.DEFINITE
        base_extraction.symptoms.fever_temp_celsius = 38.5
        base_structured_data.patient_age = 50

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.CAUTI
        assert result.fever_documented is True
        assert result.fever_eligible_per_age_rule is True
        assert result.symptom_criterion_met is True

    def test_clear_cauti_multiple_symptoms(self, engine, base_extraction, base_structured_data):
        """Clear CAUTI with multiple symptoms has higher confidence."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.DEFINITE
        base_extraction.symptoms.frequency = ConfidenceLevel.DEFINITE
        base_extraction.symptoms.urgency = ConfidenceLevel.PROBABLE

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.CAUTI
        assert result.confidence > 0.7  # Higher confidence with multiple symptoms
        assert result.dysuria_documented is True
        assert result.frequency_documented is True
        assert result.urgency_documented is True

    def test_asymptomatic_bacteriuria(self, engine, base_extraction, base_structured_data):
        """Asymptomatic bacteriuria: positive culture but no symptoms."""
        # No symptoms documented (base_extraction has no symptoms)

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.ASYMPTOMATIC_BACTERIURIA
        assert result.catheter_eligible is True
        assert result.culture_eligible is True
        assert result.symptom_criterion_met is False
        assert result.requires_review is True

    def test_fever_only_older_patient_short_catheter(self, engine, base_extraction, base_structured_data):
        """Fever-only in patient >65 with catheter <=2 days is NOT CAUTI."""
        base_extraction.symptoms.fever_documented = ConfidenceLevel.DEFINITE
        base_structured_data.patient_age = 70
        base_structured_data.catheter_days = 2  # Not > 2 days

        result = engine.classify(base_extraction, base_structured_data)

        # Should not meet criteria because fever alone not eligible for >65 with catheter <=2d
        assert result.classification == CAUTIClassification.ASYMPTOMATIC_BACTERIURIA
        assert result.fever_documented is True
        assert result.fever_eligible_per_age_rule is False
        assert result.symptom_criterion_met is False

    def test_fever_only_older_patient_long_catheter(self, engine, base_extraction, base_structured_data):
        """Fever-only in patient >65 with catheter >2 days IS eligible."""
        base_extraction.symptoms.fever_documented = ConfidenceLevel.DEFINITE
        base_structured_data.patient_age = 70
        base_structured_data.catheter_days = 5  # > 2 days

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.CAUTI
        assert result.fever_documented is True
        assert result.fever_eligible_per_age_rule is True
        assert result.symptom_criterion_met is True

    def test_not_eligible_insufficient_catheter_days(self, engine, base_extraction, base_structured_data):
        """Not eligible: catheter <=2 days."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.DEFINITE
        base_structured_data.catheter_days = 2  # Not > 2 days

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.NOT_ELIGIBLE
        assert result.catheter_eligible is False

    def test_not_eligible_mixed_flora(self, engine, base_extraction, base_structured_data):
        """Not eligible: mixed flora (>2 organisms)."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.DEFINITE
        base_structured_data.culture_organism_count = 3

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.NOT_ELIGIBLE
        assert result.culture_eligible is False

    def test_not_eligible_candida(self, engine, base_extraction, base_structured_data):
        """Not eligible: Candida-only culture."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.DEFINITE
        base_structured_data.culture_organism = "Candida albicans"

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.NOT_ELIGIBLE
        assert result.culture_eligible is False

    def test_not_eligible_low_cfu(self, engine, base_extraction, base_structured_data):
        """Not eligible: CFU/mL below threshold."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.DEFINITE
        base_structured_data.culture_cfu_ml = 10000  # Below 10^5

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.NOT_ELIGIBLE
        assert result.culture_eligible is False

    def test_probable_symptoms_count(self, engine, base_extraction, base_structured_data):
        """Probable symptoms should count as documented."""
        base_extraction.symptoms.suprapubic_tenderness = ConfidenceLevel.PROBABLE

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.CAUTI
        assert result.suprapubic_tenderness_documented is True
        assert result.symptom_criterion_met is True

    def test_possible_symptoms_do_not_count(self, engine, base_extraction, base_structured_data):
        """Possible symptoms should NOT count as documented."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.POSSIBLE

        result = engine.classify(base_extraction, base_structured_data)

        # Possible doesn't meet threshold
        assert result.classification == CAUTIClassification.ASYMPTOMATIC_BACTERIURIA
        assert result.dysuria_documented is False

    def test_cva_tenderness_counts(self, engine, base_extraction, base_structured_data):
        """CVA tenderness is a valid CAUTI symptom."""
        base_extraction.symptoms.cva_tenderness = ConfidenceLevel.DEFINITE

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.CAUTI
        assert result.cva_tenderness_documented is True
        assert result.symptom_criterion_met is True

    def test_review_triggered_for_asb(self, engine, base_extraction, base_structured_data):
        """Asymptomatic bacteriuria should trigger review."""
        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.ASYMPTOMATIC_BACTERIURIA
        assert result.requires_review is True
        assert "Asymptomatic bacteriuria requires clinical review" in result.review_reasons

    def test_review_triggered_for_alternative_diagnoses(self, engine, base_extraction, base_structured_data):
        """Alternative diagnoses should trigger review."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.DEFINITE
        base_extraction.alternative_diagnoses = ["renal colic", "urethritis"]

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.CAUTI
        assert result.requires_review is True
        assert any("Alternative diagnoses" in r for r in result.review_reasons)

    def test_confidence_increases_with_team_diagnosis(self, engine, base_extraction, base_structured_data):
        """Confidence should increase if clinical team diagnosed UTI."""
        base_extraction.symptoms.dysuria = ConfidenceLevel.DEFINITE
        base_extraction.uti_diagnosed = ConfidenceLevel.DEFINITE

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CAUTIClassification.CAUTI
        assert result.confidence > 0.8


class TestCAUTIClassificationResult:
    """Test CAUTIClassificationResult dataclass."""

    def test_to_dict(self):
        """Result should serialize to dict."""
        result = CAUTIClassificationResult(
            classification=CAUTIClassification.CAUTI,
            confidence=0.85,
            reasoning=["Catheter >2 days", "Positive culture", "Dysuria documented"],
            requires_review=False,
            review_reasons=[],
            catheter_eligible=True,
            catheter_days=5,
            culture_eligible=True,
            culture_cfu_ml=100000,
            symptom_criterion_met=True,
            dysuria_documented=True,
        )

        d = result.to_dict()

        assert d["classification"] == "cauti"
        assert d["confidence"] == 0.85
        assert len(d["reasoning"]) == 3
        assert d["catheter_eligible"] is True
        assert d["dysuria_documented"] is True
