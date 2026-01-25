"""Base class for guideline element checkers."""

from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Add parent paths for imports
GUIDELINE_ADHERENCE_PATH = Path(__file__).parent.parent.parent
if str(GUIDELINE_ADHERENCE_PATH) not in sys.path:
    sys.path.insert(0, str(GUIDELINE_ADHERENCE_PATH))

from guideline_adherence import BundleElement, BundleElementStatus

from ..models import ElementCheckResult, ElementCheckStatus

if TYPE_CHECKING:
    from ..fhir_client import GuidelineFHIRClient

logger = logging.getLogger(__name__)


class ElementChecker(ABC):
    """Abstract base class for checking bundle elements."""

    def __init__(self, fhir_client: "GuidelineFHIRClient"):
        """Initialize with FHIR client.

        Args:
            fhir_client: Client for FHIR queries.
        """
        self.fhir_client = fhir_client

    @abstractmethod
    def check(
        self,
        element: BundleElement,
        patient_id: str,
        trigger_time: datetime,
    ) -> ElementCheckResult:
        """Check if a bundle element has been met.

        Args:
            element: The bundle element to check.
            patient_id: FHIR patient ID.
            trigger_time: When the bundle was triggered (e.g., sepsis recognition).

        Returns:
            ElementCheckResult with status and details.
        """
        pass

    def _calculate_deadline(
        self,
        trigger_time: datetime,
        window_hours: float | None,
    ) -> datetime | None:
        """Calculate the deadline for an element.

        Args:
            trigger_time: When the bundle was triggered.
            window_hours: Time window in hours.

        Returns:
            Deadline datetime or None if no window.
        """
        if window_hours is None:
            return None
        return trigger_time + timedelta(hours=window_hours)

    def _is_within_window(
        self,
        trigger_time: datetime,
        window_hours: float | None,
    ) -> bool:
        """Check if we're still within the time window.

        Args:
            trigger_time: When the bundle was triggered.
            window_hours: Time window in hours.

        Returns:
            True if still within window, False if expired.
        """
        if window_hours is None:
            return True  # No window means always applicable
        deadline = self._calculate_deadline(trigger_time, window_hours)
        return datetime.now() < deadline

    def _convert_status(self, status: BundleElementStatus) -> ElementCheckStatus:
        """Convert from BundleElementStatus to ElementCheckStatus.

        Args:
            status: The bundle element status.

        Returns:
            Corresponding ElementCheckStatus.
        """
        mapping = {
            BundleElementStatus.MET: ElementCheckStatus.MET,
            BundleElementStatus.NOT_MET: ElementCheckStatus.NOT_MET,
            BundleElementStatus.NOT_APPLICABLE: ElementCheckStatus.NOT_APPLICABLE,
            BundleElementStatus.PENDING: ElementCheckStatus.PENDING,
            BundleElementStatus.UNABLE_TO_ASSESS: ElementCheckStatus.PENDING,  # Treat as pending
        }
        return mapping.get(status, ElementCheckStatus.PENDING)

    def _create_result(
        self,
        element: BundleElement,
        status: ElementCheckStatus,
        trigger_time: datetime,
        completed_at: datetime | None = None,
        value: any = None,
        notes: str = "",
    ) -> ElementCheckResult:
        """Create an ElementCheckResult.

        Args:
            element: The bundle element.
            status: The check status.
            trigger_time: When the bundle was triggered.
            completed_at: When the element was completed (if met).
            value: The value found (e.g., lactate level).
            notes: Additional notes.

        Returns:
            ElementCheckResult instance.
        """
        return ElementCheckResult(
            element_id=element.element_id,
            element_name=element.name,
            status=status,
            time_window_hours=element.time_window_hours,
            deadline=self._calculate_deadline(trigger_time, element.time_window_hours),
            completed_at=completed_at,
            value=value,
            notes=notes,
        )
