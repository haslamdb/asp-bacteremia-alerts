"""Factory functions for data source creation."""

import logging

from ..config import Config
from .base import BaseNoteSource, BaseDeviceSource, BaseCultureSource, BaseVentilatorSource
from .fhir_source import FHIRNoteSource, FHIRDeviceSource, FHIRCultureSource, FHIRVentilatorSource
from .clarity_source import ClarityNoteSource, ClarityDeviceSource, ClarityCultureSource
from .procedure_source import (
    BaseProcedureSource,
    MockProcedureSource,
    FHIRProcedureSource,
    ClarityProcedureSource,
)

logger = logging.getLogger(__name__)


def get_note_source(source_type: str | None = None) -> BaseNoteSource:
    """Get the configured note source.

    Args:
        source_type: Override source type (fhir, clarity). Uses config if not specified.

    Returns:
        Configured note source implementation.
    """
    source = source_type or Config.NOTE_SOURCE

    if source == "clarity":
        if not Config.is_clarity_configured():
            logger.warning("Clarity not configured, falling back to FHIR")
            return FHIRNoteSource()
        return ClarityNoteSource()

    if source == "both":
        # Return a composite source that tries both
        return CompositeNoteSource()

    # Default to FHIR
    return FHIRNoteSource()


def get_device_source(source_type: str | None = None) -> BaseDeviceSource:
    """Get the configured device source.

    Args:
        source_type: Override source type (fhir, clarity). Uses config if not specified.

    Returns:
        Configured device source implementation.
    """
    source = source_type or Config.NOTE_SOURCE  # Use same source as notes

    if source == "clarity":
        if not Config.is_clarity_configured():
            logger.warning("Clarity not configured, falling back to FHIR")
            return FHIRDeviceSource()
        return ClarityDeviceSource()

    # Default to FHIR
    return FHIRDeviceSource()


def get_culture_source(source_type: str | None = None) -> BaseCultureSource:
    """Get the configured culture source.

    Args:
        source_type: Override source type (fhir, clarity). Uses config if not specified.

    Returns:
        Configured culture source implementation.
    """
    source = source_type or Config.NOTE_SOURCE

    if source == "clarity":
        if not Config.is_clarity_configured():
            logger.warning("Clarity not configured, falling back to FHIR")
            return FHIRCultureSource()
        return ClarityCultureSource()

    # Default to FHIR
    return FHIRCultureSource()


class CompositeNoteSource(BaseNoteSource):
    """Composite note source that queries both FHIR and Clarity."""

    def __init__(self):
        self.fhir_source = FHIRNoteSource()
        self.clarity_source = None
        if Config.is_clarity_configured():
            self.clarity_source = ClarityNoteSource()

    def get_notes_for_patient(
        self,
        patient_id: str,
        start_date,
        end_date,
        note_types=None,
    ):
        """Get notes from both sources and deduplicate."""
        from datetime import datetime

        notes = []
        seen_dates = set()

        # Try FHIR first
        try:
            fhir_notes = self.fhir_source.get_notes_for_patient(
                patient_id, start_date, end_date, note_types
            )
            for note in fhir_notes:
                key = (note.date.isoformat() if isinstance(note.date, datetime) else note.date, note.note_type)
                if key not in seen_dates:
                    notes.append(note)
                    seen_dates.add(key)
        except Exception as e:
            logger.warning(f"FHIR note retrieval failed: {e}")

        # Try Clarity if configured
        if self.clarity_source:
            try:
                clarity_notes = self.clarity_source.get_notes_for_patient(
                    patient_id, start_date, end_date, note_types
                )
                for note in clarity_notes:
                    key = (note.date.isoformat() if isinstance(note.date, datetime) else note.date, note.note_type)
                    if key not in seen_dates:
                        notes.append(note)
                        seen_dates.add(key)
            except Exception as e:
                logger.warning(f"Clarity note retrieval failed: {e}")

        # Sort by date descending
        notes.sort(key=lambda n: n.date, reverse=True)
        return notes

    def get_note_by_id(self, note_id: str):
        """Try to get note from FHIR first, then Clarity."""
        note = self.fhir_source.get_note_by_id(note_id)
        if note:
            return note

        if self.clarity_source:
            return self.clarity_source.get_note_by_id(note_id)

        return None


def get_procedure_source(source_type: str | None = None) -> BaseProcedureSource:
    """Get the configured procedure source for SSI monitoring.

    Args:
        source_type: Override source type (mock, fhir, clarity). Uses config if not specified.

    Returns:
        Configured procedure source implementation.
    """
    source = source_type or getattr(Config, "PROCEDURE_SOURCE", "mock")

    if source == "clarity":
        if not Config.is_clarity_configured():
            logger.warning("Clarity not configured, falling back to mock")
            return MockProcedureSource()
        return ClarityProcedureSource()

    if source == "fhir":
        return FHIRProcedureSource()

    # Default to mock for development
    return MockProcedureSource()


def get_ventilator_source(source_type: str | None = None) -> BaseVentilatorSource:
    """Get the configured ventilator source for VAE monitoring.

    Args:
        source_type: Override source type (fhir). Uses config if not specified.

    Returns:
        Configured ventilator source implementation.
    """
    source = source_type or getattr(Config, "VENTILATOR_SOURCE", "fhir")

    # Currently only FHIR source is implemented
    # Clarity ventilator source could be added in the future
    return FHIRVentilatorSource()
