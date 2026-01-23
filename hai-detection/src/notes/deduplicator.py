"""Note deduplication to handle copy-forward noise.

Clinical notes often contain copy-forwarded content from previous notes,
which can introduce noise and redundancy for LLM analysis. This module
helps identify and reduce such duplication.
"""

import hashlib
import logging
import re
from collections import defaultdict

from ..models import ClinicalNote

logger = logging.getLogger(__name__)


class NoteDeduplicator:
    """Identifies and filters duplicated content in clinical notes."""

    # Minimum paragraph length to consider for deduplication
    MIN_PARAGRAPH_LENGTH = 100

    # Similarity threshold for considering paragraphs as duplicates
    SIMILARITY_THRESHOLD = 0.9

    def __init__(self):
        self._seen_hashes: dict[str, str] = {}  # hash -> first occurrence note_id

    def deduplicate_notes(
        self,
        notes: list[ClinicalNote],
        remove_duplicates: bool = False,
    ) -> list[ClinicalNote]:
        """Process notes to identify and optionally remove duplicates.

        Args:
            notes: Notes to process (should be sorted by date)
            remove_duplicates: If True, remove duplicate paragraphs

        Returns:
            Processed notes with duplicates marked/removed
        """
        self._seen_hashes.clear()
        processed = []

        # Sort by date (oldest first) to identify original vs copied
        sorted_notes = sorted(notes, key=lambda n: n.date)

        for note in sorted_notes:
            if remove_duplicates:
                deduped_content = self._remove_duplicate_paragraphs(note)
                processed_note = ClinicalNote(
                    id=note.id,
                    patient_id=note.patient_id,
                    note_type=note.note_type,
                    author=note.author,
                    date=note.date,
                    content=deduped_content,
                    source=note.source,
                )
                processed.append(processed_note)
            else:
                # Just track duplicates, don't modify
                self._track_paragraphs(note)
                processed.append(note)

        # Restore original order (most recent first typically)
        processed.sort(key=lambda n: n.date, reverse=True)
        return processed

    def _track_paragraphs(self, note: ClinicalNote) -> None:
        """Track paragraph hashes to identify duplicates."""
        paragraphs = self._split_into_paragraphs(note.content)

        for para in paragraphs:
            if len(para) < self.MIN_PARAGRAPH_LENGTH:
                continue

            para_hash = self._hash_paragraph(para)
            if para_hash not in self._seen_hashes:
                self._seen_hashes[para_hash] = note.id

    def _remove_duplicate_paragraphs(self, note: ClinicalNote) -> str:
        """Remove paragraphs that were seen in earlier notes."""
        paragraphs = self._split_into_paragraphs(note.content)
        kept_paragraphs = []

        for para in paragraphs:
            if len(para) < self.MIN_PARAGRAPH_LENGTH:
                kept_paragraphs.append(para)
                continue

            para_hash = self._hash_paragraph(para)

            if para_hash in self._seen_hashes:
                # This paragraph was seen before
                original_note = self._seen_hashes[para_hash]
                if original_note != note.id:
                    # Skip duplicate, add marker
                    kept_paragraphs.append("[Content copied from previous note]")
                    continue

            # Track and keep this paragraph
            self._seen_hashes[para_hash] = note.id
            kept_paragraphs.append(para)

        return "\n\n".join(kept_paragraphs)

    def _split_into_paragraphs(self, content: str) -> list[str]:
        """Split note content into paragraphs."""
        # Split on double newlines or common section markers
        paragraphs = re.split(r'\n\s*\n|\n(?=[A-Z][A-Z\s]+:)', content)
        return [p.strip() for p in paragraphs if p.strip()]

    def _hash_paragraph(self, paragraph: str) -> str:
        """Create a hash for paragraph comparison.

        Normalizes whitespace and case for comparison.
        """
        # Normalize: lowercase, collapse whitespace
        normalized = re.sub(r'\s+', ' ', paragraph.lower().strip())
        return hashlib.md5(normalized.encode()).hexdigest()

    def get_duplication_stats(self, notes: list[ClinicalNote]) -> dict:
        """Calculate duplication statistics for a set of notes.

        Returns:
            Dict with duplication metrics
        """
        self._seen_hashes.clear()
        total_paragraphs = 0
        duplicate_paragraphs = 0
        total_chars = 0
        duplicate_chars = 0

        sorted_notes = sorted(notes, key=lambda n: n.date)

        for note in sorted_notes:
            paragraphs = self._split_into_paragraphs(note.content)

            for para in paragraphs:
                if len(para) < self.MIN_PARAGRAPH_LENGTH:
                    continue

                total_paragraphs += 1
                total_chars += len(para)
                para_hash = self._hash_paragraph(para)

                if para_hash in self._seen_hashes:
                    original_note = self._seen_hashes[para_hash]
                    if original_note != note.id:
                        duplicate_paragraphs += 1
                        duplicate_chars += len(para)
                else:
                    self._seen_hashes[para_hash] = note.id

        return {
            "total_paragraphs": total_paragraphs,
            "duplicate_paragraphs": duplicate_paragraphs,
            "duplication_rate": duplicate_paragraphs / max(total_paragraphs, 1),
            "total_chars": total_chars,
            "duplicate_chars": duplicate_chars,
            "char_duplication_rate": duplicate_chars / max(total_chars, 1),
        }
