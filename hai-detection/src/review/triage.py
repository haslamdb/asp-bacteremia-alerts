"""Confidence-based triage logic for routing candidates to review."""

import logging
import uuid
from datetime import datetime

from ..config import Config
from ..models import (
    HAICandidate,
    Classification,
    ClassificationDecision,
    Review,
    ReviewQueueType,
    CandidateStatus,
)
from ..db import HAIDatabase

logger = logging.getLogger(__name__)


class Triage:
    """Routes HAI candidates based on classification confidence.

    Routing logic:
    - confidence >= auto_threshold: Auto-confirm/reject
    - confidence >= ip_threshold: Route to IP review
    - confidence < ip_threshold: Route to manual review (complex cases)
    """

    def __init__(
        self,
        db: HAIDatabase | None = None,
        auto_threshold: float | None = None,
        ip_threshold: float | None = None,
    ):
        """Initialize triage.

        Args:
            db: Database instance for persisting reviews
            auto_threshold: Confidence for auto-classification. Uses config if None.
            ip_threshold: Confidence for IP review routing. Uses config if None.
        """
        self.db = db
        self.auto_threshold = auto_threshold or Config.AUTO_CLASSIFY_THRESHOLD
        self.ip_threshold = ip_threshold or Config.IP_REVIEW_THRESHOLD

    def triage_classification(
        self,
        candidate: HAICandidate,
        classification: Classification,
    ) -> tuple[CandidateStatus, Review | None]:
        """Determine routing based on classification confidence.

        Args:
            candidate: The HAI candidate
            classification: The LLM classification result

        Returns:
            Tuple of (new_status, review) where review is None for auto-processed
        """
        confidence = classification.confidence
        decision = classification.decision

        # High confidence: auto-process
        if confidence >= self.auto_threshold:
            logger.info(
                f"Candidate {candidate.id}: Auto-processing "
                f"(confidence={confidence:.2f}, threshold={self.auto_threshold})"
            )

            if decision == ClassificationDecision.HAI_CONFIRMED:
                return CandidateStatus.CONFIRMED, None
            elif decision == ClassificationDecision.NOT_HAI:
                return CandidateStatus.REJECTED, None
            else:
                # Even at high confidence, PENDING_REVIEW needs human review
                return self._create_review(
                    candidate, classification, ReviewQueueType.IP_REVIEW
                )

        # Medium confidence: IP review
        if confidence >= self.ip_threshold:
            logger.info(
                f"Candidate {candidate.id}: Routing to IP review "
                f"(confidence={confidence:.2f})"
            )
            return self._create_review(
                candidate, classification, ReviewQueueType.IP_REVIEW
            )

        # Low confidence: manual review
        logger.info(
            f"Candidate {candidate.id}: Routing to manual review "
            f"(confidence={confidence:.2f})"
        )
        return self._create_review(
            candidate, classification, ReviewQueueType.MANUAL_REVIEW
        )

    def _create_review(
        self,
        candidate: HAICandidate,
        classification: Classification,
        queue_type: ReviewQueueType,
    ) -> tuple[CandidateStatus, Review]:
        """Create a review queue entry."""
        review = Review(
            id=str(uuid.uuid4()),
            candidate_id=candidate.id,
            classification_id=classification.id,
            queue_type=queue_type,
            created_at=datetime.now(),
        )

        if self.db:
            self.db.save_review(review)
            self.db.update_candidate_status(candidate.id, CandidateStatus.PENDING_REVIEW)

        return CandidateStatus.PENDING_REVIEW, review

    def get_routing_explanation(
        self,
        confidence: float,
        decision: ClassificationDecision,
    ) -> str:
        """Get human-readable explanation of routing decision."""
        if confidence >= self.auto_threshold:
            if decision == ClassificationDecision.HAI_CONFIRMED:
                return f"High confidence ({confidence:.1%}): Auto-confirmed as HAI"
            elif decision == ClassificationDecision.NOT_HAI:
                return f"High confidence ({confidence:.1%}): Auto-rejected as not HAI"
            else:
                return f"High confidence ({confidence:.1%}) but uncertain: IP review required"
        elif confidence >= self.ip_threshold:
            return (
                f"Moderate confidence ({confidence:.1%}): "
                f"Requires IP review for {decision.value.replace('_', ' ')}"
            )
        else:
            return (
                f"Low confidence ({confidence:.1%}): "
                f"Requires manual review - complex case"
            )
