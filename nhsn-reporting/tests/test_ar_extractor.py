"""Tests for AR (Antimicrobial Resistance) data extractor."""

import pytest
import tempfile
import os
from datetime import date

import pandas as pd


class TestARDataExtractor:
    """Tests for ARDataExtractor class."""

    @pytest.fixture
    def temp_db(self):
        """Create a temporary SQLite database with test data."""
        import sqlite3

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

            CREATE TABLE CULTURE_RESULTS (
                CULTURE_ID INTEGER PRIMARY KEY,
                PAT_ID INTEGER,
                PAT_ENC_CSN_ID INTEGER,
                SPECIMEN_TAKEN_TIME DATETIME,
                SPECIMEN_TYPE TEXT,
                SPECIMEN_SOURCE TEXT,
                CULTURE_STATUS TEXT
            );

            CREATE TABLE CULTURE_ORGANISM (
                CULTURE_ORGANISM_ID INTEGER PRIMARY KEY,
                CULTURE_ID INTEGER,
                ORGANISM_NAME TEXT,
                ORGANISM_GROUP TEXT,
                CFU_COUNT TEXT,
                IS_PRIMARY INTEGER
            );

            CREATE TABLE SUSCEPTIBILITY_RESULTS (
                SUSCEPTIBILITY_ID INTEGER PRIMARY KEY,
                CULTURE_ORGANISM_ID INTEGER,
                ANTIBIOTIC TEXT,
                ANTIBIOTIC_CODE TEXT,
                MIC REAL,
                MIC_UNITS TEXT,
                INTERPRETATION TEXT,
                METHOD TEXT
            );

            CREATE TABLE NHSN_PHENOTYPE_MAP (
                PHENOTYPE_CODE TEXT PRIMARY KEY,
                PHENOTYPE_NAME TEXT,
                ORGANISM_PATTERN TEXT,
                RESISTANCE_PATTERN TEXT
            );
        """)

        # Insert test data
        # Patients
        cursor.execute("INSERT INTO PATIENT VALUES (1, 'MRN001', 'Test Patient 1')")
        cursor.execute("INSERT INTO PATIENT VALUES (2, 'MRN002', 'Test Patient 2')")
        cursor.execute("INSERT INTO PATIENT VALUES (3, 'MRN003', 'Test Patient 3')")

        # Encounters
        cursor.execute(
            "INSERT INTO PAT_ENC VALUES (101, 1, 10, '2026-01-01', '2026-01-15')"
        )
        cursor.execute(
            "INSERT INTO PAT_ENC VALUES (102, 2, 10, '2026-01-05', '2026-01-20')"
        )
        cursor.execute(
            "INSERT INTO PAT_ENC VALUES (103, 3, 20, '2026-01-10', '2026-01-25')"
        )

        # Location mapping
        cursor.execute("INSERT INTO NHSN_LOCATION_MAP VALUES (10, 'ICU-A', 'ICU Unit A')")
        cursor.execute(
            "INSERT INTO NHSN_LOCATION_MAP VALUES (20, 'WARD-B', 'Medical Ward B')"
        )

        # Culture results
        # Patient 1: Blood culture with Staph aureus (MRSA)
        cursor.execute(
            "INSERT INTO CULTURE_RESULTS VALUES (1, 1, 101, '2026-01-05 10:00', 'Blood', 'Peripheral', 'Positive')"
        )
        # Patient 1: Second blood culture same organism (should be excluded by first-isolate rule)
        cursor.execute(
            "INSERT INTO CULTURE_RESULTS VALUES (2, 1, 101, '2026-01-08 10:00', 'Blood', 'Peripheral', 'Positive')"
        )
        # Patient 2: Blood culture with E. coli
        cursor.execute(
            "INSERT INTO CULTURE_RESULTS VALUES (3, 2, 102, '2026-01-10 14:00', 'Blood', 'Central Line', 'Positive')"
        )
        # Patient 3: Urine culture with E. coli (different location)
        cursor.execute(
            "INSERT INTO CULTURE_RESULTS VALUES (4, 3, 103, '2026-01-15 08:00', 'Urine', 'Clean Catch', 'Positive')"
        )
        # Patient 3: Blood culture with Klebsiella
        cursor.execute(
            "INSERT INTO CULTURE_RESULTS VALUES (5, 3, 103, '2026-01-16 09:00', 'Blood', 'Peripheral', 'Positive')"
        )

        # Culture organisms
        cursor.execute(
            "INSERT INTO CULTURE_ORGANISM VALUES (1, 1, 'Staphylococcus aureus', 'Gram Positive Cocci', '>100000', 1)"
        )
        cursor.execute(
            "INSERT INTO CULTURE_ORGANISM VALUES (2, 2, 'Staphylococcus aureus', 'Gram Positive Cocci', '>100000', 1)"
        )
        cursor.execute(
            "INSERT INTO CULTURE_ORGANISM VALUES (3, 3, 'Escherichia coli', 'Gram Negative Bacilli', '>100000', 1)"
        )
        cursor.execute(
            "INSERT INTO CULTURE_ORGANISM VALUES (4, 4, 'Escherichia coli', 'Gram Negative Bacilli', '>100000', 1)"
        )
        cursor.execute(
            "INSERT INTO CULTURE_ORGANISM VALUES (5, 5, 'Klebsiella pneumoniae', 'Gram Negative Bacilli', '>100000', 1)"
        )

        # Susceptibility results
        # Staph aureus - MRSA (oxacillin resistant)
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (1, 1, 'Oxacillin', 'OXA', 4.0, 'mcg/mL', 'R', 'MIC')"
        )
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (2, 1, 'Vancomycin', 'VAN', 1.0, 'mcg/mL', 'S', 'MIC')"
        )
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (3, 2, 'Oxacillin', 'OXA', 4.0, 'mcg/mL', 'R', 'MIC')"
        )
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (4, 2, 'Vancomycin', 'VAN', 1.0, 'mcg/mL', 'S', 'MIC')"
        )

        # E. coli - susceptible
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (5, 3, 'Ceftriaxone', 'CRO', 0.5, 'mcg/mL', 'S', 'MIC')"
        )
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (6, 3, 'Meropenem', 'MEM', 0.25, 'mcg/mL', 'S', 'MIC')"
        )
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (7, 4, 'Ceftriaxone', 'CRO', 0.5, 'mcg/mL', 'S', 'MIC')"
        )
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (8, 4, 'Meropenem', 'MEM', 0.25, 'mcg/mL', 'S', 'MIC')"
        )

        # Klebsiella - CRE (carbapenem resistant)
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (9, 5, 'Ceftriaxone', 'CRO', 64.0, 'mcg/mL', 'R', 'MIC')"
        )
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (10, 5, 'Meropenem', 'MEM', 8.0, 'mcg/mL', 'R', 'MIC')"
        )
        cursor.execute(
            "INSERT INTO SUSCEPTIBILITY_RESULTS VALUES (11, 5, 'Ertapenem', 'ETP', 4.0, 'mcg/mL', 'R', 'MIC')"
        )

        # Phenotype definitions
        cursor.execute(
            "INSERT INTO NHSN_PHENOTYPE_MAP VALUES ('MRSA', 'Methicillin-resistant Staphylococcus aureus', 'Staphylococcus aureus', 'OXA:R')"
        )
        cursor.execute(
            "INSERT INTO NHSN_PHENOTYPE_MAP VALUES ('CRE', 'Carbapenem-resistant Enterobacterales', 'Escherichia%|Klebsiella%', 'MEM:R|ETP:R')"
        )
        cursor.execute(
            "INSERT INTO NHSN_PHENOTYPE_MAP VALUES ('VRE', 'Vancomycin-resistant Enterococcus', 'Enterococcus%', 'VAN:R')"
        )

        conn.commit()
        conn.close()

        yield db_path

        # Cleanup
        os.unlink(db_path)

    @pytest.fixture
    def extractor(self, temp_db):
        """Create extractor with temp database."""
        from nhsn_src.data.ar_extractor import ARDataExtractor

        return ARDataExtractor(f"sqlite:///{temp_db}")

    def test_get_culture_results(self, extractor):
        """Test culture results retrieval."""
        df = extractor.get_culture_results(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert not df.empty
        assert len(df) == 5  # 5 total culture organisms
        assert "isolate_id" in df.columns
        assert "organism_name" in df.columns
        assert "specimen_type" in df.columns

    def test_get_culture_results_location_filter(self, extractor):
        """Test filtering cultures by location."""
        df = extractor.get_culture_results(
            locations=["ICU-A"],
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        assert not df.empty
        assert all(df["nhsn_location_code"] == "ICU-A")

    def test_get_culture_results_specimen_filter(self, extractor):
        """Test filtering by specimen type."""
        df = extractor.get_culture_results(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
            specimen_types=["Blood"],
        )

        assert not df.empty
        assert all(df["specimen_type"] == "Blood")
        # Should have 4 blood cultures (2 staph, 1 e.coli, 1 klebsiella)
        assert len(df) == 4

    def test_get_susceptibility_results(self, extractor):
        """Test susceptibility results retrieval."""
        df = extractor.get_susceptibility_results()

        assert not df.empty
        assert "isolate_id" in df.columns
        assert "antibiotic" in df.columns
        assert "interpretation" in df.columns

    def test_apply_first_isolate_rule(self, extractor):
        """Test first-isolate deduplication."""
        # Get all cultures
        cultures_df = extractor.get_culture_results(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )

        # Apply first-isolate rule
        first_isolates = extractor.apply_first_isolate_rule(cultures_df)

        # Should exclude the duplicate Staph aureus from patient 1
        assert len(first_isolates) == 4  # 5 - 1 duplicate = 4

        # Verify only first staph aureus from patient 1 is included
        staph = first_isolates[first_isolates["organism_name"] == "Staphylococcus aureus"]
        assert len(staph) == 1
        assert staph.iloc[0]["patient_id"] == "MRN001"

    def test_calculate_resistance_rates(self, extractor):
        """Test resistance rate calculations."""
        df = extractor.calculate_resistance_rates(
            year=2026,
            quarter=1,
        )

        assert not df.empty
        assert "percent_resistant" in df.columns
        assert "percent_non_susceptible" in df.columns

        # Check MRSA rate for Staph aureus + Oxacillin
        # Only 1 first-isolate Staph aureus, and it's resistant
        staph_oxa = df[
            (df["organism_name"] == "Staphylococcus aureus")
            & (df["antibiotic"] == "Oxacillin")
        ]
        if not staph_oxa.empty:
            assert staph_oxa.iloc[0]["percent_resistant"] == 100.0

    def test_calculate_phenotypes(self, extractor):
        """Test resistance phenotype calculations."""
        df = extractor.calculate_phenotypes(
            year=2026,
            quarter=1,
        )

        assert not df.empty
        assert "phenotype_code" in df.columns
        assert "percent_positive" in df.columns

        # Check MRSA phenotype
        mrsa = df[df["phenotype_code"] == "MRSA"]
        assert len(mrsa) > 0
        # 1 Staph aureus first-isolate, and it's MRSA
        assert mrsa.iloc[0]["percent_positive"] == 100.0

        # Check CRE phenotype - calculated per location, not globally
        cre = df[df["phenotype_code"] == "CRE"]
        assert len(cre) > 0
        # ICU-A: 1 E. coli (susceptible) = 0% CRE
        # WARD-B: 1 E. coli (susceptible) + 1 Klebsiella (CRE) = 50% CRE
        cre_ward = cre[cre["nhsn_location_code"] == "WARD-B"]
        assert len(cre_ward) == 1
        assert cre_ward.iloc[0]["percent_positive"] == 50.0

    def test_get_quarterly_summary(self, extractor):
        """Test quarterly summary generation."""
        summary = extractor.get_quarterly_summary(
            year=2026,
            quarter=1,
        )

        assert "period" in summary
        assert "overall_totals" in summary
        assert "locations" in summary
        assert "phenotypes" in summary

        assert summary["period"]["year"] == 2026
        assert summary["period"]["quarter"] == 1
        assert summary["period"]["quarter_string"] == "2026-Q1"

        # Check total first isolates (after dedup)
        assert summary["overall_totals"]["first_isolates"] == 4

    def test_export_for_nhsn(self, extractor):
        """Test NHSN export format."""
        result = extractor.export_for_nhsn(
            year=2026,
            quarter=1,
        )

        assert "isolates" in result
        assert "susceptibilities" in result

        isolates_df = result["isolates"]
        suscept_df = result["susceptibilities"]

        assert not isolates_df.empty
        assert not suscept_df.empty

        # Check required NHSN columns
        assert "orgID" in isolates_df.columns
        assert "locationCode" in isolates_df.columns
        assert "specimenType" in isolates_df.columns
        assert "organismName" in isolates_df.columns

    def test_quarter_dates_calculation(self, extractor):
        """Test quarter date calculations."""
        # Q1
        start, end = extractor._get_quarter_dates(2026, 1)
        assert start == date(2026, 1, 1)
        assert end == date(2026, 3, 31)

        # Q2
        start, end = extractor._get_quarter_dates(2026, 2)
        assert start == date(2026, 4, 1)
        assert end == date(2026, 6, 30)

        # Q3
        start, end = extractor._get_quarter_dates(2026, 3)
        assert start == date(2026, 7, 1)
        assert end == date(2026, 9, 30)

        # Q4
        start, end = extractor._get_quarter_dates(2026, 4)
        assert start == date(2026, 10, 1)
        assert end == date(2026, 12, 31)


class TestARPhenotypeMatching:
    """Tests for phenotype matching logic."""

    @pytest.fixture
    def extractor(self):
        """Create extractor for testing (no DB needed for these tests)."""
        from nhsn_src.data.ar_extractor import ARDataExtractor

        return ARDataExtractor("sqlite:///:memory:")

    def test_check_phenotype_match_simple(self, extractor):
        """Test simple phenotype matching."""
        suscept_df = pd.DataFrame({
            "isolate_id": [1, 1],
            "antibiotic": ["Oxacillin", "Vancomycin"],
            "antibiotic_code": ["OXA", "VAN"],
            "interpretation": ["R", "S"],
        })

        # MRSA: Staph aureus + OXA:R
        result = extractor._check_phenotype_match(
            organism_name="Staphylococcus aureus",
            susceptibilities=suscept_df,
            organism_pattern="Staphylococcus aureus",
            resistance_pattern="OXA:R",
        )
        assert result is True

    def test_check_phenotype_match_or_condition(self, extractor):
        """Test phenotype matching with OR conditions."""
        suscept_df = pd.DataFrame({
            "isolate_id": [1, 1],
            "antibiotic": ["Meropenem", "Ertapenem"],
            "antibiotic_code": ["MEM", "ETP"],
            "interpretation": ["S", "R"],  # Only ETP resistant
        })

        # CRE: MEM:R OR ETP:R - should match because ETP:R
        result = extractor._check_phenotype_match(
            organism_name="Klebsiella pneumoniae",
            susceptibilities=suscept_df,
            organism_pattern="Klebsiella%",
            resistance_pattern="MEM:R|ETP:R",
        )
        assert result is True

    def test_check_phenotype_match_no_match(self, extractor):
        """Test phenotype non-matching."""
        suscept_df = pd.DataFrame({
            "isolate_id": [1, 1],
            "antibiotic": ["Oxacillin", "Vancomycin"],
            "antibiotic_code": ["OXA", "VAN"],
            "interpretation": ["S", "S"],  # All susceptible
        })

        # MRSA: Staph aureus + OXA:R - should NOT match
        result = extractor._check_phenotype_match(
            organism_name="Staphylococcus aureus",
            susceptibilities=suscept_df,
            organism_pattern="Staphylococcus aureus",
            resistance_pattern="OXA:R",
        )
        assert result is False

    def test_check_phenotype_match_organism_pattern(self, extractor):
        """Test organism pattern matching."""
        suscept_df = pd.DataFrame({
            "isolate_id": [1],
            "antibiotic": ["Meropenem"],
            "antibiotic_code": ["MEM"],
            "interpretation": ["R"],
        })

        # CRE with E. coli (should match Escherichia% pattern)
        result = extractor._check_phenotype_match(
            organism_name="Escherichia coli",
            susceptibilities=suscept_df,
            organism_pattern="Escherichia%|Klebsiella%",
            resistance_pattern="MEM:R",
        )
        assert result is True

        # Non-Enterobacterales should NOT match
        result = extractor._check_phenotype_match(
            organism_name="Pseudomonas aeruginosa",
            susceptibilities=suscept_df,
            organism_pattern="Escherichia%|Klebsiella%",
            resistance_pattern="MEM:R",
        )
        assert result is False


class TestARDataExtractorEdgeCases:
    """Edge case tests for AR extractor."""

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
            CREATE TABLE CULTURE_RESULTS (
                CULTURE_ID INTEGER PRIMARY KEY,
                PAT_ID INTEGER,
                PAT_ENC_CSN_ID INTEGER,
                SPECIMEN_TAKEN_TIME DATETIME,
                SPECIMEN_TYPE TEXT,
                SPECIMEN_SOURCE TEXT,
                CULTURE_STATUS TEXT
            );
            CREATE TABLE CULTURE_ORGANISM (
                CULTURE_ORGANISM_ID INTEGER PRIMARY KEY,
                CULTURE_ID INTEGER,
                ORGANISM_NAME TEXT,
                ORGANISM_GROUP TEXT,
                CFU_COUNT TEXT,
                IS_PRIMARY INTEGER
            );
            CREATE TABLE SUSCEPTIBILITY_RESULTS (
                SUSCEPTIBILITY_ID INTEGER PRIMARY KEY,
                CULTURE_ORGANISM_ID INTEGER,
                ANTIBIOTIC TEXT,
                ANTIBIOTIC_CODE TEXT,
                MIC REAL,
                MIC_UNITS TEXT,
                INTERPRETATION TEXT,
                METHOD TEXT
            );
            CREATE TABLE NHSN_PHENOTYPE_MAP (
                PHENOTYPE_CODE TEXT PRIMARY KEY,
                PHENOTYPE_NAME TEXT,
                ORGANISM_PATTERN TEXT,
                RESISTANCE_PATTERN TEXT
            );
        """)

        conn.commit()
        conn.close()

        yield db_path
        os.unlink(db_path)

    def test_empty_database(self, minimal_db):
        """Test with completely empty tables."""
        from nhsn_src.data.ar_extractor import ARDataExtractor

        extractor = ARDataExtractor(f"sqlite:///{minimal_db}")
        df = extractor.get_culture_results(
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 31),
        )
        assert df.empty

    def test_quarterly_summary_empty(self, minimal_db):
        """Test quarterly summary with no data."""
        from nhsn_src.data.ar_extractor import ARDataExtractor

        extractor = ARDataExtractor(f"sqlite:///{minimal_db}")
        summary = extractor.get_quarterly_summary(
            year=2026,
            quarter=1,
        )

        assert summary["overall_totals"]["total_cultures"] == 0
        assert summary["overall_totals"]["first_isolates"] == 0
        assert summary["locations"] == []

    def test_export_for_nhsn_empty(self, minimal_db):
        """Test NHSN export with no data."""
        from nhsn_src.data.ar_extractor import ARDataExtractor

        extractor = ARDataExtractor(f"sqlite:///{minimal_db}")
        result = extractor.export_for_nhsn(
            year=2026,
            quarter=1,
        )

        assert result["isolates"].empty
        assert result["susceptibilities"].empty
