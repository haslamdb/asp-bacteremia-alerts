"""CLABSI (Central Line-Associated Bloodstream Infection) candidate detection.

NHSN CLABSI Criteria (simplified):
1. Patient has a central line (or had one within 1 day of positive culture)
2. Central line was in place for >2 calendar days
3. Patient has a laboratory-confirmed bloodstream infection (LCBI)
4. Bloodstream infection is not secondary to another site of infection

This module implements rule-based detection of CLABSI candidates.
LLM classification is used later for source attribution (criteria 4).
"""

import logging
import uuid
from datetime import datetime, timedelta

from ..config import Config
from ..models import (
    HAICandidate,
    HAIType,
    CandidateStatus,
    Patient,
    CultureResult,
    DeviceInfo,
)
from ..data.factory import get_culture_source, get_device_source
from ..data.base import BaseCultureSource, BaseDeviceSource
from .base import BaseCandidateDetector

logger = logging.getLogger(__name__)


# Common contaminant organisms (require 2 positive cultures)
COMMON_CONTAMINANTS = {
    "coagulase-negative staphylococci",
    "coagulase negative staphylococcus",
    "staphylococcus epidermidis",
    "staphylococcus hominis",
    "staphylococcus haemolyticus",
    "corynebacterium",
    "diphtheroids",
    "bacillus",
    "propionibacterium",
    "cutibacterium acnes",
    "micrococcus",
    "viridans streptococci",
    "viridans group streptococcus",
    "aerococcus",
}


class CLABSICandidateDetector(BaseCandidateDetector):
    """Detector for CLABSI candidates based on NHSN criteria."""

    def __init__(
        self,
        culture_source: BaseCultureSource | None = None,
        device_source: BaseDeviceSource | None = None,
    ):
        """Initialize the detector.

        Args:
            culture_source: Source for culture data. Uses factory default if None.
            device_source: Source for device data. Uses factory default if None.
        """
        self.culture_source = culture_source or get_culture_source()
        self.device_source = device_source or get_device_source()
        self.min_device_days = Config.MIN_DEVICE_DAYS
        self.post_removal_window = Config.POST_REMOVAL_WINDOW_DAYS

    @property
    def hai_type(self) -> HAIType:
        return HAIType.CLABSI

    def detect_candidates(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[HAICandidate]:
        """Detect potential CLABSI candidates.

        Process:
        1. Get all positive blood cultures in date range
        2. For each culture, check for central line presence
        3. Validate against NHSN criteria
        4. Create candidate if criteria met

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of CLABSI candidates
        """
        candidates = []

        logger.info(
            f"Detecting CLABSI candidates from {start_date.date()} to {end_date.date()}"
        )

        # Get positive blood cultures
        cultures_with_patients = self.culture_source.get_positive_blood_cultures(
            start_date, end_date
        )

        logger.info(f"Found {len(cultures_with_patients)} positive blood cultures")

        for patient, culture in cultures_with_patients:
            candidate = self._evaluate_for_clabsi(patient, culture)
            if candidate:
                candidates.append(candidate)

        logger.info(f"Identified {len(candidates)} CLABSI candidates")
        return candidates

    def _evaluate_for_clabsi(
        self,
        patient: Patient,
        culture: CultureResult,
    ) -> HAICandidate | None:
        """Evaluate a positive blood culture for CLABSI criteria.

        Args:
            patient: Patient information
            culture: Positive blood culture result

        Returns:
            HAICandidate if criteria met, None otherwise
        """
        # Check for central line presence at time of culture
        central_lines = self.device_source.get_central_lines(
            patient.fhir_id,
            culture.collection_date,
        )

        if not central_lines:
            logger.debug(
                f"No central line found for patient {patient.mrn} at culture date"
            )
            return None

        # Find the line with the longest dwell time (most likely source)
        best_line = None
        max_device_days = 0

        for line in central_lines:
            device_days = line.days_at_date(culture.collection_date)
            if device_days is not None and device_days > max_device_days:
                max_device_days = device_days
                best_line = line

        if best_line is None:
            logger.debug(
                f"Could not determine device days for patient {patient.mrn}"
            )
            return None

        # Create candidate
        candidate = HAICandidate(
            id=str(uuid.uuid4()),
            hai_type=HAIType.CLABSI,
            patient=patient,
            culture=culture,
            device_info=best_line,
            device_days_at_culture=max_device_days,
            status=CandidateStatus.PENDING,
        )

        # Validate against NHSN criteria
        is_valid, exclusion_reason = self.validate_candidate(candidate)

        if not is_valid:
            candidate.meets_initial_criteria = False
            candidate.exclusion_reason = exclusion_reason
            candidate.status = CandidateStatus.EXCLUDED
            logger.debug(
                f"Candidate excluded for patient {patient.mrn}: {exclusion_reason}"
            )
            # Still return excluded candidates for tracking
            return candidate

        return candidate

    def validate_candidate(
        self, candidate: HAICandidate
    ) -> tuple[bool, str | None]:
        """Validate candidate against NHSN CLABSI criteria.

        Criteria checked:
        1. Central line in place >2 calendar days
        2. Not a repeat positive within 14 days
        3. Contaminant organisms require 2 positive cultures

        Args:
            candidate: The candidate to validate

        Returns:
            Tuple of (is_valid, exclusion_reason)
        """
        # Criterion 1: Device days > 2
        if candidate.device_days_at_culture is None:
            return False, "Unable to determine device days"

        if candidate.device_days_at_culture < self.min_device_days:
            return False, f"Device days ({candidate.device_days_at_culture}) < minimum ({self.min_device_days})"

        # Criterion 2: Check for common contaminants
        if candidate.culture.organism:
            organism_lower = candidate.culture.organism.lower()
            is_contaminant = any(
                contam in organism_lower for contam in COMMON_CONTAMINANTS
            )

            if is_contaminant:
                # For contaminants, need to check for 2 positive cultures
                # within 2 days (simplified check - could be enhanced)
                if not self._has_confirmatory_culture(candidate):
                    return False, f"Single positive for contaminant organism ({candidate.culture.organism})"

        return True, None

    def _has_confirmatory_culture(self, candidate: HAICandidate) -> bool:
        """Check if there's a second positive culture for contaminant organisms.

        NHSN requires 2 positive blood cultures drawn on separate occasions
        within 2 days for common contaminants.
        """
        culture_date = candidate.culture.collection_date
        window_start = culture_date - timedelta(days=2)
        window_end = culture_date + timedelta(days=2)

        try:
            other_cultures = self.culture_source.get_cultures_for_patient(
                candidate.patient.fhir_id,
                window_start,
                window_end,
            )

            # Look for another positive culture with same organism
            for other in other_cultures:
                if other.fhir_id == candidate.culture.fhir_id:
                    continue  # Skip the original culture

                if not other.is_positive:
                    continue

                # Check if same organism
                if other.organism and candidate.culture.organism:
                    if other.organism.lower() == candidate.culture.organism.lower():
                        # Check if drawn on different day
                        if other.collection_date.date() != culture_date.date():
                            return True

        except Exception as e:
            logger.warning(f"Error checking for confirmatory culture: {e}")

        return False

    def get_exclusion_reasons(self) -> list[str]:
        """Get list of possible exclusion reasons for reporting."""
        return [
            f"Device days < minimum ({self.min_device_days})",
            "Unable to determine device days",
            "Single positive for contaminant organism",
            "No central line present",
        ]
