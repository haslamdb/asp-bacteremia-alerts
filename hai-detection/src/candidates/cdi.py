"""CDI (Clostridioides difficile Infection) candidate detector.

Detects CDI LabID event candidates based on:
1. Positive C. difficile toxin A and/or B test, OR
2. Positive molecular test (PCR/NAAT) for toxin-producing C. diff

Classification is time-based:
- Healthcare-Facility Onset (HO-CDI): >3 days after admission
- Community Onset (CO-CDI): ≤3 days after admission
- CO-HCFA: CO-CDI with discharge from facility within prior 4 weeks

Recurrence tracking:
- ≤14 days since last event = Duplicate (not reported)
- 15-56 days = Recurrent
- >56 days = New Incident

Reference: 2024 NHSN Patient Safety Component Manual, Chapter 12
"""

import logging
import uuid
from datetime import datetime, timedelta

from .base import BaseCandidateDetector
from ..models import (
    HAICandidate,
    HAIType,
    CandidateStatus,
    Patient,
    CultureResult,
    CDITestResult,
    CDIEpisode,
    CDICandidate,
)
from ..rules.nhsn_criteria import (
    is_valid_cdi_test,
    calculate_specimen_day,
    get_cdi_onset_type,
    is_cdi_duplicate,
    is_cdi_recurrent,
    is_cdi_co_hcfa,
    get_cdi_recurrence_status,
    CDI_HO_MIN_DAYS,
    CDI_CO_HCFA_DISCHARGE_WINDOW_DAYS,
)
from ..data.fhir_source import FHIRCDITestSource

logger = logging.getLogger(__name__)


