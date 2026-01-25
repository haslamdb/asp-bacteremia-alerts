#!/usr/bin/env python3
"""Test script to compare LLM performance with/without keyword filtering.

This script creates a mock CLABSI candidate with 30 clinical notes (8 relevant,
22 irrelevant) with realistic lengths (2-3K chars each) and times the
classification process both with and without keyword filtering enabled.
"""

import logging
import time
from datetime import datetime, timedelta

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Reduce noise from other loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


def create_mock_clabsi_candidate():
    """Create a mock CLABSI candidate for testing."""
    from hai_src.models import (
        HAICandidate,
        HAIType,
        Patient,
        CultureResult,
        DeviceInfo,
        CandidateStatus,
    )
    import uuid

    patient = Patient(
        fhir_id="patient-demo-clabsi-001",
        mrn="DEMO-CLABSI-001",
        name="Demo Patient",
        birth_date=datetime(1979, 3, 22),
        location="7 ICU - Medical Intensive Care",
    )

    culture = CultureResult(
        fhir_id="culture-demo-clabsi-001",
        collection_date=datetime.now() - timedelta(days=2),
        organism="Staphylococcus epidermidis",
        is_positive=True,
    )

    device = DeviceInfo(
        device_type="triple_lumen_cvc",
        insertion_date=datetime.now() - timedelta(days=12),
        site="right_subclavian",
    )

    candidate = HAICandidate(
        id=str(uuid.uuid4()),
        hai_type=HAIType.CLABSI,
        patient=patient,
        culture=culture,
        device_info=device,
        device_days_at_culture=10,
        meets_initial_criteria=True,
        status=CandidateStatus.PENDING,
    )

    return candidate


def test_note_retrieval():
    """Test note retrieval with and without keyword filtering."""
    from hai_src.data.mock_notes import MockNoteSource
    from hai_src.notes.retriever import NoteRetriever, HAI_KEYWORDS
    from hai_src.models import HAIType

    print("\n" + "=" * 70)
    print("TEST 1: Note Retrieval and Filtering (CLABSI)")
    print("=" * 70)

    # Create mock note source with 30 notes
    mock_source = MockNoteSource(hai_type="clabsi", include_irrelevant=True, num_irrelevant=22)
    candidate = create_mock_clabsi_candidate()

    # Get all notes (no filtering)
    all_notes = mock_source.get_notes_for_patient(
        patient_id=candidate.patient.fhir_id,
        start_date=datetime.now() - timedelta(days=7),
        end_date=datetime.now() + timedelta(days=3),
    )

    print(f"\nTotal notes generated: {len(all_notes)}")
    print(f"  - CLABSI-relevant notes: 8")
    print(f"  - Irrelevant notes: {len(all_notes) - 8}")

    # Calculate total character count
    total_chars = sum(len(n.content) for n in all_notes)
    avg_chars = total_chars / len(all_notes) if all_notes else 0
    print(f"\nTotal content size: {total_chars:,} characters")
    print(f"Average note length: {avg_chars:,.0f} characters")

    # Create NoteRetriever with mock source
    retriever = NoteRetriever(note_source=mock_source)

    # Test with keyword filtering
    clabsi_keywords = HAI_KEYWORDS.get('clabsi', [])
    print(f"\nCLABSI Keywords ({len(clabsi_keywords)} total):")
    print(f"  Sample: {', '.join(clabsi_keywords[:8])}...")

    filtered_notes = retriever.filter_by_keywords(all_notes, HAIType.CLABSI)
    filtered_chars = sum(len(n.content) for n in filtered_notes)

    print(f"\nAfter keyword filtering:")
    print(f"  - Notes kept: {len(filtered_notes)}")
    print(f"  - Notes filtered out: {len(all_notes) - len(filtered_notes)}")
    print(f"  - Content size: {filtered_chars:,} characters")
    print(f"  - Reduction: {100 * (1 - filtered_chars / total_chars):.1f}%")

    # Show which notes were kept
    print(f"\nNotes kept by filter:")
    for note in filtered_notes:
        print(f"  - {note.note_type}: {note.id} ({len(note.content):,} chars)")

    return all_notes, filtered_notes


