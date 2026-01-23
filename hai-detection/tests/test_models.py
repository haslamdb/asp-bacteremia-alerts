"""Tests for NHSN data models."""

import pytest
import json
from datetime import datetime, date

from src.models import (
    HAIType,
    CandidateStatus,
    ClassificationDecision,
    ReviewQueueType,
    ReviewerDecision,
    Patient,
    CultureResult,
    DeviceInfo,
    HAICandidate,
    Classification,
    Review,
    SupportingEvidence,
)


class TestEnums:
    """Test enum definitions."""

    def test_hai_type_values(self):
        """Test HAI type enum values."""
        assert HAIType.CLABSI.value == "clabsi"
        assert HAIType.CAUTI.value == "cauti"
        assert HAIType.SSI.value == "ssi"
        assert HAIType.VAE.value == "vae"

    def test_candidate_status_values(self):
        """Test candidate status enum values."""
        assert CandidateStatus.PENDING.value == "pending"
        assert CandidateStatus.CONFIRMED.value == "confirmed"
        assert CandidateStatus.EXCLUDED.value == "excluded"

    def test_classification_decision_values(self):
        """Test classification decision enum values."""
        assert ClassificationDecision.HAI_CONFIRMED.value == "hai_confirmed"
        assert ClassificationDecision.NOT_HAI.value == "not_hai"
        assert ClassificationDecision.PENDING_REVIEW.value == "pending_review"


class TestDeviceInfo:
    """Tests for DeviceInfo model."""

    def test_days_at_date_calculation(self):
        """Test device days calculation."""
        device = DeviceInfo(
            device_type="central_venous_catheter",
            insertion_date=datetime(2024, 1, 1, 8, 0),
        )

        reference_date = datetime(2024, 1, 6, 10, 0)
        days = device.days_at_date(reference_date)

        assert days == 5

    def test_days_at_date_none_when_no_insertion(self):
        """Test returns None when no insertion date."""
        device = DeviceInfo(device_type="picc")
        days = device.days_at_date(datetime.now())
        assert days is None

    def test_to_dict(self):
        """Test dictionary conversion."""
        device = DeviceInfo(
            device_type="central_venous_catheter",
            insertion_date=datetime(2024, 1, 1, 8, 0),
            site="right_subclavian",
            fhir_id="device-123",
        )

        d = device.to_dict()

        assert d["device_type"] == "central_venous_catheter"
        assert d["site"] == "right_subclavian"
        assert d["fhir_id"] == "device-123"
        assert "2024-01-01" in d["insertion_date"]


class TestHAICandidate:
    """Tests for HAICandidate model."""

    @pytest.fixture
    def sample_candidate(self):
        """Create sample candidate."""
        return HAICandidate(
            id="candidate-123",
            hai_type=HAIType.CLABSI,
            patient=Patient(fhir_id="p1", mrn="MRN001", name="Test Patient"),
            culture=CultureResult(
                fhir_id="c1",
                collection_date=datetime(2024, 1, 15, 10, 0),
                organism="E. coli",
            ),
            device_info=DeviceInfo(
                device_type="picc",
                insertion_date=datetime(2024, 1, 10),
            ),
            device_days_at_culture=5,
            status=CandidateStatus.PENDING,
        )

    def test_to_db_row(self, sample_candidate):
        """Test database row conversion."""
        row = sample_candidate.to_db_row()

        assert row["id"] == "candidate-123"
        assert row["hai_type"] == "clabsi"
        assert row["patient_mrn"] == "MRN001"
        assert row["organism"] == "E. coli"
        assert row["device_days_at_culture"] == 5
        assert row["status"] == "pending"

        # Device info should be JSON
        device_info = json.loads(row["device_info"])
        assert device_info["device_type"] == "picc"

    def test_meets_initial_criteria_default_true(self, sample_candidate):
        """Test default value for meets_initial_criteria."""
        assert sample_candidate.meets_initial_criteria is True


class TestClassification:
    """Tests for Classification model."""

    def test_to_db_row(self):
        """Test database row conversion."""
        classification = Classification(
            id="class-123",
            candidate_id="candidate-456",
            decision=ClassificationDecision.HAI_CONFIRMED,
            confidence=0.85,
            alternative_source=None,
            is_mbi_lcbi=False,
            supporting_evidence=[
                SupportingEvidence(text="Evidence 1", source="progress_note"),
            ],
            contradicting_evidence=[],
            reasoning="Clear CLABSI case",
            model_used="llama3.1:70b",
            prompt_version="clabsi_v1",
            tokens_used=1500,
            processing_time_ms=2500,
        )

        row = classification.to_db_row()

        assert row["id"] == "class-123"
        assert row["candidate_id"] == "candidate-456"
        assert row["decision"] == "hai_confirmed"
        assert row["confidence"] == 0.85
        assert row["model_used"] == "llama3.1:70b"

        # Evidence should be JSON
        supporting = json.loads(row["supporting_evidence"])
        assert len(supporting) == 1
        assert supporting[0]["text"] == "Evidence 1"