class CDICandidateDetector(BaseCandidateDetector):
    """Detect CDI candidates from positive C. difficile tests.

    This detector:
    1. Queries FHIR for positive C. diff toxin/PCR tests
    2. Gets patient admission date for each positive test
    3. Calculates specimen day (days since admission)
    4. Checks for prior CDI episodes (recurrence detection)
    5. Skips duplicates (≤14 days since last event)
    6. Creates candidates with HO vs CO classification

    Unlike device-associated HAIs (CLABSI, CAUTI), CDI detection is
    purely based on positive lab tests and timing - no device tracking.
    """

    def __init__(
        self,
        cdi_source: FHIRCDITestSource | None = None,
        db=None,
    ):
        """Initialize the CDI candidate detector.

        Args:
            cdi_source: FHIR data source for CDI tests. Uses default if None.
            db: Database for checking prior episodes. Optional.
        """
        self.cdi_source = cdi_source or FHIRCDITestSource()
        self.db = db

    @property
    def hai_type(self) -> HAIType:
        """The type of HAI this detector identifies."""
        return HAIType.CDI

    def detect_candidates(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[HAICandidate]:
        """Detect potential CDI candidates within a date range.

        Args:
            start_date: Start of date range to search
            end_date: End of date range to search

        Returns:
            List of HAI candidates for CDI events
        """
        candidates = []

        # Get positive CDI tests from FHIR
        try:
            positive_tests = self.cdi_source.get_positive_cdi_tests(
                start_date, end_date
            )
            logger.info(f"Found {len(positive_tests)} positive CDI tests")
        except Exception as e:
            logger.error(f"Failed to query CDI tests: {e}")
            return []

        for patient, cdi_test in positive_tests:
            try:
                candidate = self._evaluate_for_cdi(patient, cdi_test)
                if candidate:
                    candidates.append(candidate)
            except Exception as e:
                logger.error(
                    f"Error evaluating CDI for patient {patient.mrn}: {e}",
                    exc_info=True,
                )

        logger.info(f"Created {len(candidates)} CDI candidates")
        return candidates

    def _evaluate_for_cdi(
        self,
        patient: Patient,
        cdi_test: CDITestResult,
    ) -> HAICandidate | None:
        """Evaluate a positive CDI test for candidacy.

        Args:
            patient: Patient with positive test
            cdi_test: The positive CDI test result

        Returns:
            HAICandidate if criteria met, None otherwise
        """
        # Step 1: Verify test type qualifies (toxin/PCR, not antigen-only)
        if not is_valid_cdi_test(cdi_test.test_type, cdi_test.result):
            logger.debug(
                f"Test type {cdi_test.test_type} does not qualify for CDI LabID"
            )
            return None

        # Step 2: Check specimen type (must be unformed stool)
        if cdi_test.is_formed_stool:
            logger.debug(
                f"Formed stool specimen does not qualify for CDI LabID"
            )
            return None

        # Step 3: Get admission date
        admission_date = self.cdi_source.get_patient_admission_date(
            patient.fhir_id, cdi_test.test_date
        )

        if admission_date is None:
            logger.warning(
                f"Could not determine admission date for patient {patient.mrn}, "
                f"using test date as admission"
            )
            admission_date = cdi_test.test_date

        # Step 4: Calculate specimen day (day 1 = admission)
        specimen_day = calculate_specimen_day(admission_date, cdi_test.test_date)

        # Step 5: Determine onset type (HO vs CO)
        onset_type_code = get_cdi_onset_type(specimen_day)
        if onset_type_code == "healthcare_facility":
            onset_type = "ho"
        else:
            onset_type = "co"

        # Step 6: Check for prior CDI episodes (recurrence)
        prior_episodes = self._get_prior_cdi_episodes(
            patient.fhir_id, cdi_test.test_date
        )
        days_since_last_cdi = None
        is_duplicate = False
        is_recurrent = False

        if prior_episodes:
            # Get most recent episode
            most_recent = prior_episodes[0]
            days_since_last_cdi = most_recent.days_since(cdi_test.test_date)

            # Check if duplicate (≤14 days)
            if is_cdi_duplicate(days_since_last_cdi):
                logger.info(
                    f"CDI test for {patient.mrn} is duplicate "
                    f"({days_since_last_cdi} days since last)"
                )
                is_duplicate = True
                # Still create candidate but mark as duplicate
            elif is_cdi_recurrent(days_since_last_cdi):
                is_recurrent = True
                logger.info(
                    f"CDI test for {patient.mrn} is recurrent "
                    f"({days_since_last_cdi} days since last)"
                )

        # Step 7: Check for CO-HCFA (recent discharge from another facility)
        recent_discharge_date = None
        recent_discharge_facility = None
        days_since_discharge = None

        if onset_type == "co":
            discharge_date, facility = self.cdi_source.get_patient_prior_discharge(
                patient.fhir_id, admission_date
            )
            if discharge_date:
                days_since_discharge = (admission_date.date() - discharge_date.date()).days
                if days_since_discharge <= CDI_CO_HCFA_DISCHARGE_WINDOW_DAYS:
                    onset_type = "co_hcfa"
                    recent_discharge_date = discharge_date
                    recent_discharge_facility = facility
                    logger.info(
                        f"CDI for {patient.mrn} classified as CO-HCFA "
                        f"({days_since_discharge} days since discharge)"
                    )

        # Step 8: Create HAI candidate
        candidate_id = str(uuid.uuid4())

        # Create a CultureResult-like object for compatibility with HAICandidate
        # CDI uses toxin/PCR tests rather than cultures, but we map to the same structure
        culture = CultureResult(
            fhir_id=cdi_test.fhir_id,
            collection_date=cdi_test.test_date,
            organism="Clostridioides difficile",
            result_date=cdi_test.test_date,
            specimen_source="stool",
            is_positive=True,
        )

        # Create CDI-specific data
        cdi_data = CDICandidate(
            candidate_id=candidate_id,
            test_result=cdi_test,
            admission_date=admission_date,
            specimen_day=specimen_day,
            onset_type=onset_type,
            prior_episodes=prior_episodes,
            days_since_last_cdi=days_since_last_cdi,
            is_recurrent=is_recurrent,
            is_duplicate=is_duplicate,
            recent_discharge_date=recent_discharge_date,
            recent_discharge_facility=recent_discharge_facility,
        )

        # Determine classification
        recurrence_status = get_cdi_recurrence_status(days_since_last_cdi)
        if is_duplicate:
            cdi_data.classification = "duplicate"
        elif is_recurrent:
            cdi_data.classification = f"recurrent_{onset_type}"
        else:
            cdi_data.classification = f"{onset_type}_cdi"

        # Create HAICandidate
        candidate = HAICandidate(
            id=candidate_id,
            hai_type=HAIType.CDI,
            patient=patient,
            culture=culture,
            device_info=None,  # CDI has no device
            device_days_at_culture=None,  # Not applicable
            status=CandidateStatus.PENDING,
            meets_initial_criteria=not is_duplicate,  # Duplicates don't meet criteria
            exclusion_reason="Duplicate within 14 days" if is_duplicate else None,
            created_at=datetime.now(),
        )

        # Attach CDI-specific data
        candidate._cdi_data = cdi_data

        logger.info(
            f"Created CDI candidate {candidate_id[:8]} for {patient.mrn}: "
            f"{onset_type.upper()}-CDI, specimen day {specimen_day}, "
            f"{'recurrent' if is_recurrent else 'incident'}"
        )

        return candidate

    def _get_prior_cdi_episodes(
        self,
        patient_id: str,
        before_date: datetime,
    ) -> list[CDIEpisode]:
        """Get prior CDI episodes for recurrence detection.

        Checks both FHIR history and local database for prior episodes.

        Args:
            patient_id: FHIR patient ID
            before_date: Current test date

        Returns:
            List of prior CDI episodes, sorted by date descending
        """
        episodes = []

        # First check local database for tracked episodes
        if self.db:
            try:
                db_episodes = self.db.get_patient_cdi_episodes(
                    patient_id, before_date
                )
                for ep in db_episodes:
                    episodes.append(
                        CDIEpisode(
                            id=ep.get("id"),
                            patient_id=patient_id,
                            test_date=ep.get("test_date"),
                            test_type=ep.get("test_type"),
                            onset_type=ep.get("onset_type"),
                            is_recurrent=ep.get("is_recurrent", False),
                        )
                    )
            except Exception as e:
                logger.debug(f"Could not query DB for CDI episodes: {e}")

        # Also check FHIR for prior positive tests
        try:
            fhir_history = self.cdi_source.get_patient_cdi_history(
                patient_id, before_date
            )
            for test in fhir_history:
                # Don't duplicate entries already found in DB
                if not any(e.test_date == test.test_date for e in episodes):
                    episodes.append(
                        CDIEpisode(
                            id=f"fhir-{test.fhir_id}",
                            patient_id=patient_id,
                            test_date=test.test_date,
                            test_type=test.test_type,
                            onset_type="unknown",  # Would need encounter lookup
                            is_recurrent=False,
                        )
                    )
        except Exception as e:
            logger.debug(f"Could not query FHIR for CDI history: {e}")

        # Sort by test date descending (most recent first)
        episodes.sort(key=lambda e: e.test_date, reverse=True)

        return episodes

    def validate_candidate(
        self, candidate: HAICandidate
    ) -> tuple[bool, str | None]:
        """Validate that a CDI candidate meets all NHSN criteria.

        Args:
            candidate: The candidate to validate

        Returns:
            Tuple of (is_valid, exclusion_reason)
        """
        cdi_data = getattr(candidate, "_cdi_data", None)
        if not cdi_data:
            return False, "Missing CDI-specific data"

        # Check if duplicate
        if cdi_data.is_duplicate:
            return False, "Duplicate within 14-day window"

        # Check specimen type
        if cdi_data.test_result.is_formed_stool:
            return False, "Formed stool specimen does not qualify"

        # Check test type
        if not is_valid_cdi_test(
            cdi_data.test_result.test_type,
            cdi_data.test_result.result
        ):
            return False, f"Test type {cdi_data.test_result.test_type} does not qualify"

        return True, None

    def get_summary(self, candidate: HAICandidate) -> str:
        """Get a human-readable summary of the CDI candidate.

        Args:
            candidate: The CDI candidate

        Returns:
            Summary string for display
        """
        cdi_data = getattr(candidate, "_cdi_data", None)
        if not cdi_data:
            return "CDI candidate (details unavailable)"

        parts = [f"C. difficile positive ({cdi_data.test_result.test_type})"]

        # Add onset type
        onset_display = {
            "ho": "Healthcare-Facility Onset (HO-CDI)",
            "co": "Community Onset (CO-CDI)",
            "co_hcfa": "Community Onset, Healthcare-Facility Associated (CO-HCFA)",
        }
        parts.append(onset_display.get(cdi_data.onset_type, cdi_data.onset_type))

        # Add specimen day
        parts.append(f"specimen day {cdi_data.specimen_day}")

        # Add recurrence status
        if cdi_data.is_duplicate:
            parts.append("DUPLICATE (not reported)")
        elif cdi_data.is_recurrent:
            parts.append(f"RECURRENT ({cdi_data.days_since_last_cdi} days since last)")
        else:
            parts.append("INCIDENT")

        return " - ".join(parts)
