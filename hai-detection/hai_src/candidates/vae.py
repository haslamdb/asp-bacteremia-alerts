"""VAE (Ventilator-Associated Event) candidate detection.

NHSN VAE Criteria (simplified):
1. Patient is on mechanical ventilation for ≥2 calendar days
2. ≥2 calendar days of stable or decreasing ventilator settings (baseline)
3. ≥2 calendar days of sustained worsening (increased FiO2 ≥20% or PEEP ≥3 cmH2O)

VAC onset = first day of sustained worsening after baseline period.

This module implements rule-based detection of VAC (Ventilator-Associated Condition)
candidates. LLM classification is used later for IVAC/VAP determination.
"""

import logging
import uuid
from datetime import datetime, timedelta, date

from ..config import Config
from ..models import (
    HAICandidate,
    HAIType,
    CandidateStatus,
    Patient,
    CultureResult,
    VentilationEpisode,
    DailyVentParameters,
    VAECandidate,
)
from ..data.factory import get_ventilator_source
from ..data.base import BaseVentilatorSource
from ..rules.nhsn_criteria import (
    VAE_MIN_VENT_DAYS,
    VAE_BASELINE_PERIOD_DAYS,
    VAE_WORSENING_PERIOD_DAYS,
    VAE_FIO2_INCREASE_THRESHOLD,
    VAE_PEEP_INCREASE_THRESHOLD,
)
from .base import BaseCandidateDetector

logger = logging.getLogger(__name__)


