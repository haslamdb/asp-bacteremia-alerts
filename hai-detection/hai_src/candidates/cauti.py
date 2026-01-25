"""CAUTI (Catheter-Associated Urinary Tract Infection) candidate detection.

NHSN CAUTI Criteria:
1. Indwelling urinary catheter (IUC) in place >2 calendar days
2. Positive urine culture >=10^5 CFU/mL with <=2 organisms (no mixed flora)
3. At least one sign/symptom: fever >38C, suprapubic tenderness, CVA pain/tenderness,
   urinary urgency, frequency, or dysuria
4. Not asymptomatic bacteriuria

This module implements rule-based detection of CAUTI candidates based on:
- Positive urine culture meeting threshold
- Indwelling urinary catheter present >2 days
- Excludes Candida-only cultures and mixed flora

LLM classification is used later to extract symptoms and apply age-based criteria.
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
    CatheterEpisode,
    CAUTICandidate,
)
from ..data.fhir_source import FHIRUrinaryCatheterSource, FHIRUrineCultureSource
from ..rules.nhsn_criteria import (
    CAUTI_MIN_CATHETER_DAYS,
    CAUTI_POST_REMOVAL_WINDOW_DAYS,
    CAUTI_MIN_CFU_ML,
    CAUTI_MAX_ORGANISMS,
    is_cauti_excluded_organism,
    is_valid_cauti_culture,
)
from .base import BaseCandidateDetector

logger = logging.getLogger(__name__)


class CAUTICandidateDetector(BaseCandidateDetector):
    """Detector for CAUTI candidates based on NHSN criteria.

    This detector identifies CAUTI candidates by finding patients with:
    1. Indwelling urinary catheter present >2 calendar days
    2. Positive urine culture >= 10^5 CFU/mL with <=2 organisms

    Symptoms are extracted during LLM classification. Initial detection
    is based on culture + catheter criteria only.
    """

    def __init__(
        self,
        catheter_source: FHIRUrinaryCatheterSource | None = None,
        culture_source: FHIRUrineCultureSource | None = None,
        fhir_base_url: str | None = None,
    ):
        """Initialize the detector.

        Args:
            catheter_source: Source for urinary catheter data
            culture_source: Source for urine culture data
            fhir_base_url: FHIR server base URL (uses config default if None)
        """
        base_url = fhir_base_url or Config.get_fhir_base_url()
        self.catheter_source = catheter_source or FHIRUrinaryCatheterSource(base_url)
        self.culture_source = culture_source or FHIRUrineCultureSource(base_url)
        self.min_catheter_days = CAUTI_MIN_CATHETER_DAYS
        self.post_removal_window = CAUTI_POST_REMOVAL_WINDOW_DAYS
        self.min_cfu_ml = CAUTI_MIN_CFU_ML
        self.max_organisms = CAUTI_MAX_ORGANISMS

    @property
    def hai_type(self) -> HAIType:
        return HAIType.CAUTI

    def detect_candidates(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[HAICandidate]:
        """Detect potential CAUTI candidates.

        Process:
        1. Get all positive urine cultures meeting CFU threshold
        2. For each culture, find associated urinary catheter
        3. Calculate catheter days at culture date
        4. Create candidate if catheter >2 days and culture meets criteria
        5. Exclude Candida-only cultures and mixed flora

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of CAUTI candidates
        """
        candidates = []

        logger.info(
            f"Detecting CAUTI candidates from {start_date.date()} to {end_date.date()}"
        )

        # Get positive urine cultures meeting CFU threshold
        positive_cultures = self.culture_source.get_positive_urine_cultures(
            start_date, end_date, min_cfu_ml=self.min_cfu_ml
        )

        logger.info(f"Found {len(positive_cultures)} positive urine cultures >= {self.min_cfu_ml} CFU/mL")

        for patient, culture in positive_cultures:
            candidate = self._evaluate_for_cauti(patient, culture)
            if candidate:
                candidates.append(candidate)

        logger.info(f"Identified {len(candidates)} CAUTI candidates")
        return candidates

    def _evaluate_for_cauti(
        self,
        patient: Patient,
        culture: CultureResult,
    ) -> HAICandidate | None:
        """Evaluate a urine culture for CAUTI criteria.

        Args:
            patient: Patient information
            culture: Urine culture result

        Returns:
            HAICandidate if initial CAUTI criteria met, None otherwise
        """
        # Check for excluded organisms (Candida, yeast)
        if culture.organism and is_cauti_excluded_organism(culture.organism):
            logger.debug(
                f"Culture excluded for patient {patient.mrn}: "
                f"excluded organism ({culture.organism})"
            )
            return None

        # Get CFU/mL if stored in culture result
        cfu_ml = getattr(culture, '_cfu_ml', None)

        # Get organism count if available
        organism_count = getattr(culture, '_organism_count', 1)
        if organism_count > self.max_organisms:
            logger.debug(
                f"Culture excluded for patient {patient.mrn}: "
                f"mixed flora ({organism_count} organisms)"
            )
            return None

        # Find urinary catheters present at culture date
        catheters = self.catheter_source.get_urinary_catheters(
            patient.fhir_id,
            culture.collection_date,
        )

        if not catheters:
            logger.debug(
                f"No urinary catheter found for patient {patient.mrn} "
                f"at culture date {culture.collection_date.date()}"
            )
            return None

        # Use the catheter with the longest duration at culture date
        best_catheter = None
        best_days = 0

        for catheter in catheters:
            if catheter.insertion_date:
                days = catheter.days_at_date(culture.collection_date)
                if days and days > best_days:
                    best_catheter = catheter
                    best_days = days

        if best_catheter is None or best_days <= self.min_catheter_days:
            logger.debug(
                f"Catheter days ({best_days}) <= minimum ({self.min_catheter_days}) "
                f"for patient {patient.mrn}"
            )
            # Still create candidate but mark as potentially excluded
            # (symptoms may still qualify per NHSN criteria)
            pass

        # Calculate patient age for age-based fever rule
        patient_age = None
        if patient.birth_date:
            try:
                birth = datetime.fromisoformat(patient.birth_date)
                age_delta = culture.collection_date - birth
                patient_age = age_delta.days // 365
            except (ValueError, TypeError):
                pass

        # Create catheter episode from DeviceInfo
        catheter_episode = None
        if best_catheter:
            catheter_episode = CatheterEpisode(
                id=best_catheter.fhir_id or str(uuid.uuid4()),
                patient_id=patient.fhir_id,
                patient_mrn=patient.mrn,
                insertion_date=best_catheter.insertion_date or culture.collection_date,
                removal_date=best_catheter.removal_date,
                catheter_type=best_catheter.device_type,
                site=best_catheter.site,
                fhir_device_id=best_catheter.fhir_id,
            )

        # Create candidate
        candidate = HAICandidate(
            id=str(uuid.uuid4()),
            hai_type=HAIType.CAUTI,
            patient=patient,
            culture=culture,
            device_info=best_catheter,
            device_days_at_culture=best_days if best_days > 0 else None,
            status=CandidateStatus.PENDING,
        )

        # Create CAUTI-specific candidate data
        if catheter_episode:
            cauti_data = CAUTICandidate(
                candidate_id=candidate.id,
                catheter_episode=catheter_episode,
                catheter_days=best_days,
                patient_age=patient_age,
                culture_cfu_ml=cfu_ml,
                culture_organism=culture.organism,
                culture_organism_count=organism_count,
            )
            # Attach CAUTI data to candidate for later use
            candidate._cauti_data = cauti_data

        # Validate against NHSN criteria
        is_valid, exclusion_reason = self.validate_candidate(candidate)

        if not is_valid:
            candidate.meets_initial_criteria = False
            candidate.exclusion_reason = exclusion_reason
            candidate.status = CandidateStatus.EXCLUDED
            logger.debug(
                f"Candidate excluded for patient {patient.mrn}: {exclusion_reason}"
            )
            # Return candidate anyway for tracking/audit
            return candidate

        return candidate

    def validate_candidate(self, candidate: HAICandidate) -> tuple[bool, str | None]:
        """Validate candidate against initial NHSN CAUTI criteria.

        This checks eligibility criteria that can be determined from
        structured data alone. Symptom criteria are evaluated during
        LLM classification.

        Criteria checked:
        1. Urinary catheter present
        2. Catheter in place >2 calendar days
        3. Positive urine culture
        4. Culture not mixed flora (<=2 organisms)
        5. Culture not excluded organism (Candida, yeast)

        Args:
            candidate: The candidate to validate

        Returns:
            Tuple of (is_valid, exclusion_reason)
        """
        # Check for catheter
        if candidate.device_info is None:
            return False, "No urinary catheter documented"

        # Check catheter days
        if candidate.device_days_at_culture is None:
            return False, "Unable to determine catheter days"

        if candidate.device_days_at_culture <= self.min_catheter_days:
            return False, f"Catheter days ({candidate.device_days_at_culture}) <= minimum ({self.min_catheter_days})"

        # Check culture
        if not candidate.culture.is_positive:
            return False, "Urine culture not positive"

        # Check for excluded organisms
        if candidate.culture.organism and is_cauti_excluded_organism(candidate.culture.organism):
            return False, f"Excluded organism: {candidate.culture.organism}"

        # Check CAUTI-specific data if available
        cauti_data = getattr(candidate, '_cauti_data', None)
        if cauti_data:
            # Check organism count for mixed flora
            if cauti_data.culture_organism_count and cauti_data.culture_organism_count > self.max_organisms:
                return False, f"Mixed flora ({cauti_data.culture_organism_count} organisms > {self.max_organisms})"

            # Check CFU threshold if known
            if cauti_data.culture_cfu_ml and cauti_data.culture_cfu_ml < self.min_cfu_ml:
                return False, f"CFU/mL ({cauti_data.culture_cfu_ml}) < minimum ({self.min_cfu_ml})"

        return True, None

    def get_exclusion_reasons(self) -> list[str]:
        """Get list of possible exclusion reasons for reporting."""
        return [
            "No urinary catheter documented",
            "Unable to determine catheter days",
            f"Catheter days <= minimum ({self.min_catheter_days})",
            "Urine culture not positive",
            "Excluded organism (Candida, yeast)",
            f"Mixed flora (> {self.max_organisms} organisms)",
            f"CFU/mL < minimum ({self.min_cfu_ml})",
            "No positive urine culture found",
        ]
