"""Microsoft Teams alerter for NHSN notifications."""

import json
import logging

import requests

from ..config import Config
from ..models import HAICandidate, Review

logger = logging.getLogger(__name__)


class TeamsAlerter:
    """Sends NHSN notifications to Microsoft Teams."""

    def __init__(self, webhook_url: str | None = None):
        """Initialize Teams alerter.

        Args:
            webhook_url: Teams webhook URL. Uses config if None.
        """
        self.webhook_url = webhook_url or Config.TEAMS_WEBHOOK_URL
        self.dashboard_url = Config.DASHBOARD_BASE_URL

    def is_configured(self) -> bool:
        """Check if Teams webhook is configured."""
        return bool(self.webhook_url)

    def send_new_candidate_alert(self, candidate: HAICandidate) -> bool:
        """Send alert for a new HAI candidate.

        Args:
            candidate: The new candidate

        Returns:
            True if sent successfully
        """
        if not self.is_configured():
            logger.warning("Teams webhook not configured")
            return False

        card = self._build_candidate_card(candidate)
        return self._send_card(card)

    def send_review_needed_alert(self, review: Review, candidate: HAICandidate) -> bool:
        """Send alert that a candidate needs IP review.

        Args:
            review: The review queue entry
            candidate: The candidate needing review

        Returns:
            True if sent successfully
        """
        if not self.is_configured():
            logger.warning("Teams webhook not configured")
            return False

        card = self._build_review_card(review, candidate)
        return self._send_card(card)

    def _build_candidate_card(self, candidate: HAICandidate) -> dict:
        """Build adaptive card for new candidate."""
        facts = [
            {"title": "Patient MRN", "value": candidate.patient.mrn},
            {"title": "HAI Type", "value": candidate.hai_type.value.upper()},
            {
                "title": "Organism",
                "value": candidate.culture.organism or "Pending",
            },
            {
                "title": "Culture Date",
                "value": candidate.culture.collection_date.strftime("%Y-%m-%d %H:%M"),
            },
            {
                "title": "Device Days",
                "value": str(candidate.device_days_at_culture or "Unknown"),
            },
        ]

        if candidate.patient.name:
            facts.insert(1, {"title": "Patient Name", "value": candidate.patient.name})

        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.2",
                        "body": [
                            {
                                "type": "TextBlock",
                                "size": "Medium",
                                "weight": "Bolder",
                                "text": f"New {candidate.hai_type.value.upper()} Candidate",
                                "color": "Warning",
                            },
                            {
                                "type": "FactSet",
                                "facts": facts,
                            },
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "View in Dashboard",
                                "url": f"{self.dashboard_url}/nhsn/candidates/{candidate.id}",
                            }
                        ],
                    },
                }
            ],
        }

    def _build_review_card(self, review: Review, candidate: HAICandidate) -> dict:
        """Build adaptive card for review needed."""
        queue_display = review.queue_type.value.replace("_", " ").title()

        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "content": {
                        "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                        "type": "AdaptiveCard",
                        "version": "1.2",
                        "body": [
                            {
                                "type": "TextBlock",
                                "size": "Medium",
                                "weight": "Bolder",
                                "text": f"{candidate.hai_type.value.upper()} Needs {queue_display}",
                                "color": "Attention",
                            },
                            {
                                "type": "FactSet",
                                "facts": [
                                    {"title": "Patient MRN", "value": candidate.patient.mrn},
                                    {
                                        "title": "Organism",
                                        "value": candidate.culture.organism or "Pending",
                                    },
                                    {"title": "Queue", "value": queue_display},
                                ],
                            },
                            {
                                "type": "TextBlock",
                                "text": "Please review this candidate in the dashboard.",
                                "wrap": True,
                            },
                        ],
                        "actions": [
                            {
                                "type": "Action.OpenUrl",
                                "title": "Review Now",
                                "url": f"{self.dashboard_url}/nhsn/candidates/{candidate.id}",
                            }
                        ],
                    },
                }
            ],
        }

    def _send_card(self, card: dict) -> bool:
        """Send an adaptive card to Teams."""
        try:
            response = requests.post(
                self.webhook_url,
                json=card,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            response.raise_for_status()
            logger.info("Teams notification sent successfully")
            return True

        except requests.RequestException as e:
            logger.error(f"Failed to send Teams notification: {e}")
            return False
