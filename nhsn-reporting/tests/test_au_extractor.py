"""Tests for AU (Antibiotic Usage) data extractor."""

import pytest
import tempfile
import os
from datetime import date
from pathlib import Path

import pandas as pd


class TestAUDataExtractor:
    """Tests for AUDataExtractor class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary SQLite database with test data."""
        import sqlite3

        # Create temp file
        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Create tables
        cursor.executescript("""
            CREATE TABLE PATIENT (
                PAT_ID INTEGER PRIMARY KEY,
                PAT_MRN_ID TEXT UNIQUE NOT NULL,
                PAT_NAME TEXT
            );

            CREATE TABLE PAT_ENC (
                PAT_ENC_CSN_ID INTEGER PRIMARY KEY,
                PAT_ID INTEGER,
                DEPARTMENT_ID INTEGER,
                HOSP_ADMIT_DTTM DATETIME,
                HOSP_DISCH_DTTM DATETIME
            );

            CREATE TABLE NHSN_LOCATION_MAP (
                EPIC_DEPT_ID INTEGER PRIMARY KEY,
                NHSN_LOCATION_CODE TEXT NOT NULL,
                LOCATION_DESCRIPTION TEXT
            );

            CREATE TABLE RX_MED_ONE (
                MEDICATION_ID INTEGER PRIMARY KEY,
                GENERIC_NAME TEXT,
                BRAND_NAME TEXT
            );

            CREATE TABLE NHSN_ANTIMICROBIAL_MAP (
                MEDICATION_ID INTEGER PRIMARY KEY,
                NHSN_CODE TEXT,
                NHSN_CATEGORY TEXT,
                DDD REAL,
                DDD_UNIT TEXT
            );

            CREATE TABLE ORDER_MED (
                ORDER_MED_ID INTEGER PRIMARY KEY,
                PAT_ENC_CSN_ID INTEGER,
                MEDICATION_ID INTEGER,
                ADMIN_ROUTE TEXT
            );

            CREATE TABLE MAR_ADMIN_INFO (
                MAR_ADMIN_INFO_ID INTEGER PRIMARY KEY,
                ORDER_MED_ID INTEGER,
                TAKEN_TIME DATETIME,
                ACTION_NAME TEXT,
                DOSE_GIVEN REAL,
                DOSE_UNIT TEXT
            );
        """)

        # Insert test data
        # Patients
        cursor.execute("INSERT INTO PATIENT VALUES (1, 'MRN001', 'Test Patient 1')")
        cursor.execute("INSERT INTO PATIENT VALUES (2, 'MRN002', 'Test Patient 2')")
        cursor.execute("INSERT INTO PATIENT VALUES (3, 'MRN003', 'Test Patient 3')")

        # Encounters
        cursor.execute(
            "INSERT INTO PAT_ENC VALUES (101, 1, 10, '2026-01-01', '2026-01-10')"
        )
        cursor.execute(
            "INSERT INTO PAT_ENC VALUES (102, 2, 10, '2026-01-05', '2026-01-15')"
        )
        cursor.execute(
            "INSERT INTO PAT_ENC VALUES (103, 3, 20, '2026-01-08', '2026-01-20')"
        )

        # Location mapping
        cursor.execute("INSERT INTO NHSN_LOCATION_MAP VALUES (10, 'ICU-A', 'ICU Unit A')")
        cursor.execute(
            "INSERT INTO NHSN_LOCATION_MAP VALUES (20, 'WARD-B', 'Medical Ward B')"
        )

        # Medications
        cursor.execute("INSERT INTO RX_MED_ONE VALUES (1, 'vancomycin', 'Vancocin')")
        cursor.execute("INSERT INTO RX_MED_ONE VALUES (2, 'piperacillin-tazobactam', 'Zosyn')")
        cursor.execute("INSERT INTO RX_MED_ONE VALUES (3, 'ceftriaxone', 'Rocephin')")

        # NHSN antimicrobial mapping
        cursor.execute(
            "INSERT INTO NHSN_ANTIMICROBIAL_MAP VALUES (1, 'VAN', 'Glycopeptides', 2.0, 'g')"
        )
        cursor.execute(
            "INSERT INTO NHSN_ANTIMICROBIAL_MAP VALUES (2, 'TZP', 'BL/BLI', 13.5, 'g')"
        )
        cursor.execute(
            "INSERT INTO NHSN_ANTIMICROBIAL_MAP VALUES (3, 'CRO', 'Cephalosporins-3rd', 2.0, 'g')"
        )

        # Medication orders
        cursor.execute("INSERT INTO ORDER_MED VALUES (1001, 101, 1, 'IV')")  # Patient 1, Vancomycin
        cursor.execute("INSERT INTO ORDER_MED VALUES (1002, 101, 2, 'IV')")  # Patient 1, Zosyn
        cursor.execute("INSERT INTO ORDER_MED VALUES (1003, 102, 1, 'IV')")  # Patient 2, Vancomycin
        cursor.execute("INSERT INTO ORDER_MED VALUES (1004, 103, 3, 'IV')")  # Patient 3, Ceftriaxone

        # MAR administrations
        # Patient 1: Vancomycin 3 days (Jan 2, 3, 4)
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (1, 1001, '2026-01-02 08:00', 'Given', 1.0, 'g')"
        )
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (2, 1001, '2026-01-02 20:00', 'Given', 1.0, 'g')"
        )
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (3, 1001, '2026-01-03 08:00', 'Given', 1.0, 'g')"
        )
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (4, 1001, '2026-01-04 08:00', 'Given', 1.0, 'g')"
        )

        # Patient 1: Zosyn 2 days (Jan 3, 4)
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (5, 1002, '2026-01-03 09:00', 'Given', 4.5, 'g')"
        )
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (6, 1002, '2026-01-04 09:00', 'Given', 4.5, 'g')"
        )

        # Patient 2: Vancomycin 1 day (Jan 6)
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (7, 1003, '2026-01-06 10:00', 'Given', 1.5, 'g')"
        )

        # Patient 3: Ceftriaxone 2 days (Jan 10, 11) - different location
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (8, 1004, '2026-01-10 07:00', 'Given', 2.0, 'g')"
        )
        cursor.execute(
            "INSERT INTO MAR_ADMIN_INFO VALUES (9, 1004, '2026-01-11 07:00', 'Given', 2.0, 'g')"
        )

        conn.commit()
        conn.close()

        yield db_path

        # Cleanup
        os.unlink(db_path)

    @pytest.fixture
    def extractor(self, temp_db):
        """Create extractor with temp database."""
        from src.data.au_extractor import AUDataExtractor

        return AUDataExtractor(f"sqlite:///{temp_db}")

    def test_get_antimicrobial_administrations(self, extractor):
        """Test raw administration data retrieval."""
        df = extractor.get_antimicrobial_administrations(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert not df.empty
        assert len(df) == 9  # Total administrations
        assert "patient_id" in df.columns
        assert "nhsn_code" in df.columns
        assert "admin_date" in df.columns

    def test_get_administrations_location_filter(self, extractor):
        """Test filtering by location."""
        df = extractor.get_antimicrobial_administrations(
            locations=["ICU-A"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert not df.empty
        assert all(df["nhsn_location_code"] == "ICU-A")
        # Should only have patients 1 and 2 (7 administrations)
        assert len(df) == 7

    def test_calculate_dot(self, extractor):
        """Test DOT calculation."""
        df = extractor.calculate_dot(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert not df.empty
        assert "days_of_therapy" in df.columns

        # Check specific DOT values
        # Vancomycin in ICU-A: Patient 1 (3 days) + Patient 2 (1 day) = 4 DOT
        van_icu = df[(df["nhsn_code"] == "VAN") & (df["nhsn_location_code"] == "ICU-A")]
        assert len(van_icu) == 1
        assert van_icu.iloc[0]["days_of_therapy"] == 4

        # Zosyn in ICU-A: Patient 1 only, 2 days
        tzp_icu = df[(df["nhsn_code"] == "TZP") & (df["nhsn_location_code"] == "ICU-A")]
        assert len(tzp_icu) == 1
        assert tzp_icu.iloc[0]["days_of_therapy"] == 2

        # Ceftriaxone in WARD-B: Patient 3 only, 2 days
        cro_ward = df[(df["nhsn_code"] == "CRO") & (df["nhsn_location_code"] == "WARD-B")]
        assert len(cro_ward) == 1
        assert cro_ward.iloc[0]["days_of_therapy"] == 2

    def test_calculate_ddd(self, extractor):
        """Test DDD calculation."""
        df = extractor.calculate_ddd(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert not df.empty
        assert "defined_daily_doses" in df.columns
        assert "total_grams" in df.columns

        # Vancomycin in ICU-A: 4g (patient 1) + 1.5g (patient 2) = 5.5g
        # DDD for vancomycin is 2g, so DDD = 5.5 / 2 = 2.75
        van_icu = df[(df["nhsn_code"] == "VAN") & (df["nhsn_location_code"] == "ICU-A")]
        assert len(van_icu) == 1
        assert van_icu.iloc[0]["total_grams"] == pytest.approx(5.5, rel=0.01)
        assert van_icu.iloc[0]["defined_daily_doses"] == pytest.approx(2.75, rel=0.01)

    def test_get_monthly_summary(self, extractor):
        """Test monthly summary generation."""
        summary = extractor.get_monthly_summary(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert "date_range" in summary
        assert "locations" in summary
        assert "overall_totals" in summary

        # Check overall totals
        assert summary["overall_totals"]["total_dot"] == 8  # 4 + 2 + 2

        # Check we have both locations
        location_codes = [loc["nhsn_location_code"] for loc in summary["locations"]]
        assert "ICU-A" in location_codes
        assert "WARD-B" in location_codes

    def test_export_for_nhsn(self, extractor):
        """Test NHSN export format."""
        df = extractor.export_for_nhsn(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert not df.empty

        # Check required NHSN columns
        required_columns = [
            "orgID",
            "locationCode",
            "summaryYM",
            "antimicrobialCode",
            "daysOfTherapy",
        ]
        for col in required_columns:
            assert col in df.columns

        # Check month format (YYYYMM)
        assert df.iloc[0]["summaryYM"] == "202601"

    def test_empty_results(self, extractor):
        """Test handling of date range with no data."""
        df = extractor.calculate_dot(
            start_date=date(2025, 1, 1),  # No data in 2025
            end_date=date(2025, 1, 31),
        )

        assert df.empty

    def test_get_usage_by_category(self, extractor):
        """Test usage aggregation by antimicrobial category."""
        df = extractor.get_usage_by_category(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert not df.empty
        assert "nhsn_category" in df.columns
        assert "total_dot" in df.columns

        # Check Glycopeptides category (vancomycin)
        glyco = df[df["nhsn_category"] == "Glycopeptides"]
        assert len(glyco) > 0


class TestAUDataExtractorEdgeCases:
    """Edge case tests for AU extractor."""

    @pytest.fixture
    def minimal_db(self):
        """Create minimal database for edge case testing."""
        import sqlite3

        fd, db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)

        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        cursor.executescript("""
            CREATE TABLE PATIENT (
                PAT_ID INTEGER PRIMARY KEY,
                PAT_MRN_ID TEXT UNIQUE NOT NULL
            );
            CREATE TABLE PAT_ENC (
                PAT_ENC_CSN_ID INTEGER PRIMARY KEY,
                PAT_ID INTEGER,
                DEPARTMENT_ID INTEGER
            );
            CREATE TABLE NHSN_LOCATION_MAP (
                EPIC_DEPT_ID INTEGER PRIMARY KEY,
                NHSN_LOCATION_CODE TEXT NOT NULL
            );
            CREATE TABLE RX_MED_ONE (
                MEDICATION_ID INTEGER PRIMARY KEY,
                GENERIC_NAME TEXT
            );
            CREATE TABLE NHSN_ANTIMICROBIAL_MAP (
                MEDICATION_ID INTEGER PRIMARY KEY,
                NHSN_CODE TEXT,
                NHSN_CATEGORY TEXT,
                DDD REAL,
                DDD_UNIT TEXT
            );
            CREATE TABLE ORDER_MED (
                ORDER_MED_ID INTEGER PRIMARY KEY,
                PAT_ENC_CSN_ID INTEGER,
                MEDICATION_ID INTEGER,
                ADMIN_ROUTE TEXT
            );
            CREATE TABLE MAR_ADMIN_INFO (
                MAR_ADMIN_INFO_ID INTEGER PRIMARY KEY,
                ORDER_MED_ID INTEGER,
                TAKEN_TIME DATETIME,
                ACTION_NAME TEXT,
                DOSE_GIVEN REAL,
                DOSE_UNIT TEXT
            );
        """)

        conn.commit()
        conn.close()

        yield db_path
        os.unlink(db_path)

    def test_empty_database(self, minimal_db):
        """Test with completely empty tables."""
        from src.data.au_extractor import AUDataExtractor

        extractor = AUDataExtractor(f"sqlite:///{minimal_db}")
        df = extractor.calculate_dot(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        assert df.empty

    def test_monthly_summary_empty(self, minimal_db):
        """Test monthly summary with no data."""
        from src.data.au_extractor import AUDataExtractor

        extractor = AUDataExtractor(f"sqlite:///{minimal_db}")
        summary = extractor.get_monthly_summary(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert summary["locations"] == []
        assert summary["overall_totals"]["total_dot"] == 0