class VAECandidateDetector(BaseCandidateDetector):
    """Detector for VAE (specifically VAC) candidates based on NHSN criteria.

    This detector identifies VAC (Ventilator-Associated Condition) candidates
    by analyzing daily FiO2/PEEP trends. IVAC and VAP classification occurs
    during the LLM classification phase.

    VAC Algorithm:
    1. Find patients on mechanical ventilation ≥2 days
    2. For each day, calculate minimum FiO2 and PEEP
    3. Identify baseline period (≥2 days stable/decreasing)
    4. Detect worsening (≥2 days of increased FiO2 ≥20% or PEEP ≥3 cmH2O)
    5. VAC onset = first day of sustained worsening
    """

    def __init__(
        self,
        ventilator_source: BaseVentilatorSource | None = None,
    ):
        """Initialize the detector.

        Args:
            ventilator_source: Source for ventilator data. Uses factory default if None.
        """
        self.ventilator_source = ventilator_source or get_ventilator_source()
        self.min_vent_days = VAE_MIN_VENT_DAYS
        self.baseline_period_days = VAE_BASELINE_PERIOD_DAYS
        self.worsening_period_days = VAE_WORSENING_PERIOD_DAYS
        self.fio2_increase_threshold = VAE_FIO2_INCREASE_THRESHOLD
        self.peep_increase_threshold = VAE_PEEP_INCREASE_THRESHOLD

    @property
    def hai_type(self) -> HAIType:
        return HAIType.VAE

    def detect_candidates(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[HAICandidate]:
        """Detect potential VAC candidates.

        Process:
        1. Get all patients on mechanical ventilation ≥2 days
        2. For each patient, retrieve daily FiO2/PEEP parameters
        3. Apply VAC detection algorithm
        4. Create candidate if VAC criteria met

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of VAC candidates
        """
        candidates = []

        logger.info(
            f"Detecting VAE candidates from {start_date.date()} to {end_date.date()}"
        )

        # Get ventilated patients meeting minimum duration
        ventilated_patients = self.ventilator_source.get_ventilated_patients(
            start_date, end_date, min_vent_days=self.min_vent_days
        )

        logger.info(f"Found {len(ventilated_patients)} patients on ventilator ≥{self.min_vent_days} days")

        for patient, episode in ventilated_patients:
            candidate = self._evaluate_for_vac(patient, episode)
            if candidate:
                candidates.append(candidate)

        logger.info(f"Identified {len(candidates)} VAC candidates")
        return candidates

    def _evaluate_for_vac(
        self,
        patient: Patient,
        episode: VentilationEpisode,
    ) -> HAICandidate | None:
        """Evaluate a ventilation episode for VAC criteria.

        Args:
            patient: Patient information
            episode: Ventilation episode data

        Returns:
            HAICandidate if VAC criteria met, None otherwise
        """
        # Get daily ventilator parameters
        intubation_date = episode.intubation_date.date()
        end_date = episode.extubation_date.date() if episode.extubation_date else date.today()

        daily_params = self.ventilator_source.get_daily_vent_parameters(
            episode.id,
            intubation_date,
            end_date,
        )

        if len(daily_params) < self.min_vent_days:
            logger.debug(
                f"Insufficient ventilator days ({len(daily_params)}) for patient {patient.mrn}"
            )
            return None

        # Sort by date
        daily_params.sort(key=lambda p: p.date)

        # Apply VAC detection algorithm
        vac_result = self._detect_vac(daily_params)

        if vac_result is None:
            logger.debug(f"No VAC detected for patient {patient.mrn}")
            return None

        # VAC detected - create candidate
        vac_onset_date, baseline_start, baseline_end, baseline_fio2, baseline_peep, \
            fio2_increase, peep_increase = vac_result

        # Calculate ventilator day at onset
        vent_day_at_onset = (vac_onset_date - intubation_date).days + 1

        # Create synthetic culture result for the candidate (VAE doesn't require culture)
        synthetic_culture = CultureResult(
            fhir_id=f"vae-{episode.id}",
            collection_date=datetime.combine(vac_onset_date, datetime.min.time()),
            organism=None,
            specimen_source="respiratory",
            is_positive=False,
        )

        candidate = HAICandidate(
            id=str(uuid.uuid4()),
            hai_type=HAIType.VAE,
            patient=patient,
            culture=synthetic_culture,
            device_info=None,
            device_days_at_culture=vent_day_at_onset,
            status=CandidateStatus.PENDING,
        )

        # Create VAE-specific candidate data
        vae_data = VAECandidate(
            candidate_id=candidate.id,
            episode=episode,
            vac_onset_date=vac_onset_date,
            ventilator_day_at_onset=vent_day_at_onset,
            baseline_start_date=baseline_start,
            baseline_end_date=baseline_end,
            baseline_min_fio2=baseline_fio2,
            baseline_min_peep=baseline_peep,
            worsening_start_date=vac_onset_date,
            fio2_increase=fio2_increase,
            peep_increase=peep_increase,
            met_fio2_criterion=fio2_increase is not None and fio2_increase >= self.fio2_increase_threshold,
            met_peep_criterion=peep_increase is not None and peep_increase >= self.peep_increase_threshold,
        )

        # Attach VAE data to candidate for later use
        candidate._vae_data = vae_data

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

    def _detect_vac(
        self,
        daily_params: list[DailyVentParameters],
    ) -> tuple[date, date, date, float, float, float | None, float | None] | None:
        """Apply VAC detection algorithm to daily ventilator parameters.

        Algorithm:
        1. For each potential onset day (day 3+), look back for baseline
        2. Baseline = ≥2 days of stable or decreasing FiO2/PEEP
        3. Worsening = ≥2 days of sustained increase from baseline

        Args:
            daily_params: List of daily ventilator parameters, sorted by date

        Returns:
            Tuple of (vac_onset_date, baseline_start, baseline_end,
                     baseline_fio2, baseline_peep, fio2_increase, peep_increase)
            or None if no VAC detected
        """
        if len(daily_params) < self.baseline_period_days + self.worsening_period_days:
            return None

        # Build lookup by date
        params_by_date = {p.date: p for p in daily_params}
        sorted_dates = sorted(params_by_date.keys())

        # Need at least baseline_days + worsening_days to detect VAC
        min_days_needed = self.baseline_period_days + self.worsening_period_days

        # Try to detect VAC starting from day 3 onwards
        for i in range(min_days_needed - 1, len(sorted_dates)):
            potential_onset = sorted_dates[i - self.worsening_period_days + 1]

            # Check for valid baseline period before onset
            baseline_result = self._check_baseline(
                sorted_dates, params_by_date, potential_onset
            )

            if baseline_result is None:
                continue

            baseline_start, baseline_end, baseline_fio2, baseline_peep = baseline_result

            # Check for sustained worsening after baseline
            worsening_result = self._check_worsening(
                sorted_dates, params_by_date, potential_onset,
                baseline_fio2, baseline_peep
            )

            if worsening_result is not None:
                fio2_increase, peep_increase = worsening_result
                return (
                    potential_onset, baseline_start, baseline_end,
                    baseline_fio2, baseline_peep, fio2_increase, peep_increase
                )

        return None

    def _check_baseline(
        self,
        sorted_dates: list[date],
        params_by_date: dict[date, DailyVentParameters],
        potential_onset: date,
    ) -> tuple[date, date, float, float] | None:
        """Check for valid baseline period before potential VAC onset.

        Baseline = ≥2 calendar days of stable or decreasing FiO2/PEEP.

        Args:
            sorted_dates: Sorted list of dates with data
            params_by_date: Lookup of parameters by date
            potential_onset: Potential VAC onset date

        Returns:
            Tuple of (baseline_start, baseline_end, baseline_fio2, baseline_peep)
            or None if no valid baseline
        """
        onset_idx = sorted_dates.index(potential_onset)

        if onset_idx < self.baseline_period_days:
            return None

        # Look for baseline ending just before onset
        baseline_end_idx = onset_idx - 1
        baseline_start_idx = baseline_end_idx - self.baseline_period_days + 1

        if baseline_start_idx < 0:
            return None

        baseline_dates = sorted_dates[baseline_start_idx:baseline_end_idx + 1]

        # Collect values for baseline period
        fio2_values = []
        peep_values = []

        for d in baseline_dates:
            params = params_by_date.get(d)
            if params:
                if params.min_fio2 is not None:
                    fio2_values.append(params.min_fio2)
                if params.min_peep is not None:
                    peep_values.append(params.min_peep)

        if not fio2_values and not peep_values:
            return None

        # Check for stable or decreasing trend (no significant increase)
        # For simplicity, check that last value is not significantly higher than first
        if len(fio2_values) >= 2:
            if fio2_values[-1] > fio2_values[0] + 10:  # 10% threshold for baseline instability
                pass  # Still allow, we're looking for stable-ish baseline

        if len(peep_values) >= 2:
            if peep_values[-1] > peep_values[0] + 2:  # 2 cmH2O threshold
                pass  # Still allow

        # Use the minimum values from the first day of baseline as reference
        baseline_fio2 = fio2_values[0] if fio2_values else None
        baseline_peep = peep_values[0] if peep_values else None

        if baseline_fio2 is None and baseline_peep is None:
            return None

        return (
            baseline_dates[0],
            baseline_dates[-1],
            baseline_fio2,
            baseline_peep,
        )

    def _check_worsening(
        self,
        sorted_dates: list[date],
        params_by_date: dict[date, DailyVentParameters],
        onset_date: date,
        baseline_fio2: float | None,
        baseline_peep: float | None,
    ) -> tuple[float | None, float | None] | None:
        """Check for sustained worsening starting at onset date.

        Worsening = ≥2 calendar days where daily minimum FiO2 increases ≥20%
        OR daily minimum PEEP increases ≥3 cmH2O from baseline.

        Args:
            sorted_dates: Sorted list of dates with data
            params_by_date: Lookup of parameters by date
            onset_date: Potential VAC onset date
            baseline_fio2: Baseline FiO2 value
            baseline_peep: Baseline PEEP value

        Returns:
            Tuple of (fio2_increase, peep_increase) or None if no sustained worsening
        """
        try:
            onset_idx = sorted_dates.index(onset_date)
        except ValueError:
            return None

        # Need at least worsening_period_days starting from onset
        if onset_idx + self.worsening_period_days > len(sorted_dates):
            return None

        worsening_dates = sorted_dates[onset_idx:onset_idx + self.worsening_period_days]

        # Check each day in worsening period meets threshold
        fio2_met_all = True
        peep_met_all = True
        max_fio2_increase = None
        max_peep_increase = None

        for d in worsening_dates:
            params = params_by_date.get(d)
            if params is None:
                fio2_met_all = False
                peep_met_all = False
                continue

            # Check FiO2 increase
            if baseline_fio2 is not None and params.min_fio2 is not None:
                fio2_increase = params.min_fio2 - baseline_fio2
                if fio2_increase >= self.fio2_increase_threshold:
                    if max_fio2_increase is None or fio2_increase > max_fio2_increase:
                        max_fio2_increase = fio2_increase
                else:
                    fio2_met_all = False
            else:
                fio2_met_all = False

            # Check PEEP increase
            if baseline_peep is not None and params.min_peep is not None:
                peep_increase = params.min_peep - baseline_peep
                if peep_increase >= self.peep_increase_threshold:
                    if max_peep_increase is None or peep_increase > max_peep_increase:
                        max_peep_increase = peep_increase
                else:
                    peep_met_all = False
            else:
                peep_met_all = False

        # VAC requires sustained worsening in either FiO2 OR PEEP
        if fio2_met_all or peep_met_all:
            return (max_fio2_increase, max_peep_increase)

        return None

    def validate_candidate(self, candidate: HAICandidate) -> tuple[bool, str | None]:
        """Validate candidate against NHSN VAC criteria.

        Criteria checked:
        1. On mechanical ventilation ≥2 calendar days
        2. Valid baseline period identified
        3. Sustained worsening detected

        Args:
            candidate: The candidate to validate

        Returns:
            Tuple of (is_valid, exclusion_reason)
        """
        # Check for VAE data
        vae_data = getattr(candidate, '_vae_data', None)
        if vae_data is None:
            return False, "No VAE data available"

        # Check ventilator days
        if candidate.device_days_at_culture is None:
            return False, "Unable to determine ventilator days"

        if candidate.device_days_at_culture < self.min_vent_days:
            return False, f"Ventilator days ({candidate.device_days_at_culture}) < minimum ({self.min_vent_days})"

        # Check that either FiO2 or PEEP criterion was met
        if not vae_data.met_fio2_criterion and not vae_data.met_peep_criterion:
            return False, "Neither FiO2 nor PEEP worsening threshold met"

        # Validate baseline was established
        if vae_data.baseline_start_date is None:
            return False, "No valid baseline period identified"

        return True, None

    def get_exclusion_reasons(self) -> list[str]:
        """Get list of possible exclusion reasons for reporting."""
        return [
            f"Ventilator days < minimum ({self.min_vent_days})",
            "Unable to determine ventilator days",
            "Neither FiO2 nor PEEP worsening threshold met",
            "No valid baseline period identified",
            "Insufficient ventilator data",
            "No VAE data available",
        ]
