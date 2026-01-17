"""Base alerter interface."""

from abc import ABC, abstractmethod
from ..models import CoverageAssessment


class BaseAlerter(ABC):
    """Abstract base class for alerters."""

    @abstractmethod
    def send_alert(
        self,
        assessment: CoverageAssessment,
        alert_id: str | None = None,
    ) -> bool:
        """
        Send an alert for inadequate coverage.

        Args:
            assessment: The coverage assessment that triggered the alert
            alert_id: Optional alert ID for tracking and action buttons

        Returns:
            True if alert was sent successfully, False otherwise
        """
        pass

    @abstractmethod
    def get_alert_count(self) -> int:
        """Return the number of alerts sent."""
        pass
