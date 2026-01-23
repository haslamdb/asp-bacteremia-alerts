"""Clinical note section extraction and chunking."""

import logging
import re
from dataclasses import dataclass

from ..models import ClinicalNote, NoteChunk

logger = logging.getLogger(__name__)


class NoteChunker:
    """Extracts relevant sections from clinical notes.

    Clinical notes often contain standard sections that are particularly
    relevant for HAI evaluation:
    - Assessment/Plan (A/P): Clinician's interpretation and plan
    - Physical Exam (PE): Findings relevant to infection
    - ID Section: Infectious disease specific content
    - Impression: Summary diagnosis
    """

    # Section header patterns (case-insensitive)
    SECTION_PATTERNS = {
        "assessment_plan": [
            r"(?:^|\n)(?:ASSESSMENT\s*[/&]?\s*PLAN|A/?P|IMPRESSION\s*(?:AND|&)?\s*PLAN)[:\s]*\n",
            r"(?:^|\n)(?:ASSESSMENT\s*(?:AND|&)?\s*PLAN)[:\s]*\n",
            r"(?:^|\n)(?:ASSESSMENT|IMPRESSION)[:\s]*\n",
            r"(?:^|\n)(?:PLAN)[:\s]*\n",
        ],
        "physical_exam": [
            r"(?:^|\n)(?:PHYSICAL\s*EXAM(?:INATION)?|PE)[:\s]*\n",
            r"(?:^|\n)(?:EXAM(?:INATION)?)[:\s]*\n",
        ],
        "id_section": [
            r"(?:^|\n)(?:INFECTIOUS\s*DISEASE|ID\s*SECTION|ID\s*NOTES?)[:\s]*\n",
            r"(?:^|\n)(?:MICROBIOLOGY|CULTURES?)[:\s]*\n",
        ],
        "hospital_course": [
            r"(?:^|\n)(?:HOSPITAL\s*COURSE|BRIEF\s*HOSPITAL\s*COURSE)[:\s]*\n",
        ],
        "active_problems": [
            r"(?:^|\n)(?:ACTIVE\s*PROBLEMS?|PROBLEM\s*LIST)[:\s]*\n",
        ],
    }

    # Common section end patterns
    SECTION_END_PATTERNS = [
        r"\n(?:[A-Z][A-Z\s]+:)",  # Next section header
        r"\n(?:_+|\-+|=+)\s*\n",  # Section dividers
        r"\n(?:Electronically signed|Signed by|Attending)",  # Signatures
    ]

    def extract_sections(
        self,
        note: ClinicalNote,
        section_types: list[str] | None = None,
    ) -> list[NoteChunk]:
        """Extract specific sections from a clinical note.

        Args:
            note: The clinical note to process
            section_types: Section types to extract. All if None.

        Returns:
            List of NoteChunks for found sections
        """
        if section_types is None:
            section_types = list(self.SECTION_PATTERNS.keys())

        chunks = []
        content = note.content

        for section_type in section_types:
            patterns = self.SECTION_PATTERNS.get(section_type, [])

            for pattern in patterns:
                match = re.search(pattern, content, re.IGNORECASE | re.MULTILINE)
                if match:
                    start_pos = match.end()
                    end_pos = self._find_section_end(content, start_pos)

                    section_content = content[start_pos:end_pos].strip()

                    if section_content:
                        chunks.append(NoteChunk(
                            note_id=note.id,
                            section_type=section_type,
                            content=section_content,
                            start_pos=start_pos,
                            end_pos=end_pos,
                        ))
                    break  # Found this section, move to next type

        return chunks

    def _find_section_end(self, content: str, start_pos: int) -> int:
        """Find where a section ends."""
        remaining = content[start_pos:]

        # Try each end pattern
        earliest_end = len(remaining)

        for pattern in self.SECTION_END_PATTERNS:
            match = re.search(pattern, remaining)
            if match and match.start() < earliest_end:
                earliest_end = match.start()

        return start_pos + earliest_end

    def extract_assessment_plan(self, note: ClinicalNote) -> str | None:
        """Extract the Assessment and Plan section."""
        chunks = self.extract_sections(note, ["assessment_plan"])
        if chunks:
            return chunks[0].content
        return None

    def extract_relevant_context(
        self,
        notes: list[ClinicalNote],
        max_length: int = 10000,
    ) -> str:
        """Extract and combine relevant context from multiple notes.

        Clinical notes may not follow standardized templates, so we:
        1. First try to extract known sections (A/P, ID)
        2. Fall back to full note content if no sections found

        Args:
            notes: Notes to extract from
            max_length: Maximum combined length

        Returns:
            Combined relevant context string
        """
        context_parts = []
        total_length = 0
        notes_with_sections = set()

        # First pass: Try to extract A/P and ID sections
        for note in notes[:10]:  # Check more notes
            chunks = self.extract_sections(note, ["assessment_plan", "id_section"])
            for chunk in chunks:
                if total_length + len(chunk.content) > max_length:
                    break

                section_label = "Assessment/Plan" if chunk.section_type == "assessment_plan" else "ID/Microbiology"
                author_str = f" by {note.author}" if note.author else ""
                context_parts.append(
                    f"[{note.note_type.upper()} - {note.date.strftime('%Y-%m-%d')}{author_str}]\n"
                    f"{section_label}:\n{chunk.content}"
                )
                total_length += len(chunk.content)
                notes_with_sections.add(note.id)

        # Second pass: Include full content from notes where we couldn't find sections
        # Clinical notes often don't have standardized headers
        for note in notes[:10]:
            if total_length >= max_length:
                break
            if note.id in notes_with_sections:
                continue  # Already extracted sections from this note

            # Use full note content (truncate if needed)
            content = note.content.strip()
            available_space = max_length - total_length
            if len(content) > available_space:
                content = content[:available_space] + "... [truncated]"

            if content:
                author_str = f" by {note.author}" if note.author else ""
                context_parts.append(
                    f"[{note.note_type.upper()} - {note.date.strftime('%Y-%m-%d')}{author_str}]\n"
                    f"Full Note:\n{content}"
                )
                total_length += len(content)

        return "\n\n---\n\n".join(context_parts)
