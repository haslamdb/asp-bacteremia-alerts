"""Tests for CLABSI rules engine.

These tests validate the deterministic NHSN criteria application.
Each test represents a clinical scenario with known expected outcome.
"""

import pytest
from datetime import datetime, timedelta

from hai_src.rules import (
    CLABSIRulesEngine,
    ClinicalExtraction,
    StructuredCaseData,
    CLABSIClassification,
    ConfidenceLevel,
    DocumentedInfectionSite,
    SymptomExtraction,
    MBIFactors,
    LineAssessment,
    ContaminationAssessment,
)
from hai_src.rules.nhsn_criteria import (
    is_commensal_organism,
    is_mbi_eligible_organism,
    is_recognized_pathogen,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def engine():
    """Create a rules engine for testing."""
    return CLABSIRulesEngine(strict_mode=True)


@pytest.fixture
def base_structured_data():
    """Base case: eligible for CLABSI evaluation."""
    now = datetime.now()
    return StructuredCaseData(
        organism="Staphylococcus aureus",
        culture_date=now,
        line_present=True,
        line_type="PICC",
        line_insertion_date=now - timedelta(days=5),
        line_days_at_culture=5,
        admission_date=now - timedelta(days=7),
        patient_days_at_culture=7,
        location_at_culture="T5A",
        location_type="ICU",
    )


@pytest.fixture
def base_extraction():
    """Base extraction: no alternate sources, standard documentation."""
    return ClinicalExtraction(
        alternate_infection_sites=[],
        symptoms=SymptomExtraction(
            fever=ConfidenceLevel.DEFINITE,
            fever_value_celsius=38.9,
        ),
        mbi_factors=MBIFactors(),
        line_assessment=LineAssessment(),
        contamination=ContaminationAssessment(),
        clinical_context_summary="Patient with fever and positive blood culture",
        documentation_quality="adequate",
        notes_reviewed_count=3,
    )


# =============================================================================
# Tests: Basic Eligibility
# =============================================================================

class TestBasicEligibility:
    """Test basic CLABSI eligibility criteria."""

    def test_no_central_line_not_eligible(self, engine, base_extraction):
        """BSI without central line is not a CLABSI candidate."""
        data = StructuredCaseData(
            organism="Staphylococcus aureus",
            culture_date=datetime.now(),
            line_present=False,  # No line
            patient_days_at_culture=5,
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == CLABSIClassification.NOT_ELIGIBLE
        assert not result.requires_review
        assert "No central line" in result.reasoning[0]

    def test_line_less_than_2_days_not_eligible(self, engine, base_extraction):
        """Line must be in place >2 days."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Staphylococcus aureus",
            culture_date=now,
            line_present=True,
            line_insertion_date=now - timedelta(days=1),
            line_days_at_culture=1,  # Only 1 day
            patient_days_at_culture=5,
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == CLABSIClassification.NOT_ELIGIBLE
        assert "1 days" in result.reasoning[0]

    def test_line_removed_more_than_1_day_ago_not_eligible(self, engine, base_extraction):
        """Culture must be within 1 day of line removal."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Staphylococcus aureus",
            culture_date=now,
            line_present=True,
            line_insertion_date=now - timedelta(days=10),
            line_removal_date=now - timedelta(days=3),  # Removed 3 days before culture
            line_days_at_culture=7,
            patient_days_at_culture=12,
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == CLABSIClassification.NOT_ELIGIBLE
        assert "after line removal" in result.reasoning[0]

    def test_line_removed_same_day_eligible(self, engine, base_extraction, base_structured_data):
        """Culture on day of line removal is eligible."""
        now = datetime.now()
        data = base_structured_data
        data.line_removal_date = now  # Removed same day as culture

        result = engine.classify(base_extraction, data)

        # Should not be excluded for timing
        assert result.classification != CLABSIClassification.NOT_ELIGIBLE

    def test_present_on_admission_not_eligible(self, engine, base_extraction):
        """Infection on day 1-2 is considered present on admission."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Staphylococcus aureus",
            culture_date=now,
            line_present=True,
            line_days_at_culture=5,
            admission_date=now - timedelta(days=2),
            patient_days_at_culture=2,  # Day 2 = POA
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == CLABSIClassification.NOT_ELIGIBLE
        assert "present on admission" in result.reasoning[0].lower()


# =============================================================================
# Tests: CLABSI Classification
# =============================================================================

class TestCLABSIClassification:
    """Test cases that should classify as CLABSI."""

    def test_clear_clabsi(self, engine, base_extraction, base_structured_data):
        """Pathogenic organism, no alternate source = CLABSI."""
        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == CLABSIClassification.CLABSI
        assert result.confidence >= 0.80
        assert "CLABSI" in str(result.reasoning)

    def test_clabsi_with_line_infection_suspected(self, engine, base_structured_data):
        """CLABSI when clinical team suspects line infection."""
        extraction = ClinicalExtraction(
            alternate_infection_sites=[],
            line_assessment=LineAssessment(
                line_infection_suspected=ConfidenceLevel.DEFINITE,
                line_removed_for_infection=ConfidenceLevel.DEFINITE,
            ),
            documentation_quality="detailed",
            notes_reviewed_count=5,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == CLABSIClassification.CLABSI
        assert result.confidence >= 0.85  # Higher confidence when team suspects line

    def test_two_commensal_cultures_is_clabsi(self, engine, base_extraction):
        """Two matching cultures with commensal = CLABSI (not contamination)."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Staphylococcus epidermidis",  # Commensal
            culture_date=now,
            line_present=True,
            line_days_at_culture=5,
            patient_days_at_culture=7,
            has_second_culture_match=True,  # Has matching second culture
            second_culture_date=now - timedelta(days=1),
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == CLABSIClassification.CLABSI


# =============================================================================
# Tests: Contamination
# =============================================================================

class TestContamination:
    """Test contamination scenarios."""

    def test_single_commensal_is_contamination(self, engine, base_extraction):
        """Single positive culture with commensal = contamination."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Coagulase-negative staphylococci",
            culture_date=now,
            line_present=True,
            line_days_at_culture=5,
            patient_days_at_culture=7,
            has_second_culture_match=False,  # No second culture
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == CLABSIClassification.CONTAMINATION
        assert not result.requires_review

    def test_single_corynebacterium_is_contamination(self, engine, base_extraction):
        """Single Corynebacterium culture = contamination."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Corynebacterium species",
            culture_date=now,
            line_present=True,
            line_days_at_culture=5,
            patient_days_at_culture=7,
            has_second_culture_match=False,
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == CLABSIClassification.CONTAMINATION


# =============================================================================
# Tests: Secondary BSI
# =============================================================================

class TestSecondaryBSI:
    """Test secondary BSI scenarios."""

    def test_secondary_bsi_from_structured_data(self, engine, base_extraction):
        """BSI secondary to infection at another site (from EHR data)."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Escherichia coli",
            culture_date=now,
            line_present=True,
            line_days_at_culture=5,
            patient_days_at_culture=7,
            matching_organism_other_sites=["urine"],  # Same organism in urine
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == CLABSIClassification.SECONDARY_BSI
        assert "urine" in str(result.reasoning).lower()

    def test_secondary_bsi_from_extraction(self, engine, base_structured_data):
        """BSI secondary to infection documented in notes."""
        extraction = ClinicalExtraction(
            alternate_infection_sites=[
                DocumentedInfectionSite(
                    site="pneumonia",
                    confidence=ConfidenceLevel.DEFINITE,
                    same_organism_mentioned=True,
                    culture_from_site_positive=True,
                    supporting_quote="Respiratory culture growing Staph aureus, same as blood",
                    note_date="2025-01-18",
                )
            ],
            documentation_quality="detailed",
            notes_reviewed_count=5,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == CLABSIClassification.SECONDARY_BSI
        assert "pneumonia" in str(result.reasoning).lower()

    def test_possible_secondary_flagged_for_review(self, engine, base_structured_data):
        """Possible alternate source should flag for review."""
        extraction = ClinicalExtraction(
            alternate_infection_sites=[
                DocumentedInfectionSite(
                    site="uti",
                    confidence=ConfidenceLevel.POSSIBLE,
                    same_organism_mentioned=False,
                    culture_from_site_positive=None,
                    supporting_quote="UA shows pyuria, consider UTI",
                    note_date="2025-01-18",
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        # Should not be classified as secondary BSI without confirmation
        assert result.classification == CLABSIClassification.CLABSI
        # But should require review
        assert result.requires_review
        assert any("uti" in r.lower() for r in result.review_reasons)


# =============================================================================
# Tests: MBI-LCBI
# =============================================================================

class TestMBILCBI:
    """Test MBI-LCBI scenarios."""

    def test_mbi_lcbi_neutropenic_with_mucositis(self, engine):
        """MBI-LCBI: GI organism + neutropenia + mucositis."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Enterococcus faecalis",  # GI organism
            culture_date=now,
            line_present=True,
            line_days_at_culture=10,
            patient_days_at_culture=14,
            anc_values_7_days=[100, 50, 0],  # Neutropenic
        )

        extraction = ClinicalExtraction(
            alternate_infection_sites=[],
            mbi_factors=MBIFactors(
                neutropenia_documented=ConfidenceLevel.DEFINITE,
                anc_value=50,
                mucositis_documented=ConfidenceLevel.DEFINITE,
                mucositis_grade=3,
            ),
            documentation_quality="detailed",
            notes_reviewed_count=5,
        )

        result = engine.classify(extraction, data)

        assert result.classification == CLABSIClassification.MBI_LCBI
        assert result.requires_review  # MBI-LCBI always needs verification
        assert "mucositis" in str(result.reasoning).lower()

    def test_mbi_lcbi_allo_hsct_with_gvhd(self, engine):
        """MBI-LCBI: GI organism + allo-HSCT + GI GVHD."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Escherichia coli",  # GI organism
            culture_date=now,
            line_present=True,
            line_days_at_culture=15,
            patient_days_at_culture=20,
            is_transplant_patient=True,
            transplant_type="allogeneic",
            transplant_date=now - timedelta(days=30),  # Day +30 post-transplant
        )

        extraction = ClinicalExtraction(
            alternate_infection_sites=[],
            mbi_factors=MBIFactors(
                stem_cell_transplant=ConfidenceLevel.DEFINITE,
                transplant_type="allogeneic",
                days_post_transplant=30,
                gi_gvhd_documented=ConfidenceLevel.DEFINITE,
                gi_gvhd_grade=3,
            ),
            documentation_quality="detailed",
            notes_reviewed_count=5,
        )

        result = engine.classify(extraction, data)

        assert result.classification == CLABSIClassification.MBI_LCBI
        assert "GVHD" in str(result.reasoning) or "gvhd" in str(result.reasoning).lower()

    def test_gi_organism_not_mbi_without_mucosal_injury(self, engine):
        """GI organism in neutropenic patient WITHOUT mucositis is not MBI-LCBI."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Escherichia coli",
            culture_date=now,
            line_present=True,
            line_days_at_culture=10,
            patient_days_at_culture=14,
            anc_values_7_days=[100],  # Neutropenic
        )

        extraction = ClinicalExtraction(
            alternate_infection_sites=[],
            mbi_factors=MBIFactors(
                neutropenia_documented=ConfidenceLevel.DEFINITE,
                anc_value=100,
                mucositis_documented=ConfidenceLevel.NOT_FOUND,  # No mucositis
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, data)

        # Should NOT be MBI-LCBI - missing mucosal injury
        assert result.classification != CLABSIClassification.MBI_LCBI
        # Should be CLABSI
        assert result.classification == CLABSIClassification.CLABSI

    def test_non_mbi_organism_not_mbi_lcbi(self, engine):
        """Non-GI organism is not MBI-LCBI even with criteria met."""
        now = datetime.now()
        data = StructuredCaseData(
            organism="Staphylococcus aureus",  # Not a GI organism
            culture_date=now,
            line_present=True,
            line_days_at_culture=10,
            patient_days_at_culture=14,
            anc_values_7_days=[100],
        )

        extraction = ClinicalExtraction(
            alternate_infection_sites=[],
            mbi_factors=MBIFactors(
                neutropenia_documented=ConfidenceLevel.DEFINITE,
                anc_value=100,
                mucositis_documented=ConfidenceLevel.DEFINITE,
            ),
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, data)

        # S. aureus is not MBI-eligible, should be CLABSI
        assert result.classification == CLABSIClassification.CLABSI


# =============================================================================
# Tests: NHSN Criteria Functions
# =============================================================================

class TestNHSNCriteriaFunctions:
    """Test the NHSN organism classification functions."""

    @pytest.mark.parametrize("organism,expected", [
        ("Coagulase-negative staphylococci", True),
        ("Staphylococcus epidermidis", True),
        ("CoNS", True),
        ("Corynebacterium species", True),
        ("Bacillus species", True),
        ("Propionibacterium acnes", True),
        ("Staphylococcus aureus", False),
        ("Escherichia coli", False),
        ("Pseudomonas aeruginosa", False),
    ])
    def test_is_commensal_organism(self, organism, expected):
        assert is_commensal_organism(organism) == expected

    @pytest.mark.parametrize("organism,expected", [
        ("Escherichia coli", True),
        ("Enterococcus faecalis", True),
        ("Candida albicans", True),
        ("Klebsiella pneumoniae", True),
        ("Bacteroides fragilis", True),
        ("Streptococcus mitis", True),
        ("Staphylococcus aureus", False),
        ("Pseudomonas aeruginosa", False),
        ("Coagulase-negative staphylococci", False),
    ])
    def test_is_mbi_eligible_organism(self, organism, expected):
        assert is_mbi_eligible_organism(organism) == expected

    @pytest.mark.parametrize("organism,expected", [
        ("Staphylococcus aureus", True),
        ("Escherichia coli", True),
        ("Pseudomonas aeruginosa", True),
        ("Candida albicans", True),
        ("Coagulase-negative staphylococci", False),
        ("Corynebacterium", False),
    ])
    def test_is_recognized_pathogen(self, organism, expected):
        assert is_recognized_pathogen(organism) == expected


# =============================================================================
# Tests: Edge Cases and Review Triggers
# =============================================================================

class TestEdgeCases:
    """Test edge cases and review trigger logic."""

    def test_poor_documentation_triggers_review(self, engine, base_structured_data):
        """Poor documentation quality should trigger review."""
        extraction = ClinicalExtraction(
            alternate_infection_sites=[],
            documentation_quality="poor",
            notes_reviewed_count=1,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.requires_review
        assert any("documentation" in r.lower() for r in result.review_reasons)

    def test_multiple_review_flags_lower_confidence(self, engine, base_structured_data):
        """Multiple review flags should lower confidence."""
        extraction = ClinicalExtraction(
            alternate_infection_sites=[
                DocumentedInfectionSite(
                    site="possible uti",
                    confidence=ConfidenceLevel.POSSIBLE,
                    same_organism_mentioned=False,
                    culture_from_site_positive=None,
                    supporting_quote="",
                    note_date=None,
                ),
                DocumentedInfectionSite(
                    site="possible pneumonia",
                    confidence=ConfidenceLevel.POSSIBLE,
                    same_organism_mentioned=False,
                    culture_from_site_positive=None,
                    supporting_quote="",
                    note_date=None,
                ),
            ],
            contamination=ContaminationAssessment(
                treated_as_contaminant=ConfidenceLevel.POSSIBLE,
            ),
            documentation_quality="limited",
            notes_reviewed_count=2,
        )

        result = engine.classify(extraction, base_structured_data)

        # Should still classify but with lower confidence
        assert result.classification == CLABSIClassification.CLABSI
        assert result.confidence < 0.80
        assert result.requires_review


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
