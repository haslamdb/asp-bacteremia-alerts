"""Clinical note retrieval for LLM context."""

import logging
import re
from datetime import datetime, timedelta

from ..config import Config
from ..models import ClinicalNote, HAICandidate, HAIType
from ..data.factory import get_note_source

logger = logging.getLogger(__name__)


# Keywords for pre-filtering notes by HAI type
# Notes containing these keywords are more likely to be relevant
HAI_KEYWORDS: dict[str, list[str]] = {
    "cdi": [
        # Symptoms
        "diarrhea", "loose stool", "watery stool", "bowel movement",
        "stool frequency", "stool output", "gi symptoms",
        # Organism
        "c. diff", "c diff", "cdiff", "c.diff", "clostridioides", "clostridium difficile",
        # Testing
        "toxin", "pcr", "eia", "gdh", "stool test", "stool sample",
        # Treatment
        "vancomycin oral", "vancomycin po", "oral vanc", "fidaxomicin", "dificid",
        "metronidazole", "flagyl", "bezlotoxumab", "zinplava", "fmt",
        "fecal transplant", "fecal microbiota",
        # Clinical context
        "colitis", "pseudomembranous", "megacolon", "ileus",
        "recurrence", "recurrent cdi", "prior cdi",
    ],
    "clabsi": [
        # Device terms
        "central line", "central venous", "cvc", "picc", "port-a-cath",
        "port a cath", "portacath", "hickman", "broviac", "tunneled catheter",
        "non-tunneled", "triple lumen", "double lumen", "hemodialysis catheter",
        "line days", "catheter days",
        # Infection terms
        "line infection", "catheter infection", "line sepsis", "crbsi",
        "bacteremia", "blood stream infection", "bsi", "blood culture",
        "positive culture", "grew", "organism",
        # Management
        "line removal", "catheter removal", "line exchange", "pull the line",
        "remove the line", "keep the line", "line salvage",
        # Clinical context
        "sepsis", "septic", "fever", "chills", "rigors",
        "erythema at site", "exit site", "tunnel infection", "purulence",
    ],
    "cauti": [
        # Device terms
        "foley", "urinary catheter", "indwelling catheter", "foley catheter",
        "catheter days", "foley days", "suprapubic catheter",
        # Infection terms
        "urinary tract infection", "uti", "urine culture", "cfu",
        "bacteriuria", "pyuria", "urosepsis",
        # Symptoms
        "dysuria", "frequency", "urgency", "suprapubic", "flank pain",
        "costovertebral", "cvat", "cloudy urine", "hematuria",
        # Organisms
        "e. coli", "e.coli", "klebsiella", "enterococcus", "pseudomonas",
        "proteus", "candida",
        # Management
        "remove foley", "discontinue foley", "catheter removal",
    ],
    "vae": [
        # Device terms
        "ventilator", "mechanical ventilation", "intubated", "endotracheal",
        "tracheostomy", "vent settings", "vent days",
        # Parameters
        "peep", "fio2", "oxygen requirement", "ventilator settings",
        "pressure support", "volume control", "pressure control",
        # Infection terms
        "vap", "ventilator pneumonia", "pneumonia", "respiratory culture",
        "sputum culture", "bal", "bronchoalveolar", "mini-bal",
        # Clinical context
        "respiratory distress", "ards", "infiltrate", "consolidation",
        "secretions", "purulent", "tracheal aspirate",
        # Management
        "wean", "weaning", "extubation", "sedation vacation",
    ],
    "ssi": [
        # Surgery terms
        "surgical site", "incision", "wound", "operative site",
        "post-op", "postoperative", "post-operative", "surgery",
        # Infection signs
        "wound infection", "surgical infection", "dehiscence",
        "erythema", "drainage", "purulent", "abscess", "cellulitis",
        "wound culture", "deep infection", "superficial infection",
        "organ space",
        # Management
        "wound care", "wound vac", "debridement", "i&d", "incision and drainage",
        "washout", "return to or", "reoperation",
    ],
}

# Always include notes of these types regardless of keywords
ALWAYS_INCLUDE_NOTE_TYPES = ["id_consult", "discharge_summary"]


class NoteRetriever:
    """Retrieves clinical notes for HAI candidate context."""

    # Note types relevant for HAI evaluation
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
        hai_type: str | HAIType | None = None,
        use_keyword_filter: bool = True,
    ) -> list[ClinicalNote]:
        """Get clinical notes relevant to an HAI candidate.

        Retrieves notes around the culture date to provide context
        for LLM classification. Optionally filters by HAI-specific keywords
        to reduce context size and improve LLM performance.

        Args:
            candidate: The HAI candidate to get notes for
            days_before: Days before culture to retrieve
            days_after: Days after culture to retrieve
            hai_type: HAI type for keyword filtering (e.g., "cdi", "clabsi").
                     If None, uses candidate.hai_type if available.
            use_keyword_filter: If True, filter notes by HAI-specific keywords.
                               Set to False to retrieve all notes.

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

            # Apply keyword filtering if enabled
            if use_keyword_filter and notes:
                # Determine HAI type
                filter_type = hai_type
                if filter_type is None and hasattr(candidate, 'hai_type'):
                    filter_type = candidate.hai_type

                if filter_type:
                    notes = self.filter_by_keywords(notes, filter_type)

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

    def filter_by_keywords(
        self,
        notes: list[ClinicalNote],
        hai_type: str | HAIType,
    ) -> list[ClinicalNote]:
        """Filter notes to those containing HAI-relevant keywords.

        This reduces the number of notes sent to the LLM, improving
        performance while maintaining classification accuracy.

        Notes of type 'id_consult' and 'discharge_summary' are always
        included regardless of keywords.

        Args:
            notes: Notes to filter
            hai_type: HAI type to filter for (e.g., "cdi", "clabsi", HAIType.CDI)

        Returns:
            Filtered list of notes
        """
        # Normalize hai_type to string
        if isinstance(hai_type, HAIType):
            type_key = hai_type.value.lower()
        else:
            type_key = str(hai_type).lower()

        keywords = HAI_KEYWORDS.get(type_key, [])
        if not keywords:
            logger.warning(f"No keywords defined for HAI type '{type_key}', returning all notes")
            return notes

        # Build regex pattern for efficient matching
        # Use word boundaries where appropriate
        pattern = re.compile(
            "|".join(re.escape(kw) for kw in keywords),
            re.IGNORECASE
        )

        filtered = []
        skipped = 0

        for note in notes:
            # Always include certain note types
            if note.note_type.lower() in ALWAYS_INCLUDE_NOTE_TYPES:
                filtered.append(note)
                continue

            # Check if note contains any keywords
            if pattern.search(note.content):
                filtered.append(note)
            else:
                skipped += 1

        logger.info(
            f"Keyword filter ({type_key}): kept {len(filtered)} notes, "
            f"skipped {skipped} non-relevant notes"
        )

        return filtered

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
