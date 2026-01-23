"""Tests for CLABSI candidate detection."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, MagicMock

from src.models import (
    Patient,
    CultureResult,
    DeviceInfo,
    HAICandidate,
    HAIType,
    CandidateStatus,
)
from src.candidates.clabsi import CLABSICandidateDetector, COMMON_CONTAMINANTS


class TestCLABSICandidateDetector:
    """Tests for CLABSICandidateDetector."""

    @pytest.fixture
    def mock_culture_source(self):
        """Create mock culture source."""
        return Mock()

    @pytest.fixture
    def mock_device_source(self):
        """Create mock device source."""
        return Mock()

    @pytest.fixture
    def detector(self, mock_culture_source, mock_device_source):
        """Create detector with mocked sources."""
        return CLABSICandidateDetector(
            culture_source=mock_culture_source,
            device_source=mock_device_source,
        )

    @pytest.fixture
    def sample_patient(self):
        """Sample patient."""
        return Patient(
            fhir_id="patient-123",
            mrn="MRN001",
            name="Test Patient",
        )

    @pytest.fixture
    def sample_culture(self):
        """Sample positive blood culture."""
        return CultureResult(
            fhir_id="culture-456",
            collection_date=datetime(2024, 1, 15, 10, 0),
            organism="Staphylococcus aureus",
            is_positive=True,
        )

    @pytest.fixture
    def sample_device(self):
        """Sample central line with 5 days dwell time."""
        return DeviceInfo(
            device_type="central_venous_catheter",
            insertion_date=datetime(2024, 1, 10, 8, 0),
            site="right_subclavian",
        )

    def test_detect_creates_candidate_when_criteria_met(
        self,
        detector,
        mock_culture_source,
        mock_device_source,
        sample_patient,
        sample_culture,
        sample_device,
    ):
        """Test that detector creates candidate when CLABSI criteria met."""
        # Setup mocks
        mock_culture_source.get_positive_blood_cultures.return_value = [
            (sample_patient, sample_culture)
        ]
        mock_device_source.get_central_lines.return_value = [sample_device]

        # Run detection
        candidates = detector.detect_candidates(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
        )

        # Verify
        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.hai_type == HAIType.CLABSI
        assert candidate.patient.mrn == "MRN001"
        assert candidate.culture.organism == "Staphylococcus aureus"
        assert candidate.device_days_at_culture == 5
        assert candidate.meets_initial_criteria is True
        assert candidate.status == CandidateStatus.PENDING

    def test_no_candidate_when_no_central_line(
        self,
        detector,
        mock_culture_source,
        mock_device_source,
        sample_patient,
        sample_culture,
    ):
        """Test that no candidate created when no central line present."""
        mock_culture_source.get_positive_blood_cultures.return_value = [
            (sample_patient, sample_culture)
        ]
        mock_device_source.get_central_lines.return_value = []

        candidates = detector.detect_candidates(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
        )

        assert len(candidates) == 0

    def test_candidate_excluded_when_device_days_insufficient(
        self,
        detector,
        mock_culture_source,
        mock_device_source,
        sample_patient,
        sample_culture,
    ):
        """Test candidate excluded when device days < 2."""
        # Device inserted same day as culture (0 days)
        short_dwell_device = DeviceInfo(
            device_type="central_venous_catheter",
            insertion_date=datetime(2024, 1, 15, 8, 0),  # Same day as culture
        )

        mock_culture_source.get_positive_blood_cultures.return_value = [
            (sample_patient, sample_culture)
        ]
        mock_device_source.get_central_lines.return_value = [short_dwell_device]

        candidates = detector.detect_candidates(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.meets_initial_criteria is False
        assert candidate.status == CandidateStatus.EXCLUDED
        assert "Device days" in candidate.exclusion_reason

    def test_contaminant_organism_requires_second_culture(
        self,
        detector,
        mock_culture_source,
        mock_device_source,
        sample_patient,
        sample_device,
    ):
        """Test that contaminant organisms require confirmatory culture."""
        contaminant_culture = CultureResult(
            fhir_id="culture-contaminant",
            collection_date=datetime(2024, 1, 15, 10, 0),
            organism="Coagulase-negative staphylococci",
            is_positive=True,
        )

        mock_culture_source.get_positive_blood_cultures.return_value = [
            (sample_patient, contaminant_culture)
        ]
        mock_device_source.get_central_lines.return_value = [sample_device]
        # No confirmatory culture
        mock_culture_source.get_cultures_for_patient.return_value = []

        candidates = detector.detect_candidates(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.meets_initial_criteria is False
        assert "contaminant" in candidate.exclusion_reason.lower()

    def test_contaminant_with_confirmatory_culture_meets_criteria(
        self,
        detector,
        mock_culture_source,
        mock_device_source,
        sample_patient,
        sample_device,
    ):
        """Test contaminant with second positive culture meets criteria."""
        contaminant_culture = CultureResult(
            fhir_id="culture-1",
            collection_date=datetime(2024, 1, 15, 10, 0),
            organism="Coagulase-negative staphylococci",
            is_positive=True,
        )

        confirmatory_culture = CultureResult(
            fhir_id="culture-2",
            collection_date=datetime(2024, 1, 16, 14, 0),  # Next day
            organism="Coagulase-negative staphylococci",
            is_positive=True,
        )

        mock_culture_source.get_positive_blood_cultures.return_value = [
            (sample_patient, contaminant_culture)
        ]
        mock_device_source.get_central_lines.return_value = [sample_device]
        mock_culture_source.get_cultures_for_patient.return_value = [
            contaminant_culture,
            confirmatory_culture,
        ]

        candidates = detector.detect_candidates(
            start_date=datetime(2024, 1, 1),
            end_date=datetime(2024, 1, 31),
        )

        assert len(candidates) == 1
        candidate = candidates[0]
        assert candidate.meets_initial_criteria is True


class TestValidateCandidate:
    """Tests for candidate validation logic."""

    @pytest.fixture
    def detector(self):
        return CLABSICandidateDetector(
            culture_source=Mock(),
            device_source=Mock(),
        )

    def test_valid_candidate(self, detector):
        """Test validation of valid candidate."""
        candidate = HAICandidate(
            id="test-1",
            hai_type=HAIType.CLABSI,
            patient=Patient(fhir_id="p1", mrn="MRN001", name="Test"),
            culture=CultureResult(
                fhir_id="c1",
                collection_date=datetime.now(),
                organism="E. coli",
            ),
            device_info=DeviceInfo(
                device_type="picc",
                insertion_date=datetime.now() - timedelta(days=5),
            ),
            device_days_at_culture=5,
        )

        is_valid, reason = detector.validate_candidate(candidate)
        assert is_valid is True
        assert reason is None

    def test_invalid_device_days(self, detector):
        """Test validation fails for insufficient device days."""
        candidate = HAICandidate(
            id="test-1",
            hai_type=HAIType.CLABSI,
            patient=Patient(fhir_id="p1", mrn="MRN001", name="Test"),
            culture=CultureResult(
                fhir_id="c1",
                collection_date=datetime.now(),
            ),
            device_days_at_culture=1,  # Less than 2
        )

        is_valid, reason = detector.validate_candidate(candidate)
        assert is_valid is False
        assert "Device days" in reason


class TestCommonContaminants:
    """Tests for contaminant organism detection."""

    def test_contaminant_list_contains_expected_organisms(self):
        """Verify expected contaminants are in the list."""
        expected = [
            "staphylococcus epidermidis",
            "corynebacterium",
            "micrococcus",
        ]
        for organism in expected:
            assert organism in COMMON_CONTAMINANTS

    def test_staph_aureus_not_contaminant(self):
        """S. aureus should NOT be a contaminant."""
        assert "staphylococcus aureus" not in COMMON_CONTAMINANTS
