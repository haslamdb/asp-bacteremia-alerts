#!/usr/bin/env python3
"""Test mock Clarity database integration.

This script tests the mock Clarity database setup and data retrieval
to ensure the hybrid FHIR/Clarity architecture works correctly.

Usage:
    python scripts/test_mock_clarity.py
    python scripts/test_mock_clarity.py --generate  # Generate data first
    python scripts/test_mock_clarity.py --verbose
"""

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import Config


def test_config():
    """Test configuration is set up correctly."""
    print("\n" + "=" * 60)
    print("Testing Configuration")
    print("=" * 60)

    print(f"MOCK_CLARITY_DB_PATH: {Config.MOCK_CLARITY_DB_PATH}")
    print(f"Mock DB exists: {Path(Config.MOCK_CLARITY_DB_PATH).exists()}")

    conn_str = Config.get_clarity_connection_string()
    print(f"Connection string: {conn_str}")
    print(f"Clarity configured: {Config.is_clarity_configured()}")

    if not Config.is_clarity_configured():
        print("\nWARNING: Clarity not configured. Run with --generate to create mock data.")
        return False

    return True


def test_notes_retrieval(verbose: bool = False):
    """Test clinical notes retrieval from mock Clarity."""
    print("\n" + "=" * 60)
    print("Testing Notes Retrieval")
    print("=" * 60)

    from src.data.clarity_source import ClarityNoteSource

    try:
        source = ClarityNoteSource()
        print(f"Connection string: {source.connection_string}")
        print(f"Is SQLite: {source._is_sqlite()}")

        # Get a patient MRN from the database
        from sqlalchemy import create_engine, text
        engine = create_engine(source.connection_string)
        with engine.connect() as conn:
            result = conn.execute(text("SELECT PAT_MRN_ID FROM PATIENT LIMIT 1"))
            row = result.fetchone()
            if not row:
                print("ERROR: No patients in database")
                return False
            patient_mrn = row[0]

        print(f"\nTesting with patient: {patient_mrn}")

        # Get notes for this patient
        start_date = datetime.now() - timedelta(days=90)
        end_date = datetime.now()

        notes = source.get_notes_for_patient(patient_mrn, start_date, end_date)
        print(f"Found {len(notes)} notes")

        if verbose and notes:
            for note in notes[:3]:  # Show first 3
                print(f"\n  Note ID: {note.id}")
                print(f"  Type: {note.note_type}")
                print(f"  Date: {note.date}")
                print(f"  Author: {note.author}")
                print(f"  Content preview: {note.content[:100]}...")

        return len(notes) > 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_device_retrieval(verbose: bool = False):
    """Test central line device retrieval from mock Clarity."""
    print("\n" + "=" * 60)
    print("Testing Device Retrieval")
    print("=" * 60)

    from src.data.clarity_source import ClarityDeviceSource

    try:
        source = ClarityDeviceSource()

        # Get a patient with a central line
        from sqlalchemy import create_engine, text
        engine = create_engine(source.connection_string)
        with engine.connect() as conn:
            # Find a patient with flowsheet entries
            result = conn.execute(text("""
                SELECT DISTINCT p.PAT_MRN_ID
                FROM PATIENT p
                JOIN PAT_ENC pe ON p.PAT_ID = pe.PAT_ID
                JOIN IP_FLWSHT_REC fr ON pe.INPATIENT_DATA_ID = fr.INPATIENT_DATA_ID
                LIMIT 1
            """))
            row = result.fetchone()
            if not row:
                print("WARNING: No patients with flowsheet data found")
                return True  # Not a failure, just no data
            patient_mrn = row[0]

        print(f"Testing with patient: {patient_mrn}")

        as_of_date = datetime.now()
        devices = source.get_central_lines(patient_mrn, as_of_date)
        print(f"Found {len(devices)} central lines")

        if verbose and devices:
            for dev in devices:
                print(f"\n  Type: {dev.device_type}")
                print(f"  Site: {dev.site}")
                print(f"  Insertion: {dev.insertion_date}")
                print(f"  Removal: {dev.removal_date}")

        return True  # May have 0 devices which is OK

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_culture_retrieval(verbose: bool = False):
    """Test blood culture retrieval from mock Clarity."""
    print("\n" + "=" * 60)
    print("Testing Culture Retrieval")
    print("=" * 60)

    from src.data.clarity_source import ClarityCultureSource

    try:
        source = ClarityCultureSource()

        start_date = datetime.now() - timedelta(days=90)
        end_date = datetime.now()

        cultures = source.get_positive_blood_cultures(start_date, end_date)
        print(f"Found {len(cultures)} positive blood cultures")

        if verbose and cultures:
            for patient, culture in cultures[:5]:  # Show first 5
                print(f"\n  Patient: {patient.mrn} - {patient.name}")
                print(f"  Organism: {culture.organism}")
                print(f"  Collection: {culture.collection_date}")
                print(f"  Result: {culture.result_date}")

        return len(cultures) > 0

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_denominator_calculation(verbose: bool = False):
    """Test denominator (line-days, patient-days) calculation."""
    print("\n" + "=" * 60)
    print("Testing Denominator Calculation")
    print("=" * 60)

    from src.data.denominator import DenominatorCalculator
    from datetime import date

    try:
        calc = DenominatorCalculator()

        # Test central line days
        start = date.today() - timedelta(days=90)
        end = date.today()

        print(f"\nDate range: {start} to {end}")

        line_days_df = calc.get_central_line_days(start_date=start, end_date=end)
        print(f"\nCentral Line Days:")
        if not line_days_df.empty:
            print(line_days_df.to_string(index=False))
        else:
            print("  No data")

        # Test patient days
        patient_days_df = calc.get_patient_days(start_date=start, end_date=end)
        print(f"\nPatient Days:")
        if not patient_days_df.empty:
            print(patient_days_df.to_string(index=False))
        else:
            print("  No data")

        # Test summary
        if verbose:
            summary = calc.get_denominator_summary(start_date=start, end_date=end)
            print(f"\nDenominator Summary:")
            import json
            print(json.dumps(summary, indent=2))

        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_hybrid_source_routing(verbose: bool = False):
    """Test that source routing works correctly."""
    print("\n" + "=" * 60)
    print("Testing Hybrid Source Routing")
    print("=" * 60)

    from src.data.factory import get_note_source, get_culture_source, get_device_source

    try:
        # Test with explicit source type
        print("\nTesting explicit 'clarity' source:")
        note_src = get_note_source("clarity")
        print(f"  Note source type: {type(note_src).__name__}")

        culture_src = get_culture_source("clarity")
        print(f"  Culture source type: {type(culture_src).__name__}")

        device_src = get_device_source("clarity")
        print(f"  Device source type: {type(device_src).__name__}")

        # Verify they're Clarity sources
        from src.data.clarity_source import ClarityNoteSource, ClarityCultureSource, ClarityDeviceSource
        assert isinstance(note_src, ClarityNoteSource), "Note source should be ClarityNoteSource"
        assert isinstance(culture_src, ClarityCultureSource), "Culture source should be ClarityCultureSource"
        assert isinstance(device_src, ClarityDeviceSource), "Device source should be ClarityDeviceSource"

        print("\nAll source routing tests passed!")
        return True

    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return False


