"""Clinical note retrieval for LLM context."""

import logging
from datetime import datetime, timedelta

from ..config import Config
from ..models import ClinicalNote, HAICandidate
from ..data.factory import get_note_source

logger = logging.getLogger(__name__)


class NoteRetriever:
    """Retrieves clinical notes for HAI candidate context."""

    # Note types relevant for CLABSI evaluation
    RELEVANT_NOTE_TYPES = [
        "progress_note",
        "id_consult",
        "discharge_summary",
        "h_and_p",
        "nursing_note",
    ]

    def __init__(self, note_source=None):
        """Initialize retriever.

        Args:
            note_source: Note source to use. Uses factory default if None.
        """
        self.note_source = note_source or get_note_source()
        self.max_notes = Config.MAX_NOTES_PER_PATIENT
        self.max_length = Config.MAX_NOTE_LENGTH

    def get_notes_for_candidate(
        self,
        candidate: HAICandidate,
        days_before: int = 7,
        days_after: int = 3,
    ) -> list[ClinicalNote]:
        """Get clinical notes relevant to an HAI candidate.

        Retrieves notes around the culture date to provide context
        for LLM classification.

        Args:
            candidate: The HAI candidate to get notes for
            days_before: Days before culture to retrieve
            days_after: Days after culture to retrieve

        Returns:
            List of relevant clinical notes, sorted by date
        """
        culture_date = candidate.culture.collection_date
        start_date = culture_date - timedelta(days=days_before)
        end_date = culture_date + timedelta(days=days_after)

        logger.info(
            f"Retrieving notes for patient {candidate.patient.mrn} "
            f"from {start_date.date()} to {end_date.date()}"
        )

        try:
            notes = self.note_source.get_notes_for_patient(
                patient_id=candidate.patient.fhir_id,
                start_date=start_date,
                end_date=end_date,
                note_types=self.RELEVANT_NOTE_TYPES,
            )

            logger.info(f"Retrieved {len(notes)} notes")

            # Sort by date (most recent first for relevance)
            notes.sort(key=lambda n: n.date, reverse=True)

            # Limit number of notes
            if len(notes) > self.max_notes:
                logger.info(f"Limiting to {self.max_notes} most recent notes")
                notes = notes[:self.max_notes]

            return notes

        except Exception as e:
            logger.error(f"Failed to retrieve notes: {e}")
            return []

    def get_id_consults(
        self,
        candidate: HAICandidate,
        days_before: int = 14,
        days_after: int = 7,
    ) -> list[ClinicalNote]:
        """Get ID (Infectious Disease) consult notes specifically.

        ID consults are particularly valuable for source attribution.
        """
        culture_date = candidate.culture.collection_date
        start_date = culture_date - timedelta(days=days_before)
        end_date = culture_date + timedelta(days=days_after)

        try:
            notes = self.note_source.get_notes_for_patient(
                patient_id=candidate.patient.fhir_id,
                start_date=start_date,
                end_date=end_date,
                note_types=["id_consult"],
            )

            notes.sort(key=lambda n: n.date, reverse=True)
            return notes

        except Exception as e:
            logger.error(f"Failed to retrieve ID consults: {e}")
            return []

    def truncate_notes(
        self,
        notes: list[ClinicalNote],
        max_total_length: int | None = None,
    ) -> list[ClinicalNote]:
        """Truncate notes to fit within LLM context limits.

        Args:
            notes: Notes to truncate
            max_total_length: Maximum total length. Uses config if None.

        Returns:
            Notes with content truncated if necessary
        """
        max_length = max_total_length or self.max_length
        truncated = []
        total_length = 0

        for note in notes:
            remaining = max_length - total_length
            if remaining <= 0:
                break

            if len(note.content) > remaining:
                # Truncate this note
                truncated_note = ClinicalNote(
                    id=note.id,
                    patient_id=note.patient_id,
                    note_type=note.note_type,
                    author=note.author,
                    date=note.date,
                    content=note.content[:remaining] + "\n[TRUNCATED]",
                    source=note.source,
                )
                truncated.append(truncated_note)
                break
            else:
                truncated.append(note)
                total_length += len(note.content)

        return truncated
