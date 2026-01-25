"""Abstract base class for HAI candidate detection."""

from abc import ABC, abstractmethod
from datetime import datetime

from ..models import HAICandidate, HAIType


class BaseCandidateDetector(ABC):
    """Abstract base class for rule-based HAI candidate detection.

    Subclasses implement the detection logic for specific HAI types
    (CLABSI, CAUTI, SSI, VAE).
    """

    @property
    @abstractmethod
    def hai_type(self) -> HAIType:
        """The type of HAI this detector identifies."""
        pass

    @abstractmethod
    def detect_candidates(
        self,
        start_date: datetime,
        end_date: datetime,
    ) -> list[HAICandidate]:
        """Detect potential HAI candidates within a date range.

        This performs rule-based screening based on NHSN criteria.
        Candidates should be created with meets_initial_criteria=True
        only if they pass all required criteria.

        Args:
            start_date: Start of date range to search
            end_date: End of date range to search

        Returns:
            List of HAI candidates identified
        """
        pass

    @abstractmethod
    def validate_candidate(self, candidate: HAICandidate) -> tuple[bool, str | None]:
        """Validate that a candidate meets all NHSN criteria.

        Args:
            candidate: The candidate to validate

        Returns:
            Tuple of (is_valid, exclusion_reason)
        """
        pass