def generate_test_data():
    """Generate mock data for testing."""
    print("\n" + "=" * 60)
    print("Generating Test Data")
    print("=" * 60)

    from mock_clarity.generate_data import MockClarityGenerator, DEFAULT_DB_PATH

    generator = MockClarityGenerator(DEFAULT_DB_PATH)
    generator.initialize_database()
    generator.generate_providers()

    print("\nGenerating random patients...")
    generator.generate_random_patients(30, months=3)

    print("\nGenerating CLABSI scenarios...")
    scenarios = generator.generate_all_scenarios()

    generator.load_to_database()

    print(f"\nTest data generated at: {DEFAULT_DB_PATH}")
    return True


def main():
    parser = argparse.ArgumentParser(
        description="Test mock Clarity database integration"
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Generate mock data before testing",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Show detailed output",
    )
    parser.add_argument(
        "--test",
        choices=["config", "notes", "devices", "cultures", "denominators", "routing", "all"],
        default="all",
        help="Run specific test (default: all)",
    )

    args = parser.parse_args()

    # Generate data if requested
    if args.generate:
        generate_test_data()

    # Run tests
    results = {}

    if args.test in ("config", "all"):
        results["config"] = test_config()
        if not results["config"] and args.test == "all":
            print("\nConfiguration not ready. Use --generate to create mock data.")
            sys.exit(1)

    if args.test in ("notes", "all"):
        results["notes"] = test_notes_retrieval(args.verbose)

    if args.test in ("devices", "all"):
        results["devices"] = test_device_retrieval(args.verbose)

    if args.test in ("cultures", "all"):
        results["cultures"] = test_culture_retrieval(args.verbose)

    if args.test in ("denominators", "all"):
        results["denominators"] = test_denominator_calculation(args.verbose)

    if args.test in ("routing", "all"):
        results["routing"] = test_hybrid_source_routing(args.verbose)

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    all_passed = True
    for test_name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  {test_name}: {status}")
        if not passed:
            all_passed = False

    if all_passed:
        print("\nAll tests passed!")
        sys.exit(0)
    else:
        print("\nSome tests failed.")
        sys.exit(1)


if __name__ == "__main__":
    main()
