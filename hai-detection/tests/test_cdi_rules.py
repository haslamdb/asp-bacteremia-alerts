"""Unit tests for CDI (Clostridioides difficile Infection) rules engine.

Tests cover all NHSN CDI LabID Event classification scenarios:
- Healthcare-Facility Onset (HO-CDI): Specimen >3 days after admission
- Community Onset (CO-CDI): Specimen ≤3 days after admission
- Community Onset Healthcare Facility-Associated (CO-HCFA): CO-CDI with prior discharge within 4 weeks
- Recurrent: 15-56 days since prior CDI event
- Duplicate: ≤14 days since prior CDI event (not reported)
- Incident: First event or >56 days since prior event

Reference: 2024 NHSN Patient Safety Component Manual, Chapter 12
"""

import pytest
from datetime import datetime, timedelta

from hai_src.rules.cdi_engine import CDIRulesEngine
from hai_src.rules.cdi_schemas import (
    CDIClassification,
    CDIExtraction,
    CDIStructuredData,
    CDIPriorEpisode,
    DiarrheaExtraction,
    CDIHistoryExtraction,
    CDITreatmentExtraction,
)
from hai_src.rules.schemas import ConfidenceLevel
from hai_src.rules.nhsn_criteria import (
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
)


class TestCDITimingCriteria:
    """Test NHSN timing-based CDI criteria."""

    def test_calculate_specimen_day(self):
        """Test specimen day calculation."""
        admission = datetime(2024, 1, 1, 10, 0)

        # Day 1 = admission day
        assert calculate_specimen_day(admission, datetime(2024, 1, 1, 15, 0)) == 1

        # Day 2
        assert calculate_specimen_day(admission, datetime(2024, 1, 2, 10, 0)) == 2

        # Day 3
        assert calculate_specimen_day(admission, datetime(2024, 1, 3, 10, 0)) == 3

        # Day 4
        assert calculate_specimen_day(admission, datetime(2024, 1, 4, 10, 0)) == 4

        # Day 5
        assert calculate_specimen_day(admission, datetime(2024, 1, 5, 10, 0)) == 5

    def test_onset_type_community(self):
        """Test Community Onset determination (days 1-3)."""
        assert get_cdi_onset_type(1) == "community"
        assert get_cdi_onset_type(2) == "community"
        assert get_cdi_onset_type(3) == "community"

    def test_onset_type_healthcare_facility(self):
        """Test Healthcare-Facility Onset determination (day 4+)."""
        assert get_cdi_onset_type(4) == "healthcare_facility"
        assert get_cdi_onset_type(5) == "healthcare_facility"
        assert get_cdi_onset_type(10) == "healthcare_facility"
        assert get_cdi_onset_type(100) == "healthcare_facility"


class TestCDIRecurrenceCriteria:
    """Test NHSN recurrence/duplicate criteria."""

    def test_duplicate_window(self):
        """Test ≤14 days = duplicate."""
        assert is_cdi_duplicate(0) is True
        assert is_cdi_duplicate(7) is True
        assert is_cdi_duplicate(14) is True
        assert is_cdi_duplicate(15) is False
        assert is_cdi_duplicate(None) is False

    def test_recurrence_window(self):
        """Test 15-56 days = recurrent."""
        assert is_cdi_recurrent(14) is False
        assert is_cdi_recurrent(15) is True
        assert is_cdi_recurrent(30) is True
        assert is_cdi_recurrent(56) is True
        assert is_cdi_recurrent(57) is False
        assert is_cdi_recurrent(None) is False

    def test_incident_determination(self):
        """Test >56 days or no prior = incident."""
        assert is_cdi_incident(None) is True  # No prior event
        assert is_cdi_incident(57) is True
        assert is_cdi_incident(60) is True
        assert is_cdi_incident(100) is True
        assert is_cdi_incident(14) is False
        assert is_cdi_incident(30) is False
        assert is_cdi_incident(56) is False

    def test_recurrence_status_string(self):
        """Test recurrence status string determination."""
        assert get_cdi_recurrence_status(None) == "incident"
        assert get_cdi_recurrence_status(10) == "duplicate"
        assert get_cdi_recurrence_status(14) == "duplicate"
        assert get_cdi_recurrence_status(15) == "recurrent"
        assert get_cdi_recurrence_status(30) == "recurrent"
        assert get_cdi_recurrence_status(56) == "recurrent"
        assert get_cdi_recurrence_status(57) == "incident"
        assert get_cdi_recurrence_status(100) == "incident"


