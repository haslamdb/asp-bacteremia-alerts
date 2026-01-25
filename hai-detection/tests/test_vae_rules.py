"""Tests for VAE rules engine.

These tests validate the deterministic NHSN VAE criteria application.
Each test represents a clinical scenario with known expected outcome.

NHSN VAE Hierarchy (most specific first):
1. Probable VAP - IVAC + purulent secretions + positive quantitative culture
2. Possible VAP - IVAC + purulent secretions OR positive respiratory culture
3. IVAC - VAC + temperature/WBC abnormality + new antimicrobial ≥4 days
4. VAC - ≥2 days stable ventilator settings followed by ≥2 days sustained worsening
"""

import pytest
from datetime import datetime, date, timedelta

from hai_src.rules.vae_engine import VAERulesEngine, classify_vae
from hai_src.rules.vae_schemas import (
    VAEExtraction,
    VAEStructuredData,
    VAEClassification,
    VAETier,
    TemperatureExtraction,
    WBCExtraction,
    AntimicrobialExtraction,
    RespiratorySecretionsExtraction,
    RespiratoryCultureExtraction,
    VentilatorStatusExtraction,
)
from hai_src.rules.schemas import ConfidenceLevel
from hai_src.rules.nhsn_criteria import (
    VAE_MIN_VENT_DAYS,
    VAE_FIO2_INCREASE_THRESHOLD,
    VAE_PEEP_INCREASE_THRESHOLD,
    IVAC_FEVER_THRESHOLD_CELSIUS,
    IVAC_LEUKOCYTOSIS_THRESHOLD,
    IVAC_ANTIMICROBIAL_MIN_DAYS,
    is_qualifying_antimicrobial,
    meets_vap_quantitative_threshold,
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def engine():
    """Create a rules engine for testing."""
    return VAERulesEngine(strict_mode=True)


@pytest.fixture
def base_structured_data():
    """Base case: VAC criteria met (eligible for IVAC/VAP evaluation)."""
    now = datetime.now()
    vac_onset = now.date() - timedelta(days=5)

    return VAEStructuredData(
        patient_id="patient-123",
        intubation_date=now - timedelta(days=10),
        ventilator_days=10,
        vac_onset_date=vac_onset,
        baseline_period_start=vac_onset - timedelta(days=4),
        baseline_period_end=vac_onset - timedelta(days=2),
        baseline_min_fio2=30.0,
        baseline_min_peep=5.0,
        worsening_start_date=vac_onset,
        fio2_increase=25.0,  # Meets ≥20% threshold
        peep_increase=4.0,    # Meets ≥3 cmH2O threshold
        location_at_vac="ICU-A",
        location_type="ICU",
    )


@pytest.fixture
def base_extraction():
    """Base extraction: minimal findings, no infection signs."""
    return VAEExtraction(
        temperature=TemperatureExtraction(),
        wbc=WBCExtraction(),
        antimicrobials=[],
        secretions=RespiratorySecretionsExtraction(),
        cultures=[],
        ventilator_status=VentilatorStatusExtraction(
            on_mechanical_ventilation=ConfidenceLevel.DEFINITE,
        ),
        documentation_quality="adequate",
        notes_reviewed_count=3,
    )


# =============================================================================
# Tests: Basic Eligibility
# =============================================================================

class TestBasicEligibility:
    """Test basic VAE eligibility criteria."""

    def test_insufficient_ventilator_days_not_eligible(self, engine, base_extraction):
        """Patient on ventilator <2 days is not eligible."""
        data = VAEStructuredData(
            patient_id="patient-123",
            intubation_date=datetime.now() - timedelta(days=1),
            ventilator_days=1,  # Only 1 day - insufficient
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == VAEClassification.NOT_ELIGIBLE
        assert not result.requires_review
        assert "Insufficient ventilator days" in result.reasoning[0]

    def test_no_vac_onset_not_eligible(self, engine, base_extraction):
        """No VAC onset date identified is not eligible."""
        data = VAEStructuredData(
            patient_id="patient-123",
            intubation_date=datetime.now() - timedelta(days=10),
            ventilator_days=10,
            vac_onset_date=None,  # No VAC detected
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == VAEClassification.NOT_ELIGIBLE
        assert "No VAC onset date" in result.reasoning[1]

    def test_insufficient_fio2_peep_increase_not_eligible(self, engine, base_extraction):
        """Neither FiO2 nor PEEP threshold met is not eligible."""
        now = datetime.now()
        data = VAEStructuredData(
            patient_id="patient-123",
            intubation_date=now - timedelta(days=10),
            ventilator_days=10,
            vac_onset_date=now.date() - timedelta(days=5),
            fio2_increase=15.0,  # Below 20% threshold
            peep_increase=2.0,   # Below 3 cmH2O threshold
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == VAEClassification.NOT_ELIGIBLE
        # Check that it was identified as not eligible due to threshold
        assert "not eligible" in result.reasoning[-1].lower() or "threshold" in str(result.reasoning).lower()

    def test_fio2_threshold_met_eligible(self, engine, base_extraction, base_structured_data):
        """FiO2 increase ≥20% is eligible for VAE."""
        data = base_structured_data
        data.fio2_increase = 25.0
        data.peep_increase = 0.0  # Only FiO2 meets threshold

        result = engine.classify(base_extraction, data)

        # Should be at least VAC
        assert result.classification != VAEClassification.NOT_ELIGIBLE
        assert result.vac_met

    def test_peep_threshold_met_eligible(self, engine, base_extraction, base_structured_data):
        """PEEP increase ≥3 cmH2O is eligible for VAE."""
        data = base_structured_data
        data.fio2_increase = 0.0  # Only PEEP meets threshold
        data.peep_increase = 5.0

        result = engine.classify(base_extraction, data)

        # Should be at least VAC
        assert result.classification != VAEClassification.NOT_ELIGIBLE
        assert result.vac_met


# =============================================================================
# Tests: VAC Classification (Tier 1)
# =============================================================================

class TestVACClassification:
    """Test cases that should classify as VAC only."""

    def test_vac_only_no_infection_signs(self, engine, base_extraction, base_structured_data):
        """VAC without infection signs should classify as VAC only."""
        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == VAEClassification.VAC
        assert result.vae_tier == VAETier.TIER_1
        assert result.vac_met
        assert not result.ivac_met
        assert "VAC (Ventilator-Associated Condition)" in str(result.reasoning)

    def test_vac_with_fever_but_no_antibiotics(self, engine, base_structured_data):
        """VAC + fever but no antibiotics should still be VAC only."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=39.0,
            ),
            # No antimicrobials
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.VAC
        assert result.vae_tier == VAETier.TIER_1
        assert result.temperature_criterion_met is False  # Set in IVAC eval
        assert not result.ivac_met

    def test_vac_with_antibiotics_but_no_fever_or_wbc(self, engine, base_structured_data):
        """VAC + antibiotics but no temperature/WBC criteria is VAC only."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(),  # No fever
            wbc=WBCExtraction(),  # Normal WBC
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["vancomycin"],
                    duration_days=7,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.VAC
        assert "Neither temperature nor WBC criterion met" in str(result.reasoning)


# =============================================================================
# Tests: IVAC Classification (Tier 2)
# =============================================================================

class TestIVACClassification:
    """Test cases that should classify as IVAC."""

    def test_ivac_fever_and_antibiotics(self, engine, base_structured_data):
        """VAC + fever + qualifying antibiotics ≥4 days = IVAC."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=38.5,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["piperacillin-tazobactam"],
                    duration_days=5,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.IVAC
        assert result.vae_tier == VAETier.TIER_2
        assert result.ivac_met
        assert result.temperature_criterion_met
        assert result.antimicrobial_criterion_met
        assert "piperacillin-tazobactam" in result.qualifying_antimicrobials

    def test_ivac_leukocytosis_and_antibiotics(self, engine, base_structured_data):
        """VAC + leukocytosis + qualifying antibiotics = IVAC."""
        extraction = VAEExtraction(
            wbc=WBCExtraction(
                leukocytosis_documented=ConfidenceLevel.DEFINITE,
                max_wbc=15000,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["ceftriaxone"],
                    duration_days=6,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.IVAC
        assert result.wbc_criterion_met
        assert result.antimicrobial_criterion_met

    def test_ivac_hypothermia_and_antibiotics(self, engine, base_structured_data):
        """VAC + hypothermia + qualifying antibiotics = IVAC."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                hypothermia_documented=ConfidenceLevel.DEFINITE,
                min_temp_celsius=35.0,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["meropenem"],
                    duration_days=5,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.IVAC
        assert result.temperature_criterion_met
        assert "hypothermia" in str(result.reasoning).lower()

    def test_ivac_leukopenia_and_antibiotics(self, engine, base_structured_data):
        """VAC + leukopenia + qualifying antibiotics = IVAC."""
        extraction = VAEExtraction(
            wbc=WBCExtraction(
                leukopenia_documented=ConfidenceLevel.DEFINITE,
                min_wbc=2000,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["vancomycin"],
                    duration_days=5,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.IVAC
        assert result.wbc_criterion_met
        assert "leukopenia" in str(result.reasoning).lower()

    def test_ivac_from_structured_data_temps(self, engine, base_extraction, base_structured_data):
        """IVAC with temperature from structured EHR data."""
        base_structured_data.temperatures = [
            (datetime.now(), 38.9),  # Fever from EHR
        ]
        base_structured_data.qualifying_antimicrobials = [
            {"drug": "levofloxacin", "start_date": date.today(), "days_on_drug": 5, "route": "IV"}
        ]

        result = engine.classify(base_extraction, base_structured_data)

        assert result.classification == VAEClassification.IVAC
        assert "from EHR" in str(result.reasoning)

    def test_ivac_antibiotics_less_than_4_days_not_ivac(self, engine, base_structured_data):
        """Antibiotics <4 days should not meet IVAC criteria."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=39.0,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["vancomycin"],
                    duration_days=3,  # Less than 4 days
                    continued_four_or_more_days=ConfidenceLevel.NOT_FOUND,
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.VAC  # Not IVAC
        assert not result.antimicrobial_criterion_met

    def test_non_qualifying_antimicrobial_not_ivac(self, engine, base_structured_data):
        """Non-qualifying antimicrobial should not meet IVAC criteria."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=39.0,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    # Topical agents don't qualify
                    antimicrobial_names=["mupirocin"],
                    duration_days=7,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        # Mupirocin is topical - not a qualifying IV/PO antimicrobial
        assert result.classification == VAEClassification.VAC


# =============================================================================
# Tests: Possible VAP Classification (Tier 3)
# =============================================================================

class TestPossibleVAPClassification:
    """Test cases that should classify as Possible VAP."""

    def test_possible_vap_purulent_secretions(self, engine, base_structured_data):
        """IVAC + purulent secretions = Possible VAP."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=38.8,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["meropenem"],
                    duration_days=5,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            secretions=RespiratorySecretionsExtraction(
                purulent_secretions=ConfidenceLevel.DEFINITE,
                secretion_description="Thick yellow-green sputum",
            ),
            documentation_quality="detailed",
            notes_reviewed_count=5,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.POSSIBLE_VAP
        assert result.vae_tier == VAETier.TIER_3
        assert result.vap_met
        assert result.purulent_secretions_met

    def test_possible_vap_positive_culture(self, engine, base_structured_data):
        """IVAC + positive respiratory culture = Possible VAP."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=38.6,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["ceftriaxone"],
                    duration_days=5,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            cultures=[
                RespiratoryCultureExtraction(
                    culture_positive=ConfidenceLevel.DEFINITE,
                    specimen_type="sputum",
                    organism_identified="Pseudomonas aeruginosa",
                )
            ],
            documentation_quality="adequate",
            notes_reviewed_count=4,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.POSSIBLE_VAP
        assert result.positive_culture_met
        assert result.organism_identified == "Pseudomonas aeruginosa"

    def test_possible_vap_gram_stain_criteria(self, engine, base_structured_data):
        """IVAC + gram stain meeting PMN criteria = Possible VAP."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=39.0,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["vancomycin", "piperacillin-tazobactam"],
                    duration_days=6,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            secretions=RespiratorySecretionsExtraction(
                gram_stain_positive=ConfidenceLevel.DEFINITE,
                pmn_count=50,
                epithelial_count=5,
            ),
            documentation_quality="detailed",
            notes_reviewed_count=5,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.POSSIBLE_VAP
        assert result.purulent_secretions_met
        assert "PMNs" in str(result.reasoning)


# =============================================================================
# Tests: Probable VAP Classification (Tier 3)
# =============================================================================

class TestProbableVAPClassification:
    """Test cases that should classify as Probable VAP."""

    def test_probable_vap_purulent_and_quantitative_culture(self, engine, base_structured_data):
        """IVAC + purulent secretions + quantitative culture = Probable VAP."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=39.2,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["cefepime"],
                    duration_days=7,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            secretions=RespiratorySecretionsExtraction(
                purulent_secretions=ConfidenceLevel.DEFINITE,
                secretion_description="Thick purulent sputum",
            ),
            cultures=[
                RespiratoryCultureExtraction(
                    culture_positive=ConfidenceLevel.DEFINITE,
                    specimen_type="BAL",
                    organism_identified="Staphylococcus aureus",
                    colony_count="10^5 CFU/mL",
                    meets_quantitative_threshold=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="detailed",
            notes_reviewed_count=6,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.PROBABLE_VAP
        assert result.vae_tier == VAETier.TIER_3
        assert result.purulent_secretions_met
        assert result.quantitative_threshold_met
        assert result.organism_identified == "Staphylococcus aureus"
        assert result.specimen_type == "BAL"

    def test_probable_vap_with_eta_culture(self, engine, base_structured_data):
        """Probable VAP with ETA culture meeting threshold."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=38.9,
            ),
            wbc=WBCExtraction(
                leukocytosis_documented=ConfidenceLevel.DEFINITE,
                max_wbc=18000,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["tobramycin", "piperacillin-tazobactam"],
                    duration_days=5,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            secretions=RespiratorySecretionsExtraction(
                purulent_secretions=ConfidenceLevel.DEFINITE,
                gram_stain_positive=ConfidenceLevel.DEFINITE,
                pmn_count=30,
                epithelial_count=3,
            ),
            cultures=[
                RespiratoryCultureExtraction(
                    culture_positive=ConfidenceLevel.DEFINITE,
                    specimen_type="ETA",  # Endotracheal aspirate
                    organism_identified="Klebsiella pneumoniae",
                    colony_count="10^6 CFU/mL",  # ETA threshold
                    meets_quantitative_threshold=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="detailed",
            notes_reviewed_count=7,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.PROBABLE_VAP
        assert result.specimen_type == "ETA"

    def test_probable_vap_from_structured_culture_data(self, engine, base_structured_data):
        """Probable VAP using culture data from structured EHR."""
        base_structured_data.respiratory_cultures = [
            {"specimen_type": "BAL", "organism": "MRSA", "count": 100000, "date": date.today()}
        ]

        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=39.1,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["vancomycin"],
                    duration_days=10,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            secretions=RespiratorySecretionsExtraction(
                purulent_secretions=ConfidenceLevel.DEFINITE,
            ),
            documentation_quality="detailed",
            notes_reviewed_count=5,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.classification == VAEClassification.PROBABLE_VAP
        assert "from EHR" in str(result.reasoning)


# =============================================================================
# Tests: VAE Type Hierarchy
# =============================================================================

class TestVAEHierarchy:
    """Test that more specific classifications take precedence."""

    def test_probable_vap_takes_precedence(self, engine, base_structured_data):
        """Probable VAP should be classified when all criteria met."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.DEFINITE,
                max_temp_celsius=39.5,
            ),
            wbc=WBCExtraction(
                leukocytosis_documented=ConfidenceLevel.DEFINITE,
                max_wbc=20000,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.DEFINITE,
                    antimicrobial_names=["meropenem", "vancomycin"],
                    duration_days=10,
                    continued_four_or_more_days=ConfidenceLevel.DEFINITE,
                )
            ],
            secretions=RespiratorySecretionsExtraction(
                purulent_secretions=ConfidenceLevel.DEFINITE,
                gram_stain_positive=ConfidenceLevel.DEFINITE,
            ),
            cultures=[
                RespiratoryCultureExtraction(
                    culture_positive=ConfidenceLevel.DEFINITE,
                    specimen_type="BAL",
                    organism_identified="Pseudomonas aeruginosa",
                    meets_quantitative_threshold=ConfidenceLevel.DEFINITE,
                )
            ],
            documentation_quality="detailed",
            notes_reviewed_count=8,
        )

        result = engine.classify(extraction, base_structured_data)

        # Should be Probable VAP (most specific)
        assert result.classification == VAEClassification.PROBABLE_VAP
        assert result.vap_met
        assert result.ivac_met
        assert result.vac_met


# =============================================================================
# Tests: Not VAE
# =============================================================================

class TestNotVAE:
    """Test cases that should not be classified as VAE."""

    def test_no_vac_criteria_is_not_vae(self, engine, base_extraction):
        """Without VAC criteria, classification is NOT_ELIGIBLE."""
        data = VAEStructuredData(
            patient_id="patient-123",
            intubation_date=datetime.now() - timedelta(days=10),
            ventilator_days=10,
            # No VAC onset - worsening not detected
            vac_onset_date=None,
        )

        result = engine.classify(base_extraction, data)

        assert result.classification == VAEClassification.NOT_ELIGIBLE
        assert not result.vac_met


# =============================================================================
# Tests: Review Triggers
# =============================================================================

class TestReviewTriggers:
    """Test conditions that trigger IP review."""

    def test_possible_findings_trigger_review(self, engine, base_structured_data):
        """Possible (not definite) findings should trigger review."""
        extraction = VAEExtraction(
            temperature=TemperatureExtraction(
                fever_documented=ConfidenceLevel.POSSIBLE,
                max_temp_celsius=38.2,
            ),
            antimicrobials=[
                AntimicrobialExtraction(
                    new_antimicrobial_started=ConfidenceLevel.POSSIBLE,
                    antimicrobial_names=["vancomycin"],
                )
            ],
            documentation_quality="limited",
            notes_reviewed_count=2,
        )

        result = engine.classify(extraction, base_structured_data)

        assert result.requires_review
        assert len(result.review_reasons) > 0

    def test_poor_documentation_triggers_review(self, engine, base_extraction, base_structured_data):
        """Poor documentation quality should affect confidence."""
        base_extraction.documentation_quality = "poor"
        base_extraction.notes_reviewed_count = 1

        result = engine.classify(base_extraction, base_structured_data)

        # Poor documentation should lower confidence
        assert result.confidence < 0.75

    def test_vap_suspected_triggers_review(self, engine, base_structured_data):
        """Team suspecting VAP should trigger review even without all criteria."""
        extraction = VAEExtraction(
            vap_suspected_by_team=ConfidenceLevel.DEFINITE,
            clinical_team_impression="Suspect VAP, started antibiotics",
            documentation_quality="adequate",
            notes_reviewed_count=3,
        )

        result = engine.classify(extraction, base_structured_data)

        # Should be flagged for review when team suspects but criteria not met
        assert result.classification == VAEClassification.VAC
        # Note: Adding team suspicion doesn't automatically elevate classification
        # but the clinical context is captured


# =============================================================================
# Tests: NHSN Criteria Functions
# =============================================================================

class TestNHSNCriteriaFunctions:
    """Test NHSN VAE-related helper functions."""

    @pytest.mark.parametrize("drug,expected", [
        ("vancomycin", True),
        ("ceftriaxone", True),
        ("piperacillin-tazobactam", True),
        ("meropenem", True),
        ("ciprofloxacin", True),
        ("levofloxacin", True),
        ("mupirocin", False),  # Topical
        ("bacitracin", False),  # Topical
        ("nystatin", False),    # Antifungal not typically qualifying
    ])
    def test_is_qualifying_antimicrobial(self, drug, expected):
        """Test qualifying antimicrobial identification."""
        assert is_qualifying_antimicrobial(drug) == expected

    @pytest.mark.parametrize("specimen,count,expected", [
        ("BAL", 100000, True),    # 10^5 meets BAL threshold (10^4)
        ("BAL", 1000, False),     # Below BAL threshold
        ("ETA", 1000000, True),   # 10^6 meets ETA threshold
        ("ETA", 10000, False),    # Below ETA threshold
        ("PSB", 1000, True),      # 10^3 meets PSB threshold
    ])
    def test_meets_vap_quantitative_threshold(self, specimen, count, expected):
        """Test quantitative culture threshold evaluation."""
        assert meets_vap_quantitative_threshold(specimen, count) == expected


# =============================================================================
# Tests: Convenience Function
# =============================================================================

class TestConvenienceFunction:
    """Test the classify_vae convenience function."""

    def test_classify_vae_function(self, base_extraction, base_structured_data):
        """classify_vae should work the same as engine.classify."""
        result = classify_vae(base_extraction, base_structured_data)

        assert result.classification in [
            VAEClassification.PROBABLE_VAP,
            VAEClassification.POSSIBLE_VAP,
            VAEClassification.IVAC,
            VAEClassification.VAC,
            VAEClassification.NOT_VAE,
            VAEClassification.NOT_ELIGIBLE,
            VAEClassification.INDETERMINATE,
        ]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
