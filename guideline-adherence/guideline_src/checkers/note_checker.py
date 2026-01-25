"""Note-based element checker for documentation requirements."""

from datetime import datetime, timedelta
import logging
import re
import sys
from pathlib import Path

# Add parent paths for imports
GUIDELINE_ADHERENCE_PATH = Path(__file__).parent.parent.parent
if str(GUIDELINE_ADHERENCE_PATH) not in sys.path:
    sys.path.insert(0, str(GUIDELINE_ADHERENCE_PATH))

from guideline_adherence import BundleElement

from ..models import ElementCheckResult, ElementCheckStatus
from .base import ElementChecker

logger = logging.getLogger(__name__)


# Note type LOINC codes
NOTE_TYPES = {
    "id_consult": ["11488-4", "34117-2"],  # ID consult note
    "asp_review": ["11488-4"],  # Progress note (ASP)
    "progress_note": ["11506-3"],  # General progress note
    "procedure_note": ["28570-0"],  # Procedure note
}

# Keywords indicating reassessment/review
REASSESSMENT_KEYWORDS = [
    "reassessment",
    "antibiotic review",
    "antimicrobial review",
    "asp review",
    "stewardship review",
    "day 2 review",
    "day 3 review",
    "48 hour",
    "48h review",
    "72 hour",
    "culture review",
    "de-escalation",
    "narrowing",
    "spectrum",
    "id consult",
    "infectious disease",
]