class TestCDITestValidation:
    """Test qualifying test type validation."""

    def test_valid_toxin_tests(self):
        """Test that toxin tests qualify."""
        assert is_valid_cdi_test("toxin_a", "positive") is True
        assert is_valid_cdi_test("toxin_b", "positive") is True
        assert is_valid_cdi_test("toxin_ab", "positive") is True
        assert is_valid_cdi_test("toxin_a_b", "positive") is True

    def test_valid_molecular_tests(self):
        """Test that PCR/NAAT tests qualify."""
        assert is_valid_cdi_test("pcr", "positive") is True
        assert is_valid_cdi_test("naat", "positive") is True
        assert is_valid_cdi_test("toxin_gene", "positive") is True

    def test_negative_tests_dont_qualify(self):
        """Test that negative tests don't qualify."""
        assert is_valid_cdi_test("toxin_ab", "negative") is False
        assert is_valid_cdi_test("pcr", "negative") is False

    def test_antigen_only_doesnt_qualify(self):
        """Test that antigen-only tests don't qualify."""
        assert is_valid_cdi_test("gdh", "positive") is False
        assert is_valid_cdi_test("antigen", "positive") is False
        assert is_valid_cdi_test("eia_gdh", "positive") is False


class TestCOHCFA:
    """Test Community-Onset Healthcare Facility-Associated criteria."""

    def test_co_hcfa_with_recent_discharge(self):
        """Test CO-HCFA when discharged within 4 weeks."""
        # CO-CDI with discharge 14 days ago
        assert is_cdi_co_hcfa("community", 14) is True

        # CO-CDI with discharge 28 days ago (exactly 4 weeks)
        assert is_cdi_co_hcfa("community", 28) is True

    def test_not_co_hcfa_if_no_recent_discharge(self):
        """Test not CO-HCFA when discharged >4 weeks ago."""
        assert is_cdi_co_hcfa("community", 29) is False
        assert is_cdi_co_hcfa("community", 60) is False
        assert is_cdi_co_hcfa("community", None) is False

    def test_not_co_hcfa_if_ho(self):
        """Test HO-CDI can't be CO-HCFA."""
        assert is_cdi_co_hcfa("healthcare_facility", 14) is False


