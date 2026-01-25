"""Tests for the antibiotic indication monitor."""

import pytest
from datetime import datetime
from unittest.mock import Mock, patch

import sys
from pathlib import Path

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from au_alerts_src.models import (
    Patient,
    MedicationOrder,
    IndicationCandidate,
    IndicationAssessment,
    AlertSeverity,
)
from au_alerts_src.indication_db import IndicationDatabase


class TestIndicationCandidate:
    """Test IndicationCandidate model."""

    def test_create_candidate(self):
        """Test creating an indication candidate."""
        patient = Patient(
            fhir_id="pat-123",
            mrn="MRN001",
            name="Test Patient",
        )

        medication = MedicationOrder(
            fhir_id="med-123",
            patient_id="pat-123",
            medication_name="Ceftriaxone",
            rxnorm_code="309090",
            start_date=datetime.now(),
        )

        candidate = IndicationCandidate(
            id="cand-123",
            patient=patient,
            medication=medication,
            icd10_codes=["J18.9"],
            icd10_classification="A",
            icd10_primary_indication="Pneumonia",
            llm_extracted_indication=None,
            llm_classification=None,
            final_classification="A",
            classification_source="icd10",
            status="pending",
        )

        assert candidate.id == "cand-123"
        assert candidate.patient.mrn == "MRN001"
        assert candidate.medication.medication_name == "Ceftriaxone"
        assert candidate.icd10_classification == "A"
        assert candidate.final_classification == "A"


class TestIndicationDatabase:
    """Test IndicationDatabase operations."""

    @pytest.fixture
    def temp_db(self, tmp_path):
        """Create a temporary database."""
        db_path = tmp_path / "test_indications.db"
        return IndicationDatabase(str(db_path))

    def test_save_and_get_candidate(self, temp_db):
        """Test saving and retrieving a candidate."""
        patient = Patient(
            fhir_id="pat-456",
            mrn="MRN002",
            name="Test Patient 2",
        )

        medication = MedicationOrder(
            fhir_id="med-456",
            patient_id="pat-456",
            medication_name="Vancomycin",
            rxnorm_code="11124",
            start_date=datetime.now(),
        )

        candidate = IndicationCandidate(
            id="cand-456",
            patient=patient,
            medication=medication,
            icd10_codes=["J06.9"],
            icd10_classification="N",
            icd10_primary_indication="Viral URI",
            llm_extracted_indication=None,
            llm_classification=None,
            final_classification="N",
            classification_source="icd10",
            status="pending",
        )

        # Save
        saved_id = temp_db.save_candidate(candidate)
        assert saved_id == "cand-456"

        # Retrieve
        retrieved = temp_db.get_candidate("cand-456")
        assert retrieved is not None
        assert retrieved.medication.medication_name == "Vancomycin"
        assert retrieved.icd10_classification == "N"

    def test_save_review(self, temp_db):
        """Test saving a review."""
        # First create a candidate
        patient = Patient(fhir_id="pat-789", mrn="MRN003", name="Test 3")
        medication = MedicationOrder(
            fhir_id="med-789",
            patient_id="pat-789",
            medication_name="Meropenem",
            start_date=datetime.now(),
        )
        candidate = IndicationCandidate(
            id="cand-789",
            patient=patient,
            medication=medication,
            icd10_codes=[],
            icd10_classification="N",
            icd10_primary_indication=None,
            llm_extracted_indication=None,
            llm_classification=None,
            final_classification="N",
            classification_source="icd10",
            status="alerted",
        )
        temp_db.save_candidate(candidate)

        # Save review
        review_id = temp_db.save_review(
            candidate_id="cand-789",
            reviewer="pharmacist@hospital.org",
            decision="override_to_a",
            is_override=True,
            override_reason="Sepsis not coded yet",
            notes="Patient clinically septic, waiting for cultures",
        )

        assert review_id is not None

        # Check candidate status updated
        updated = temp_db.get_candidate("cand-789")
        assert updated.status == "reviewed"

    def test_override_stats(self, temp_db):
        """Test getting override statistics."""
        stats = temp_db.get_override_stats(days=30)

        assert "total_reviews" in stats
        assert "total_overrides" in stats
        assert "override_rate" in stats


class TestIndicationAssessment:
    """Test IndicationAssessment creation."""

    def test_assessment_requires_alert_for_n(self):
        """Test that N classification requires alert."""
        patient = Patient(fhir_id="p1", mrn="M1", name="P1")
        medication = MedicationOrder(
            fhir_id="m1",
            patient_id="p1",
            medication_name="Ceftriaxone",
            start_date=datetime.now(),
        )
        candidate = IndicationCandidate(
            id="c1",
            patient=patient,
            medication=medication,
            icd10_codes=[],
            icd10_classification="N",
            icd10_primary_indication=None,
            llm_extracted_indication=None,
            llm_classification=None,
            final_classification="N",
            classification_source="icd10",
            status="pending",
        )

        assessment = IndicationAssessment(
            candidate=candidate,
            requires_alert=candidate.final_classification == "N",
            recommendation="No documented indication",
            severity=AlertSeverity.WARNING,
        )

        assert assessment.requires_alert is True

    def test_assessment_no_alert_for_a(self):
        """Test that A classification does not require alert."""
        patient = Patient(fhir_id="p2", mrn="M2", name="P2")
        medication = MedicationOrder(
            fhir_id="m2",
            patient_id="p2",
            medication_name="Ceftriaxone",
            start_date=datetime.now(),
        )
        candidate = IndicationCandidate(
            id="c2",
            patient=patient,
            medication=medication,
            icd10_codes=["J18.9"],
            icd10_classification="A",
            icd10_primary_indication="Pneumonia",
            llm_extracted_indication=None,
            llm_classification=None,
            final_classification="A",
            classification_source="icd10",
            status="pending",
        )

        assessment = IndicationAssessment(
            candidate=candidate,
            requires_alert=candidate.final_classification == "N",
            recommendation="Indicated for pneumonia",
            severity=AlertSeverity.INFO,
        )

        assert assessment.requires_alert is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