class NoteChecker(ElementChecker):
    """Check note-based bundle elements."""

    def check(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
    ) -> ElementCheckResult:
        """Check if a documentation element has been completed.

        Args:
            element: The bundle element to check.
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered.

        Returns:
            ElementCheckResult with status.
        """
        # Route to appropriate checker based on element type
        if "reassess" in element.element_id or "48h" in element.element_id:
            return self._check_reassessment(element, patient_id, trigger_time)
        elif "margin" in element.element_id:
            return self._check_margins_marked(element, patient_id, trigger_time)
        elif "risk_stratification" in element.element_id:
            return self._check_risk_stratification(element, patient_id, trigger_time)
        else:
            # Generic note check
            return self._check_generic_documentation(element, patient_id, trigger_time)

    def _check_reassessment(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
    ) -> ElementCheckResult:
        """Check for 48-72h antibiotic reassessment documentation.

        Args:
            element: The bundle element to check.
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered.

        Returns:
            ElementCheckResult with status.
        """
        # Reassessment window is typically 48-72h after trigger
        reassess_start = trigger_time + timedelta(hours=48)
        reassess_end = trigger_time + timedelta(hours=72)
        now = datetime.now()

        # If we're not yet at 48h, element is pending
        if now < reassess_start:
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes=f"Reassessment window opens at 48h ({reassess_start.strftime('%Y-%m-%d %H:%M')})",
            )

        # Get notes from the past 72h
        notes = self.fhir_client.get_recent_notes(
            patient_id=patient_id,
            since_hours=72,
            note_types=NOTE_TYPES.get("id_consult", []) + NOTE_TYPES.get("progress_note", []),
        )

        # Look for reassessment documentation in the 48-72h window
        for note in notes:
            note_date = note.get("date")
            if note_date:
                if isinstance(note_date, str):
                    try:
                        note_date = datetime.fromisoformat(note_date.replace("Z", "+00:00"))
                    except ValueError:
                        continue

                # Check if note is in reassessment window
                if reassess_start <= note_date <= reassess_end:
                    note_text = note.get("text", "").lower()
                    # Check for reassessment keywords
                    if any(kw in note_text for kw in REASSESSMENT_KEYWORDS):
                        return self._create_result(
                            element=element,
                            status=ElementCheckStatus.MET,
                            trigger_time=trigger_time,
                            completed_at=note_date,
                            value=note.get("type", "Note"),
                            notes=f"Reassessment documented in {note.get('type', 'note')}",
                        )

        # No reassessment found
        if now < reassess_end:
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes=f"In reassessment window (48-72h) - awaiting documentation. Window closes: {reassess_end.strftime('%Y-%m-%d %H:%M')}",
            )
        else:
            return self._create_result(
                element=element,
                status=ElementCheckStatus.NOT_MET,
                trigger_time=trigger_time,
                notes="72h window expired - no reassessment documentation found",
            )

    def _check_margins_marked(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
    ) -> ElementCheckResult:
        """Check if cellulitis margins were marked (nursing documentation).

        Args:
            element: The bundle element to check.
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered.

        Returns:
            ElementCheckResult with status.
        """
        # Get recent nursing notes
        notes = self.fhir_client.get_recent_notes(
            patient_id=patient_id,
            since_hours=24,
        )

        margin_keywords = [
            "margins marked",
            "borders marked",
            "demarcated",
            "outlined",
            "border outlined",
            "circumscribed",
        ]

        for note in notes:
            note_text = note.get("text", "").lower()
            note_date = note.get("date")

            if any(kw in note_text for kw in margin_keywords):
                if isinstance(note_date, str):
                    try:
                        note_date = datetime.fromisoformat(note_date.replace("Z", "+00:00"))
                    except ValueError:
                        note_date = None

                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.MET,
                    trigger_time=trigger_time,
                    completed_at=note_date,
                    notes="Cellulitis margins marked per documentation",
                )

        if self._is_within_window(trigger_time, element.time_window_hours):
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes="Awaiting documentation of cellulitis margins",
            )

        return self._create_result(
            element=element,
            status=ElementCheckStatus.NOT_MET,
            trigger_time=trigger_time,
            notes="Time window expired - no documentation of margins marked",
        )

    def _check_risk_stratification(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
    ) -> ElementCheckResult:
        """Check for risk stratification documentation (e.g., febrile neutropenia).

        Args:
            element: The bundle element to check.
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered.

        Returns:
            ElementCheckResult with status.
        """
        notes = self.fhir_client.get_recent_notes(
            patient_id=patient_id,
            since_hours=48,
        )

        risk_keywords = [
            "high risk",
            "low risk",
            "risk stratification",
            "risk assessment",
            "mascc score",
            "risk category",
            "risk classification",
        ]

        for note in notes:
            note_text = note.get("text", "").lower()
            note_date = note.get("date")

            if any(kw in note_text for kw in risk_keywords):
                if isinstance(note_date, str):
                    try:
                        note_date = datetime.fromisoformat(note_date.replace("Z", "+00:00"))
                    except ValueError:
                        note_date = None

                # Determine which risk category was documented
                risk_level = "documented"
                if "high risk" in note_text:
                    risk_level = "high risk"
                elif "low risk" in note_text:
                    risk_level = "low risk"

                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.MET,
                    trigger_time=trigger_time,
                    completed_at=note_date,
                    value=risk_level,
                    notes=f"Risk stratification: {risk_level}",
                )

        if self._is_within_window(trigger_time, element.time_window_hours):
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes="Awaiting risk stratification documentation",
            )

        return self._create_result(
            element=element,
            status=ElementCheckStatus.NOT_MET,
            trigger_time=trigger_time,
            notes="Time window expired - no risk stratification documented",
        )

    def _check_generic_documentation(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
    ) -> ElementCheckResult:
        """Generic check for documentation-based elements.

        Args:
            element: The bundle element to check.
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered.

        Returns:
            ElementCheckResult with status.
        """
        # Extract keywords from element description
        description = element.description.lower()
        keywords = self._extract_keywords(description)

        if not keywords:
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes="Unable to determine documentation requirements",
            )

        # Get recent notes
        hours_to_check = element.time_window_hours or 72
        notes = self.fhir_client.get_recent_notes(
            patient_id=patient_id,
            since_hours=int(hours_to_check),
        )

        for note in notes:
            note_text = note.get("text", "").lower()
            note_date = note.get("date")

            if any(kw in note_text for kw in keywords):
                if isinstance(note_date, str):
                    try:
                        note_date = datetime.fromisoformat(note_date.replace("Z", "+00:00"))
                    except ValueError:
                        note_date = None

                return self._create_result(
                    element=element,
                    status=ElementCheckStatus.MET,
                    trigger_time=trigger_time,
                    completed_at=note_date,
                    notes=f"Documentation found matching: {element.name}",
                )

        if self._is_within_window(trigger_time, element.time_window_hours):
            return self._create_result(
                element=element,
                status=ElementCheckStatus.PENDING,
                trigger_time=trigger_time,
                notes=f"Awaiting documentation for: {element.name}",
            )

        return self._create_result(
            element=element,
            status=ElementCheckStatus.NOT_MET,
            trigger_time=trigger_time,
            notes=f"No documentation found for: {element.name}",
        )

    def _extract_keywords(self, text: str) -> list[str]:
        """Extract likely keywords from element description.

        Args:
            text: Element description text.

        Returns:
            List of keywords to search for.
        """
        # Remove common words
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "been",
            "being", "have", "has", "had", "do", "does", "did", "will",
            "would", "could", "should", "may", "might", "must", "shall",
            "can", "need", "dare", "ought", "used", "to", "of", "in",
            "for", "on", "with", "at", "by", "from", "as", "into",
            "through", "during", "before", "after", "above", "below",
            "between", "under", "again", "further", "then", "once",
            "here", "there", "when", "where", "why", "how", "all",
            "each", "few", "more", "most", "other", "some", "such",
            "no", "nor", "not", "only", "own", "same", "so", "than",
            "too", "very", "just", "and", "but", "if", "or", "because",
            "until", "while", "documented", "documentation",
        }

        # Extract words
        words = re.findall(r"\b\w+\b", text.lower())
        keywords = [w for w in words if w not in stop_words and len(w) > 3]

        # Also look for multi-word phrases
        phrases = [
            "blood culture",
            "id consult",
            "infectious disease",
            "follow up",
            "risk assessment",
        ]
        for phrase in phrases:
            if phrase in text:
                keywords.append(phrase)

        return keywords[:10]  # Limit to top 10