class TestCDIRulesEngine:
    """Test the full CDI rules engine."""

    @pytest.fixture
    def engine(self):
        """Create a CDI rules engine."""
        return CDIRulesEngine()

    @pytest.fixture
    def basic_extraction(self):
        """Create basic extraction with diarrhea documented."""
        return CDIExtraction(
            diarrhea=DiarrheaExtraction(
                diarrhea_documented=ConfidenceLevel.DEFINITE,
            ),
            prior_history=CDIHistoryExtraction(),
            treatment=CDITreatmentExtraction(
                treatment_initiated=ConfidenceLevel.DEFINITE,
                treatment_type="vancomycin",
            ),
            documentation_quality="adequate",
        )

    def test_ho_cdi_day_5(self, engine, basic_extraction):
        """Test clear HO-CDI on specimen day 5."""
        admission = datetime(2024, 1, 1, 10, 0)
        test_date = datetime(2024, 1, 5, 14, 0)  # Day 5

        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=admission,
            test_date=test_date,
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=5,
            is_formed_stool=False,
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.HO_CDI
        assert result.onset_type == "ho"
        assert result.is_recurrent is False
        assert result.specimen_day == 5
        assert result.confidence >= 0.85

    def test_co_cdi_day_2(self, engine, basic_extraction):
        """Test clear CO-CDI on specimen day 2."""
        admission = datetime(2024, 1, 1, 10, 0)
        test_date = datetime(2024, 1, 2, 14, 0)  # Day 2

        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=admission,
            test_date=test_date,
            test_type="pcr",
            test_result="positive",
            specimen_day=2,
            is_formed_stool=False,
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.CO_CDI
        assert result.onset_type == "co"
        assert result.is_recurrent is False
        assert result.specimen_day == 2

    def test_co_hcfa_cdi(self, engine, basic_extraction):
        """Test CO-HCFA-CDI with recent prior discharge."""
        admission = datetime(2024, 1, 15, 10, 0)
        test_date = datetime(2024, 1, 16, 14, 0)  # Day 2

        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=admission,
            test_date=test_date,
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=2,
            is_formed_stool=False,
            prior_discharge_date=datetime(2024, 1, 5, 12, 0),  # 10 days prior
            days_since_prior_discharge=10,
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.CO_HCFA_CDI
        assert result.onset_type == "co_hcfa"
        assert result.is_co_hcfa is True

    def test_recurrent_cdi(self, engine, basic_extraction):
        """Test recurrent CDI (30 days after prior event)."""
        prior_date = datetime(2024, 1, 1, 10, 0)
        test_date = datetime(2024, 1, 31, 14, 0)  # 30 days later

        prior_episode = CDIPriorEpisode(
            episode_id="prior-1",
            test_date=prior_date,
            onset_type="ho",
            is_recurrent=False,
        )

        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=datetime(2024, 1, 25, 10, 0),
            test_date=test_date,
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=7,  # HO-CDI
            is_formed_stool=False,
            prior_cdi_events=[prior_episode],
            days_since_last_cdi=30,
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.RECURRENT_HO
        assert result.is_recurrent is True
        assert result.recurrence_status == "recurrent"
        assert result.days_since_last_cdi == 30

    def test_duplicate_cdi_not_reported(self, engine, basic_extraction):
        """Test duplicate CDI (10 days after prior event) - not reported."""
        prior_date = datetime(2024, 1, 1, 10, 0)
        test_date = datetime(2024, 1, 11, 14, 0)  # 10 days later

        prior_episode = CDIPriorEpisode(
            episode_id="prior-1",
            test_date=prior_date,
            onset_type="ho",
            is_recurrent=False,
        )

        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=datetime(2024, 1, 5, 10, 0),
            test_date=test_date,
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=7,
            is_formed_stool=False,
            prior_cdi_events=[prior_episode],
            days_since_last_cdi=10,
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.DUPLICATE
        assert result.recurrence_status == "duplicate"

    def test_incident_after_long_gap(self, engine, basic_extraction):
        """Test incident CDI after 65 days (>56 = new episode)."""
        prior_date = datetime(2024, 1, 1, 10, 0)
        test_date = datetime(2024, 3, 6, 14, 0)  # 65 days later

        prior_episode = CDIPriorEpisode(
            episode_id="prior-1",
            test_date=prior_date,
            onset_type="ho",
            is_recurrent=False,
        )

        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=datetime(2024, 3, 1, 10, 0),
            test_date=test_date,
            test_type="pcr",
            test_result="positive",
            specimen_day=6,  # HO-CDI
            is_formed_stool=False,
            prior_cdi_events=[prior_episode],
            days_since_last_cdi=65,
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.HO_CDI
        assert result.is_recurrent is False
        assert result.recurrence_status == "incident"

    def test_not_cdi_if_negative_test(self, engine, basic_extraction):
        """Test negative test doesn't qualify."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=datetime(2024, 1, 1, 10, 0),
            test_date=datetime(2024, 1, 5, 14, 0),
            test_type="toxin_ab",
            test_result="negative",  # Negative
            specimen_day=5,
            is_formed_stool=False,
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.NOT_CDI
        assert result.test_eligible is False

    def test_not_eligible_if_formed_stool(self, engine, basic_extraction):
        """Test formed stool specimen doesn't qualify."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=datetime(2024, 1, 1, 10, 0),
            test_date=datetime(2024, 1, 5, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=5,
            is_formed_stool=True,  # Formed stool - doesn't qualify
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.NOT_ELIGIBLE

    def test_not_cdi_if_antigen_only(self, engine, basic_extraction):
        """Test antigen-only test doesn't qualify."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=datetime(2024, 1, 1, 10, 0),
            test_date=datetime(2024, 1, 5, 14, 0),
            test_type="gdh",  # Antigen only
            test_result="positive",
            specimen_day=5,
            is_formed_stool=False,
        )

        result = engine.classify(basic_extraction, structured)

        assert result.classification == CDIClassification.NOT_CDI
        assert result.test_eligible is False

    def test_confidence_reduced_for_poor_documentation(self, engine):
        """Test confidence is reduced for poor documentation."""
        extraction = CDIExtraction(
            documentation_quality="poor",
        )

        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=datetime(2024, 1, 1, 10, 0),
            test_date=datetime(2024, 1, 5, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=5,
            is_formed_stool=False,
        )

        result = engine.classify(extraction, structured)

        assert result.confidence < 0.90
        assert "Poor documentation quality" in result.review_reasons

    def test_requires_review_with_alternative_diagnoses(self, engine):
        """Test review required when alternative diagnoses are documented."""
        extraction = CDIExtraction(
            diarrhea=DiarrheaExtraction(
                diarrhea_documented=ConfidenceLevel.DEFINITE,
            ),
            alternative_diagnoses=["tube feeding intolerance", "laxative effect"],
            documentation_quality="adequate",
        )

        structured = CDIStructuredData(
            patient_id="patient-123",
            patient_mrn="MRN123",
            admission_date=datetime(2024, 1, 1, 10, 0),
            test_date=datetime(2024, 1, 5, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=5,
            is_formed_stool=False,
        )

        result = engine.classify(extraction, structured)

        assert result.requires_review is True
        assert any("Alternative diagnoses" in r for r in result.review_reasons)


class TestBoundaryConditions:
    """Test boundary conditions for CDI classification."""

    @pytest.fixture
    def engine(self):
        return CDIRulesEngine()

    @pytest.fixture
    def basic_extraction(self):
        return CDIExtraction(
            diarrhea=DiarrheaExtraction(
                diarrhea_documented=ConfidenceLevel.DEFINITE,
            ),
            treatment=CDITreatmentExtraction(
                treatment_initiated=ConfidenceLevel.DEFINITE,
            ),
            documentation_quality="adequate",
        )

    def test_day_3_is_co(self, engine, basic_extraction):
        """Test specimen day 3 is CO-CDI (boundary)."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            test_date=datetime(2024, 1, 3, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=3,
            is_formed_stool=False,
        )

        result = engine.classify(basic_extraction, structured)
        assert result.onset_type == "co"

    def test_day_4_is_ho(self, engine, basic_extraction):
        """Test specimen day 4 is HO-CDI (boundary)."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            test_date=datetime(2024, 1, 4, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=4,
            is_formed_stool=False,
        )

        result = engine.classify(basic_extraction, structured)
        assert result.onset_type == "ho"

    def test_day_14_is_duplicate(self, engine, basic_extraction):
        """Test 14 days since last is still duplicate (boundary)."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            test_date=datetime(2024, 1, 15, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=5,
            is_formed_stool=False,
            days_since_last_cdi=14,
            prior_cdi_events=[CDIPriorEpisode(
                episode_id="prior-1",
                test_date=datetime(2024, 1, 1, 10, 0),
                onset_type="ho",
                is_recurrent=False,
            )],
        )

        result = engine.classify(basic_extraction, structured)
        assert result.classification == CDIClassification.DUPLICATE

    def test_day_15_is_recurrent(self, engine, basic_extraction):
        """Test 15 days since last is recurrent (boundary)."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            test_date=datetime(2024, 1, 16, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=5,
            is_formed_stool=False,
            days_since_last_cdi=15,
            prior_cdi_events=[CDIPriorEpisode(
                episode_id="prior-1",
                test_date=datetime(2024, 1, 1, 10, 0),
                onset_type="ho",
                is_recurrent=False,
            )],
        )

        result = engine.classify(basic_extraction, structured)
        assert result.is_recurrent is True
        assert result.recurrence_status == "recurrent"

    def test_day_56_is_recurrent(self, engine, basic_extraction):
        """Test 56 days since last is still recurrent (boundary)."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            test_date=datetime(2024, 2, 26, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=5,
            is_formed_stool=False,
            days_since_last_cdi=56,
            prior_cdi_events=[CDIPriorEpisode(
                episode_id="prior-1",
                test_date=datetime(2024, 1, 1, 10, 0),
                onset_type="ho",
                is_recurrent=False,
            )],
        )

        result = engine.classify(basic_extraction, structured)
        assert result.is_recurrent is True

    def test_day_57_is_incident(self, engine, basic_extraction):
        """Test 57 days since last is new incident (boundary)."""
        structured = CDIStructuredData(
            patient_id="patient-123",
            test_date=datetime(2024, 2, 27, 14, 0),
            test_type="toxin_ab",
            test_result="positive",
            specimen_day=5,
            is_formed_stool=False,
            days_since_last_cdi=57,
            prior_cdi_events=[CDIPriorEpisode(
                episode_id="prior-1",
                test_date=datetime(2024, 1, 1, 10, 0),
                onset_type="ho",
                is_recurrent=False,
            )],
        )

        result = engine.classify(basic_extraction, structured)
        assert result.is_recurrent is False
        assert result.recurrence_status == "incident"
