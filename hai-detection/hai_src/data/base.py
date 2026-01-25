"""Abstract base classes for data source abstraction."""

from abc import ABC, abstractmethod
from datetime import datetime, date

from ..models import ClinicalNote, DeviceInfo, CultureResult, Patient, VentilationEpisode, DailyVentParameters


class BaseNoteSource(ABC):
    """Abstract base class for clinical note retrieval."""

    @abstractmethod
    def get_notes_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
        note_types: list[str] | None = None,
    ) -> list[ClinicalNote]:
        """Retrieve clinical notes for a patient within a date range.

        Args:
            patient_id: FHIR patient ID or MRN depending on source
            start_date: Start of date range
            end_date: End of date range
            note_types: Optional filter for note types (e.g., ["progress_note", "id_consult"])

        Returns:
            List of clinical notes
        """
        pass

    @abstractmethod
    def get_note_by_id(self, note_id: str) -> ClinicalNote | None:
        """Retrieve a specific note by ID."""
        pass


class BaseDeviceSource(ABC):
    """Abstract base class for device/procedure data retrieval."""

    @abstractmethod
    def get_central_lines(
        self,
        patient_id: str,
        as_of_date: datetime,
    ) -> list[DeviceInfo]:
        """Get central lines for a patient that were present at a given date.

        Args:
            patient_id: FHIR patient ID or MRN
            as_of_date: Date to check for line presence

        Returns:
            List of central lines present at that date
        """
        pass

    @abstractmethod
    def get_active_devices(
        self,
        patient_id: str,
        device_types: list[str] | None = None,
    ) -> list[DeviceInfo]:
        """Get currently active devices for a patient.

        Args:
            patient_id: FHIR patient ID or MRN
            device_types: Optional filter for device types

        Returns:
            List of active devices
        """
        pass


class BaseCultureSource(ABC):
    """Abstract base class for culture/microbiology data retrieval."""

    @abstractmethod
    def get_positive_blood_cultures(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[tuple[Patient, CultureResult]]:
        """Get positive blood cultures within a date range.

        Args:
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of (Patient, CultureResult) tuples
        """
        pass

    @abstractmethod
    def get_cultures_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CultureResult]:
        """Get cultures for a specific patient."""
        pass


class BaseVentilatorSource(ABC):
    """Abstract base class for mechanical ventilation data retrieval.

    Used for VAE (Ventilator-Associated Event) surveillance.
    """

    @abstractmethod
    def get_ventilated_patients(
        self,
        start_date: datetime,
        end_date: datetime,
        min_vent_days: int = 2,
    ) -> list[tuple[Patient, VentilationEpisode]]:
        """Get patients on mechanical ventilation within a date range.

        Args:
            start_date: Start of date range
            end_date: End of date range
            min_vent_days: Minimum ventilator days required (default 2 for VAE eligibility)

        Returns:
            List of (Patient, VentilationEpisode) tuples
        """
        pass

    @abstractmethod
    def get_daily_vent_parameters(
        self,
        episode_id: str,
        start_date: date,
        end_date: date,
    ) -> list[DailyVentParameters]:
        """Get daily ventilator parameters for a ventilation episode.

        Retrieves the minimum FiO2 and PEEP values for each calendar day,
        which are used to detect VAC (Ventilator-Associated Condition).

        Args:
            episode_id: Ventilation episode ID
            start_date: Start date for parameter retrieval
            end_date: End date for parameter retrieval

        Returns:
            List of DailyVentParameters, one per day
        """
        pass

    @abstractmethod
    def get_ventilation_episodes_for_patient(
        self,
        patient_id: str,
        start_date: datetime,
        end_date: datetime,
    ) -> list[VentilationEpisode]:
        """Get ventilation episodes for a specific patient.

        Args:
            patient_id: FHIR patient ID or MRN
            start_date: Start of date range
            end_date: End of date range

        Returns:
            List of VentilationEpisode objects
        """
        pass
