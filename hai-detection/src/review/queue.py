"""IP review queue management."""

import logging
from datetime import datetime
from typing import Any

from ..models import (
    Review,
    ReviewQueueType,
    ReviewerDecision,
    CandidateStatus,
    NHSNEvent,
    HAIType,
)
from ..db import HAIDatabase

logger = logging.getLogger(__name__)


class ReviewQueue:
    """Manages the IP review queue for HAI candidates."""

    def __init__(self, db: HAIDatabase):
        """Initialize queue manager.

        Args:
            db: Database instance for persistence
        """
        self.db = db

    def get_pending_reviews(
        self,
        queue_type: ReviewQueueType | None = None,
    ) -> list[dict[str, Any]]:
        """Get pending reviews with candidate context.

        Args:
            queue_type: Filter by queue type. All if None.

        Returns:
            List of review dicts with candidate and classification info
        """
        return self.db.get_pending_reviews(queue_type)

    def get_queue_counts(self) -> dict[str, int]:
        """Get counts of items in each queue.

        Returns:
            Dict mapping queue type to count
        """
        all_pending = self.db.get_pending_reviews()

        counts = {
            "ip_review": 0,
            "manual_review": 0,
            "total": len(all_pending),
        }

        for review in all_pending:
            queue = review.get("queue_type", "ip_review")
            if queue in counts:
                counts[queue] += 1

        return counts

    def complete_review(
        self,
        review_id: str,
        reviewer: str,
        decision: ReviewerDecision,
        notes: str | None = None,
    ) -> bool:
        """Complete a review and update candidate status.

        Args:
            review_id: Review to complete
            reviewer: Reviewer's identifier (name or ID)
            decision: The reviewer's decision
            notes: Optional notes

        Returns:
            True if successful
        """
        try:
            # Complete the review record
            self.db.complete_review(review_id, reviewer, decision, notes)

            # Get the review to find candidate ID
            # Note: Would need to add get_review method to db.py
            # For now, handle in the route

            logger.info(
                f"Review {review_id} completed by {reviewer}: {decision.value}"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to complete review {review_id}: {e}")
            return False

    def finalize_candidate(
        self,
        candidate_id: str,
        decision: ReviewerDecision,
        reviewer: str,
    ) -> bool:
        """Finalize a candidate based on review decision.

        Args:
            candidate_id: Candidate to finalize
            decision: Review decision
            reviewer: Who made the decision

        Returns:
            True if successful
        """
        try:
            candidate = self.db.get_candidate(candidate_id)
            if not candidate:
                logger.error(f"Candidate not found: {candidate_id}")
                return False

            if decision == ReviewerDecision.CONFIRMED:
                # Mark as confirmed and create NHSN event
                self.db.update_candidate_status(candidate_id, CandidateStatus.CONFIRMED)
                self._create_nhsn_event(candidate)
                logger.info(f"Candidate {candidate_id} confirmed as HAI")

            elif decision == ReviewerDecision.REJECTED:
                self.db.update_candidate_status(candidate_id, CandidateStatus.REJECTED)
                logger.info(f"Candidate {candidate_id} rejected")

            elif decision == ReviewerDecision.NEEDS_MORE_INFO:
                # Keep in pending review status
                logger.info(f"Candidate {candidate_id} needs more information")

            return True

        except Exception as e:
            logger.error(f"Failed to finalize candidate {candidate_id}: {e}")
            return False

    def _create_nhsn_event(self, candidate) -> None:
        """Create an NHSN event for a confirmed HAI."""
        import uuid
        from datetime import date

        event = NHSNEvent(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            event_date=candidate.culture.collection_date.date(),
            hai_type=candidate.hai_type,
            # Location and pathogen codes would come from additional mapping
            location_code=None,
            pathogen_code=None,
        )

        self.db.save_event(event)
        logger.info(f"Created NHSN event {event.id} for candidate {candidate.id}")
