"""SSI (Surgical Site Infection) candidate detection.

NHSN SSI Criteria (simplified):
1. Patient had an NHSN operative procedure
2. Infection occurs within surveillance window (30 or 90 days)
3. Infection is related to the operative procedure site
4. Meets criteria for superficial, deep, or organ/space SSI

This module implements rule-based detection of SSI candidates.
LLM extraction is used for wound assessment and infection signals.
Rules engine applies NHSN SSI criteria for classification.
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
    SurgicalProcedure,
    SSICandidate,
)
from ..data.factory import get_procedure_source, get_culture_source, get_note_source
from ..data.procedure_source import BaseProcedureSource
from ..data.base import BaseCultureSource, BaseNoteSource
from ..rules.nhsn_criteria import (
    is_nhsn_operative_procedure,
    get_surveillance_window,
    SSI_DETECTION_KEYWORDS,
)
from .base import BaseCandidateDetector

logger = logging.getLogger(__name__)


class SSICandidateDetector(BaseCandidateDetector):
    """Detector for SSI candidates based on NHSN criteria.

    Detection strategy:
    1. Get NHSN operative procedures within lookback window
    2. For each procedure still in surveillance period:
       - Check for positive wound/tissue cultures
       - Scan notes for SSI keywords (wound infection, dehiscence, etc.)
       - Check for readmissions related to procedure
    3. Create candidate if infection signals found
    """

    def __init__(
        self,
        procedure_source: BaseProcedureSource | None = None,
        culture_source: BaseCultureSource | None = None,
        note_source: BaseNoteSource | None = None,
    ):
        """Initialize the detector.

        Args:
            procedure_source: Source for surgical procedure data. Uses factory default if None.
            culture_source: Source for culture data. Uses factory default if None.
            note_source: Source for clinical notes. Uses factory default if None.
        """
        self.procedure_source = procedure_source or get_procedure_source()
        self.culture_source = culture_source or get_culture_source()
        self.note_source = note_source or get_note_source()

        # Lookback for procedures (need to capture procedures within max surveillance window)
        self.procedure_lookback_days = 90  # Max surveillance window

    @property
    def hai_type(self) -> HAIType:
        return HAIType.SSI

    def detect_candidates(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[HAICandidate]:
        """Detect potential SSI candidates.

        Process:
        1. Get NHSN operative procedures within lookback window
        2. For each procedure still in surveillance period:
           - Check for infection signals (cultures, notes, readmissions)
        3. Create candidate if criteria met

        Args:
            start_date: Start of date range for infection signals
            end_date: End of date range for infection signals

        Returns:
            List of SSI candidates
        """
        candidates = []

        logger.info(
            f"Detecting SSI candidates from {start_date.date()} to {end_date.date()}"
        )

        # Get procedures that could have SSI (within max surveillance window)
        procedure_start = end_date - timedelta(days=self.procedure_lookback_days)
        procedures_with_patients = self.procedure_source.get_nhsn_procedures(
            procedure_start, end_date
        )

        logger.info(f"Found {len(procedures_with_patients)} NHSN procedures to evaluate")

        for patient, procedure in procedures_with_patients:
            # Check if still within surveillance window
            if not procedure.is_within_surveillance(end_date):
                logger.debug(
                    f"Procedure {procedure.id} outside surveillance window "
                    f"({procedure.days_since_procedure(end_date)} days post-op)"
                )
                continue

            # Check for infection signals
            candidate = self._evaluate_for_ssi(
                patient, procedure, start_date, end_date
            )
            if candidate:
                candidates.append(candidate)

        logger.info(f"Identified {len(candidates)} SSI candidates")
        return candidates

    def _evaluate_for_ssi(
        self,
        patient: Patient,
        procedure: SurgicalProcedure,
        start_date: datetime,
        end_date: datetime,
    ) -> HAICandidate | None:
        """Evaluate a surgical procedure for SSI signals.

        Args:
            patient: Patient information
            procedure: Surgical procedure
            start_date: Start of signal detection window
            end_date: End of signal detection window

        Returns:
            HAICandidate if infection signals found, None otherwise
        """
        days_post_op = procedure.days_since_procedure(end_date)
        infection_signals = []

        # Signal 1: Check for positive wound/tissue cultures
        wound_culture = self._check_for_wound_cultures(
            patient.fhir_id, procedure, start_date, end_date
        )
        if wound_culture:
            infection_signals.append(("wound_culture", wound_culture))
            logger.debug(
                f"Found positive wound culture for patient {patient.mrn}: "
                f"{wound_culture.organism}"
            )

        # Signal 2: Scan notes for SSI keywords
        ssi_keywords_found = self._scan_notes_for_ssi_keywords(
            patient.fhir_id, procedure.procedure_date, end_date
        )
        if ssi_keywords_found:
            infection_signals.append(("keywords", ssi_keywords_found))
            logger.debug(
                f"Found SSI keywords in notes for patient {patient.mrn}: "
                f"{ssi_keywords_found[:3]}..."
            )

        # If no infection signals, no candidate
        if not infection_signals:
            return None

        # Create a "synthetic" culture result for the candidate
        # (SSI candidates don't necessarily have a blood culture like CLABSI)
        culture = self._create_culture_for_candidate(
            patient, procedure, wound_culture, infection_signals
        )

        # Create candidate
        candidate = HAICandidate(
            id=str(uuid.uuid4()),
            hai_type=HAIType.SSI,
            patient=patient,
            culture=culture,
            device_info=None,  # SSI doesn't use device_info
            device_days_at_culture=None,
            status=CandidateStatus.PENDING,
        )

        # Store SSI-specific data in a separate structure
        # (This would be persisted in ssi_candidate_details table)
        ssi_data = SSICandidate(
            candidate_id=candidate.id,
            procedure=procedure,
            days_post_op=days_post_op,
            wound_culture_organism=wound_culture.organism if wound_culture else None,
            wound_culture_date=wound_culture.collection_date if wound_culture else None,
        )

        # Attach SSI data to candidate for later use
        candidate._ssi_data = ssi_data  # type: ignore

        # Validate against NHSN criteria
        is_valid, exclusion_reason = self.validate_candidate(candidate)

        if not is_valid:
            candidate.meets_initial_criteria = False
            candidate.exclusion_reason = exclusion_reason
            candidate.status = CandidateStatus.EXCLUDED
            logger.debug(
                f"Candidate excluded for patient {patient.mrn}: {exclusion_reason}"
            )
            return candidate

        return candidate

    def _check_for_wound_cultures(
        self,
        patient_id: str,
        procedure: SurgicalProcedure,
        start_date: datetime,
        end_date: datetime,
    ) -> CultureResult | None:
        """Check for positive wound/tissue cultures related to procedure.

        Args:
            patient_id: Patient FHIR ID
            procedure: The surgical procedure
            start_date: Start of search window
            end_date: End of search window

        Returns:
            Most recent positive wound culture if found
        """
        try:
            # Get all cultures for patient
            cultures = self.culture_source.get_cultures_for_patient(
                patient_id, procedure.procedure_date, end_date
            )

            # Filter for wound/tissue cultures (not blood cultures)
            wound_sources = {
                "wound",
                "tissue",
                "abscess",
                "drain",
                "surgical site",
                "incision",
                "operative site",
                "deep tissue",
                "bone",
                "prosthetic",
                "implant",
                "fluid",  # e.g., intra-abdominal fluid
            }

            for culture in cultures:
                if not culture.is_positive:
                    continue

                # Check if specimen source is wound-related
                if culture.specimen_source:
                    source_lower = culture.specimen_source.lower()
                    if any(ws in source_lower for ws in wound_sources):
                        return culture

            return None

        except Exception as e:
            logger.warning(f"Error checking wound cultures: {e}")
            return None

    def _scan_notes_for_ssi_keywords(
        self,
        patient_id: str,
        procedure_date: datetime,
        end_date: datetime,
    ) -> list[str]:
        """Scan clinical notes for SSI-related keywords.

        Args:
            patient_id: Patient FHIR ID
            procedure_date: Date of surgical procedure
            end_date: End of search window

        Returns:
            List of SSI keywords found in notes
        """
        try:
            notes = self.note_source.get_notes_for_patient(
                patient_id,
                procedure_date,
                end_date,
                note_types=None,  # All note types
            )

            keywords_found = set()

            for note in notes:
                content_lower = note.content.lower()
                for keyword in SSI_DETECTION_KEYWORDS:
                    if keyword in content_lower:
                        keywords_found.add(keyword)

            return list(keywords_found)

        except Exception as e:
            logger.warning(f"Error scanning notes for SSI keywords: {e}")
            return []

    def _create_culture_for_candidate(
        self,
        patient: Patient,
        procedure: SurgicalProcedure,
        wound_culture: CultureResult | None,
        infection_signals: list[tuple[str, any]],
    ) -> CultureResult:
        """Create a CultureResult for the SSI candidate.

        SSI candidates may or may not have an actual culture. This creates
        a placeholder or uses the actual wound culture.

        Args:
            patient: Patient information
            procedure: Surgical procedure
            wound_culture: Actual wound culture if found
            infection_signals: List of infection signals found

        Returns:
            CultureResult (real or synthetic)
        """
        if wound_culture:
            return wound_culture

        # Create synthetic culture result for keyword-based detection
        return CultureResult(
            fhir_id=f"ssi-signal-{procedure.id}",
            collection_date=datetime.now(),
            organism=None,  # Will be determined by LLM extraction
            result_date=datetime.now(),
            specimen_source="surgical_site_infection_signal",
            is_positive=True,
        )

    def validate_candidate(
        self, candidate: HAICandidate
    ) -> tuple[bool, str | None]:
        """Validate candidate against NHSN SSI criteria.

        Criteria checked:
        1. Must be NHSN operative procedure category
        2. Must be within surveillance window

        Note: SSI type (superficial/deep/organ-space) is determined
        later by the rules engine based on LLM extraction.

        Args:
            candidate: The candidate to validate

        Returns:
            Tuple of (is_valid, exclusion_reason)
        """
        # Get SSI-specific data
        ssi_data: SSICandidate | None = getattr(candidate, "_ssi_data", None)

        if not ssi_data:
            return False, "Missing SSI procedure data"

        procedure = ssi_data.procedure

        # Criterion 1: Must be NHSN operative procedure
        if not procedure.nhsn_category:
            return False, "Procedure not mapped to NHSN category"

        if not is_nhsn_operative_procedure(procedure.nhsn_category):
            return False, f"Category {procedure.nhsn_category} is not an NHSN operative procedure"

        # Criterion 2: Must be within surveillance window
        surveillance_days = get_surveillance_window(
            procedure.nhsn_category, procedure.implant_used
        )

        if ssi_data.days_post_op > surveillance_days:
            return (
                False,
                f"Outside surveillance window ({ssi_data.days_post_op} days > {surveillance_days} days)",
            )

        if ssi_data.days_post_op < 0:
            return False, "Infection signal before procedure date"

        return True, None

    def get_exclusion_reasons(self) -> list[str]:
        """Get list of possible exclusion reasons for reporting."""
        return [
            "Procedure not mapped to NHSN category",
            "Category is not an NHSN operative procedure",
            "Outside surveillance window",
            "Infection signal before procedure date",
            "Missing SSI procedure data",
        ]
