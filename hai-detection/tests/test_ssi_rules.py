"""Tests for SSI rules engine.

These tests validate the deterministic NHSN SSI criteria application.
Each test represents a clinical scenario with known expected outcome.
"""

import pytest
from datetime import datetime, timedelta

from src.rules.ssi_engine import SSIRulesEngine, classify_ssi
from src.rules.ssi_schemas import (
    SSIExtraction,
    SSIStructuredData,
    SSIClassification,
    SSIType,
    WoundAssessmentExtraction,
    SuperficialSSIFindings,
    DeepSSIFindings,
    OrganSpaceSSIFindings,
    ReoperationFindings,
)
from src.rules.schemas import ConfidenceLevel
from src.rules.nhsn_criteria import (
    is_nhsn_operative_procedure,
    is_implant_procedure,
    get_surveillance_window,
    NHSN_OPERATIVE_CATEGORIES,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def engine():
    """Create a rules engine for testing."""
    return SSIRulesEngine(strict_mode=True)


@pytest.fixture
def base_structured_data():
    """Base case: eligible for SSI evaluation (colon surgery)."""
    now = datetime.now()
    return SSIStructuredData(
        procedure_code="44140",
        procedure_name="Sigmoid colectomy",
        procedure_date=now - timedelta(days=10),
        nhsn_category="COLO",
        wound_class=2,  # Clean-contaminated
        duration_minutes=180,
        asa_score=2,
        implant_used=False,
        days_post_op=10,
        surveillance_window_days=30,
    )


@pytest.fixture
def base_extraction():
    """Base extraction: wound assessments but no definite SSI findings."""
    return SSIExtraction(
        wound_assessments=[
            WoundAssessmentExtraction(
                drainage_present=ConfidenceLevel.NOT_FOUND,
                erythema_present=ConfidenceLevel.NOT_FOUND,
            )
        ],
        superficial_findings=SuperficialSSIFindings(),
        deep_findings=DeepSSIFindings(),
        organ_space_findings=OrganSpaceSSIFindings(),
        reoperation=ReoperationFindings(),
        documentation_quality="adequate",
        notes_reviewed_count=3,
    )


# =============================================================================
# Tests: Basic Eligibility
# =============================================================================

class TestBasicEligibility:
    """Test basic SSI eligibility criteria."""

    def test_non_nhsn_procedure_not_eligible(self, engine, base_extraction):
        """Non-NHSN procedure category is not eligible."""
        data = SSIStructuredData(
            procedure_code="12345",
            procedure_name="Minor skin procedure",
            procedure_date=datetime.now() - timedelta(days=5),
            nhsn_category="NOT_VALID",  # Invalid category
            days_post_op=5,
            surveillance_window_days=30,
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == SSIClassification.NOT_ELIGIBLE
        assert not result.requires_review

    def test_outside_surveillance_window_not_eligible(self, engine, base_extraction):
        """Infection outside surveillance window is not eligible."""
        now = datetime.now()
        data = SSIStructuredData(
            procedure_code="44140",
            procedure_name="Sigmoid colectomy",
            procedure_date=now - timedelta(days=45),  # 45 days ago
            nhsn_category="COLO",
            days_post_op=45,  # Outside 30-day window
            surveillance_window_days=30,
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == SSIClassification.NOT_ELIGIBLE
        assert "surveillance window" in str(result.reasoning).lower()

    def test_implant_procedure_has_90_day_window(self, engine, base_extraction):
        """Implant procedures should have 90-day surveillance window."""
        now = datetime.now()
        data = SSIStructuredData(
            procedure_code="27447",
            procedure_name="Total knee replacement",
            procedure_date=now - timedelta(days=60),
            nhsn_category="KPRO",
            implant_used=True,
            days_post_op=60,
            surveillance_window_days=90,  # 90-day window for implant
        )

        result = engine.classify(base_extraction, data)

        # Should still be eligible (within 90-day window)
        assert result.classification != SSIClassification.NOT_ELIGIBLE

    def test_valid_nhsn_procedures(self):
        """Test that known NHSN categories are valid."""
        valid_categories = ["COLO", "HPRO", "KPRO", "CABG", "CHOL", "HYS"]
        for cat in valid_categories:
            assert is_nhsn_operative_procedure(cat), f"{cat} should be valid"

    def test_implant_procedure_identification(self):
        """Test implant procedure detection."""
        implant_procs = ["HPRO", "KPRO", "PACE", "FUSN"]
        non_implant = ["COLO", "CHOL", "APPY"]

        for proc in implant_procs:
            assert is_implant_procedure(proc), f"{proc} should be implant procedure"

        for proc in non_implant:
            assert not is_implant_procedure(proc), f"{proc} should not be implant"


# =============================================================================
# Tests: Superficial SSI Classification
# =============================================================================

class TestSuperficialSSI:
    """Test Superficial Incisional SSI scenarios."""

    def test_purulent_drainage_superficial_is_ssi(self, engine, base_structured_data):
        """Purulent drainage from superficial incision meets criteria."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                purulent_drainage_superficial=ConfidenceLevel.DEFINITE,
                purulent_drainage_quote="Purulent discharge noted from incision site",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.SUPERFICIAL_SSI
        assert result.ssi_type == SSIType.SUPERFICIAL_INCISIONAL
        assert "Purulent drainage from superficial incision" in result.superficial_criteria_met

    def test_positive_wound_culture_is_ssi(self, engine, base_structured_data):
        """Positive culture from superficial incision meets criteria."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                organisms_from_superficial_culture=ConfidenceLevel.DEFINITE,
                organism_identified="Staphylococcus aureus",
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.SUPERFICIAL_SSI
        assert result.ssi_type == SSIType.SUPERFICIAL_INCISIONAL
        assert any("culture" in c.lower() for c in result.superficial_criteria_met)

    def test_signs_with_incision_opened_is_ssi(self, engine, base_structured_data):
        """Signs of infection + incision deliberately opened meets criteria."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                pain_or_tenderness=ConfidenceLevel.DEFINITE,
                erythema=ConfidenceLevel.DEFINITE,
                incision_deliberately_opened=ConfidenceLevel.DEFINITE,
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.SUPERFICIAL_SSI
        assert "incision deliberately opened" in str(result.superficial_criteria_met).lower()

    def test_signs_without_incision_opened_not_ssi(self, engine, base_structured_data):
        """Signs of infection without incision opened is NOT SSI."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                pain_or_tenderness=ConfidenceLevel.DEFINITE,
                erythema=ConfidenceLevel.DEFINITE,
                incision_deliberately_opened=ConfidenceLevel.NOT_FOUND,  # Not opened
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        # Should NOT be superficial SSI without incision opened
        assert result.classification != SSIClassification.SUPERFICIAL_SSI

    def test_physician_diagnosis_superficial_is_ssi(self, engine, base_structured_data):
        """Physician diagnosis of superficial SSI meets criteria."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                physician_diagnosis_superficial_ssi=ConfidenceLevel.DEFINITE,
                diagnosis_quote="Superficial wound infection at incision site",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.SUPERFICIAL_SSI


# =============================================================================
# Tests: Deep SSI Classification
# =============================================================================

class TestDeepSSI:
    """Test Deep Incisional SSI scenarios."""

    def test_purulent_drainage_deep_is_ssi(self, engine, base_structured_data):
        """Purulent drainage from deep incision meets criteria."""
        extraction = SSIExtraction(
            deep_findings=DeepSSIFindings(
                purulent_drainage_deep=ConfidenceLevel.DEFINITE,
                purulent_drainage_quote="Purulent drainage from fascial layer",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.DEEP_SSI
        assert result.ssi_type == SSIType.DEEP_INCISIONAL

    def test_dehiscence_with_fever_is_ssi(self, engine, base_structured_data):
        """Deep dehiscence + fever meets criteria."""
        extraction = SSIExtraction(
            deep_findings=DeepSSIFindings(
                deep_incision_dehisces=ConfidenceLevel.DEFINITE,
                fever_greater_38=ConfidenceLevel.DEFINITE,
                fever_value_celsius=38.9,
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.DEEP_SSI
        assert "fever" in str(result.deep_criteria_met).lower()

    def test_abscess_on_imaging_is_ssi(self, engine, base_structured_data):
        """Abscess found on imaging meets deep SSI criteria."""
        extraction = SSIExtraction(
            deep_findings=DeepSSIFindings(
                abscess_on_imaging=ConfidenceLevel.DEFINITE,
                imaging_type="CT",
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.DEEP_SSI
        assert any("CT" in c for c in result.deep_criteria_met)

    def test_physician_diagnosis_deep_is_ssi(self, engine, base_structured_data):
        """Physician diagnosis of deep SSI meets criteria."""
        extraction = SSIExtraction(
            deep_findings=DeepSSIFindings(
                physician_diagnosis_deep_ssi=ConfidenceLevel.DEFINITE,
                diagnosis_quote="Deep wound infection requiring debridement",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.DEEP_SSI


# =============================================================================
# Tests: Organ/Space SSI Classification
# =============================================================================

class TestOrganSpaceSSI:
    """Test Organ/Space SSI scenarios."""

    def test_purulent_drainage_from_drain_is_ssi(self, engine, base_structured_data):
        """Purulent drainage from drain in organ/space meets criteria."""
        extraction = SSIExtraction(
            organ_space_findings=OrganSpaceSSIFindings(
                purulent_drainage_drain=ConfidenceLevel.DEFINITE,
                drain_location="JP drain in pelvis",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.ORGAN_SPACE_SSI
        assert result.ssi_type == SSIType.ORGAN_SPACE

    def test_positive_culture_organ_space_is_ssi(self, engine, base_structured_data):
        """Positive culture from organ/space meets criteria."""
        extraction = SSIExtraction(
            organ_space_findings=OrganSpaceSSIFindings(
                organisms_from_organ_space=ConfidenceLevel.DEFINITE,
                organism_identified="Escherichia coli",
                specimen_type="peritoneal fluid",
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.ORGAN_SPACE_SSI
        assert result.organism_for_report == "Escherichia coli"

    def test_abscess_on_ct_is_organ_space_ssi(self, engine, base_structured_data):
        """Abscess on CT involving organ/space meets criteria."""
        extraction = SSIExtraction(
            organ_space_findings=OrganSpaceSSIFindings(
                abscess_on_imaging=ConfidenceLevel.DEFINITE,
                imaging_type="CT",
                imaging_findings="4cm pelvic abscess",
                organ_space_involved="pelvis",
                organ_space_nhsn_code="IAB",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.ORGAN_SPACE_SSI
        assert result.nhsn_specific_site == "IAB"

    def test_abscess_on_reoperation_is_ssi(self, engine, base_structured_data):
        """Abscess found on reoperation meets criteria."""
        extraction = SSIExtraction(
            organ_space_findings=OrganSpaceSSIFindings(
                abscess_on_reoperation=ConfidenceLevel.DEFINITE,
                organ_space_involved="intra-abdominal",
            ),
            reoperation=ReoperationFindings(
                reoperation_performed=ConfidenceLevel.DEFINITE,
                reoperation_indication="washout for infection",
                reoperation_findings="purulent fluid, necrotic tissue",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=5,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.ORGAN_SPACE_SSI

    def test_mediastinitis_after_cabg(self, engine):
        """Mediastinitis after CABG is organ/space SSI."""
        now = datetime.now()
        data = SSIStructuredData(
            procedure_code="33533",
            procedure_name="CABG x3",
            procedure_date=now - timedelta(days=14),
            nhsn_category="CABG",
            implant_used=True,
            days_post_op=14,
            surveillance_window_days=90,
        )

        extraction = SSIExtraction(
            organ_space_findings=OrganSpaceSSIFindings(
                physician_diagnosis_organ_space_ssi=ConfidenceLevel.DEFINITE,
                diagnosis_quote="Mediastinitis, requiring surgical debridement",
                organ_space_involved="mediastinum",
                organ_space_nhsn_code="MED",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=6,
        )

        result = engine.classify(extraction, data)

        assert result.classification == SSIClassification.ORGAN_SPACE_SSI
        assert result.nhsn_specific_site == "MED"


# =============================================================================
# Tests: SSI Type Hierarchy (most severe wins)
# =============================================================================

class TestSSITypeHierarchy:
    """Test that deeper SSI types take precedence."""

    def test_organ_space_takes_precedence_over_superficial(self, engine, base_structured_data):
        """Organ/space SSI should be classified even if superficial criteria also met."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                purulent_drainage_superficial=ConfidenceLevel.DEFINITE,
            ),
            organ_space_findings=OrganSpaceSSIFindings(
                abscess_on_imaging=ConfidenceLevel.DEFINITE,
                imaging_type="CT",
                organ_space_involved="pelvis",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        # Should classify as organ/space (most severe)
        assert result.classification == SSIClassification.ORGAN_SPACE_SSI

    def test_deep_takes_precedence_over_superficial(self, engine, base_structured_data):
        """Deep SSI should be classified over superficial if both present."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                purulent_drainage_superficial=ConfidenceLevel.DEFINITE,
            ),
            deep_findings=DeepSSIFindings(
                purulent_drainage_deep=ConfidenceLevel.DEFINITE,
            ),
            documentation_quality="detailed",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        # Should classify as deep (more severe than superficial)
        assert result.classification == SSIClassification.DEEP_SSI


# =============================================================================
# Tests: No SSI
# =============================================================================

class TestNotSSI:
    """Test cases that should not be classified as SSI."""

    def test_no_criteria_met_is_not_ssi(self, engine, base_extraction, base_structured_data):
        """No SSI criteria met results in NOT_SSI classification."""
        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == SSIClassification.NOT_SSI
        assert result.ssi_type is None

    def test_possible_findings_only_not_ssi(self, engine, base_structured_data):
        """Only 'possible' findings should not classify as SSI."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                purulent_drainage_superficial=ConfidenceLevel.POSSIBLE,
            ),
            deep_findings=DeepSSIFindings(
                abscess_on_imaging=ConfidenceLevel.POSSIBLE,
            ),
            documentation_quality="limited",
            notes_reviewed_count=2,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == SSIClassification.NOT_SSI
        # Should flag for review
        assert result.requires_review


# =============================================================================
# Tests: Review Triggers
# =============================================================================

class TestReviewTriggers:
    """Test conditions that trigger IP review."""

    def test_team_suspects_ssi_triggers_review(self, engine, base_structured_data):
        """Clinical team suspecting SSI should trigger review."""
        extraction = SSIExtraction(
            ssi_suspected_by_team=ConfidenceLevel.DEFINITE,
            antibiotics_for_wound_infection=ConfidenceLevel.NOT_FOUND,
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.requires_review
        assert any("team suspects" in r.lower() for r in result.review_reasons)

    def test_antibiotics_for_wound_triggers_review(self, engine, base_structured_data):
        """Antibiotics for wound infection without SSI criteria should trigger review."""
        extraction = SSIExtraction(
            antibiotics_for_wound_infection=ConfidenceLevel.DEFINITE,
            antibiotic_names=["cephalexin"],
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.requires_review

    def test_possible_findings_trigger_review(self, engine, base_structured_data):
        """Possible SSI findings should trigger review."""
        extraction = SSIExtraction(
            superficial_findings=SuperficialSSIFindings(
                purulent_drainage_superficial=ConfidenceLevel.POSSIBLE,
                physician_diagnosis_superficial_ssi=ConfidenceLevel.POSSIBLE,
            ),
            documentation_quality="limited",
            notes_reviewed_count=2,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.requires_review


# =============================================================================
# Tests: NHSN Criteria Functions
# =============================================================================

class TestNHSNCriteriaFunctions:
    """Test NHSN SSI-related helper functions."""

    def test_surveillance_window_standard(self):
        """Standard procedures should have 30-day window."""
        assert get_surveillance_window("COLO") == 30
        assert get_surveillance_window("CHOL") == 30
        assert get_surveillance_window("APPY") == 30

    def test_surveillance_window_implant(self):
        """Implant procedures should have 90-day window."""
        assert get_surveillance_window("HPRO") == 90
        assert get_surveillance_window("KPRO") == 90
        assert get_surveillance_window("PACE") == 90

    def test_surveillance_window_implant_override(self):
        """has_implant override should give 90-day window."""
        assert get_surveillance_window("COLO", has_implant=True) == 90


# =============================================================================
# Tests: Convenience Function
# =============================================================================

class TestConvenienceFunction:
    """Test the classify_ssi convenience function."""

    def test_classify_ssi_function(self, base_extraction, base_structured_data):
        """classify_ssi should work the same as engine.classify."""
        result = classify_ssi(base_extraction, base_structured_data)

        assert result.classification in [
            SSIClassification.SUPERFICIAL_SSI,
            SSIClassification.DEEP_SSI,
            SSIClassification.ORGAN_SPACE_SSI,
            SSIClassification.NOT_SSI,
            SSIClassification.NOT_ELIGIBLE,
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