def test_llm_classification(use_filtering: bool = True):
    """Test LLM classification timing.

    Args:
        use_filtering: Whether to use keyword filtering

    Returns:
        Tuple of (classification_result, elapsed_time)
    """
    from hai_src.data.mock_notes import MockNoteSource
    from hai_src.notes.retriever import NoteRetriever
    from hai_src.classifiers import CLABSIClassifierV2

    print(f"\n{'=' * 70}")
    print(f"TEST 2: LLM Classification ({'WITH' if use_filtering else 'WITHOUT'} filtering)")
    print("=" * 70)

    # Create mock source and candidate
    mock_source = MockNoteSource(hai_type="clabsi", include_irrelevant=True, num_irrelevant=22)
    candidate = create_mock_clabsi_candidate()

    # Create retriever
    retriever = NoteRetriever(note_source=mock_source)

    # Get notes
    print("\nRetrieving notes...")
    start_retrieve = time.time()

    notes = retriever.get_notes_for_candidate(
        candidate,
        days_before=7,
        days_after=3,
        hai_type="clabsi",
        use_keyword_filter=use_filtering,
    )

    retrieve_time = time.time() - start_retrieve
    total_chars = sum(len(n.content) for n in notes)

    print(f"  Notes retrieved: {len(notes)}")
    print(f"  Total content: {total_chars:,} characters")
    print(f"  Retrieval time: {retrieve_time:.2f}s")

    # Run LLM classification
    print("\nRunning LLM classification (this may take 60-90 seconds)...")
    classifier = CLABSIClassifierV2()

    start_llm = time.time()
    try:
        classification = classifier.classify(candidate, notes)
        llm_time = time.time() - start_llm

        print(f"\n  LLM classification completed in {llm_time:.1f}s")
        print(f"\n  Results:")
        print(f"    - Decision: {classification.decision.value}")
        print(f"    - Confidence: {classification.confidence:.2f}")
        print(f"    - Reasoning: {classification.reasoning[:200] if classification.reasoning else 'N/A'}...")

        return classification, llm_time

    except Exception as e:
        llm_time = time.time() - start_llm
        print(f"\n  LLM classification failed after {llm_time:.1f}s: {e}")
        import traceback
        traceback.print_exc()
        return None, llm_time


def main():
    """Run all tests."""
    print("\n" + "#" * 70)
    print("# CLABSI Keyword Filtering Performance Test")
    print("# Using realistic-length clinical notes (2-3K chars each)")
    print("#" * 70)

    # Test 1: Note retrieval and filtering
    all_notes, filtered_notes = test_note_retrieval()

    # Test 2: Compare LLM timing
    print("\n" + "#" * 70)
    print("# LLM Timing Comparison")
    print("#" * 70)

    # Run with filtering first (should be faster)
    result_filtered, time_filtered = test_llm_classification(use_filtering=True)

    # Run without filtering
    result_unfiltered, time_unfiltered = test_llm_classification(use_filtering=False)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)

    total_chars_all = sum(len(n.content) for n in all_notes)
    total_chars_filtered = sum(len(n.content) for n in filtered_notes)

    print(f"\nNotes:")
    print(f"  - Total available: {len(all_notes)} ({total_chars_all:,} chars)")
    print(f"  - After filtering: {len(filtered_notes)} ({total_chars_filtered:,} chars)")
    print(f"  - Reduction: {100 * (1 - total_chars_filtered / total_chars_all):.1f}%")

    print(f"\nLLM Classification Time:")
    print(f"  - WITH filtering:    {time_filtered:.1f}s ({len(filtered_notes)} notes, {total_chars_filtered:,} chars)")
    print(f"  - WITHOUT filtering: {time_unfiltered:.1f}s ({len(all_notes)} notes, {total_chars_all:,} chars)")

    if time_filtered > 0 and time_unfiltered > 0:
        speedup = time_unfiltered / time_filtered
        savings = time_unfiltered - time_filtered
        print(f"\n  Speedup: {speedup:.2f}x")
        print(f"  Time saved: {savings:.1f}s per candidate")


if __name__ == "__main__":
    main()
