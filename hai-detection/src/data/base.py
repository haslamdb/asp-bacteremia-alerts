"""Abstract base classes for data source abstraction."""

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import ClinicalNote, DeviceInfo, CultureResult, Patient


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
