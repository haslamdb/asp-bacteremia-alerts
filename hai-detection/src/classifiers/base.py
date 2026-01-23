"""Abstract base class for HAI classifiers."""

from abc import ABC, abstractmethod

from ..models import HAICandidate, Classification, ClinicalNote


class BaseHAIClassifier(ABC):
    """Abstract base class for LLM-based HAI classification."""

    @property
    @abstractmethod
    def hai_type(self) -> str:
        """The HAI type this classifier handles."""
        pass

    @property
    @abstractmethod
    def prompt_version(self) -> str:
        """Version of the prompt template being used."""
        pass

    @abstractmethod
    def classify(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> Classification:
        """Classify an HAI candidate.

        Args:
            candidate: The HAI candidate to classify
            notes: Clinical notes for context

        Returns:
            Classification result with decision and confidence
        """
        pass

    @abstractmethod
    def build_prompt(
        self,
        candidate: HAICandidate,
        notes: list[ClinicalNote],
    ) -> str:
        """Build the classification prompt.

        Args:
            candidate: The HAI candidate
            notes: Clinical notes for context

        Returns:
            Formatted prompt string
        """
        pass
