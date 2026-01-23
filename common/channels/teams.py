"""Microsoft Teams webhook channel (Workflows / Power Automate version).

Send messages to Teams channels via the new Workflows webhook.
This replaces the deprecated Incoming Webhook connector.

Setup:
1. In Teams channel, click ... > Workflows
2. Search "Post to a channel when a webhook request is received"
3. Select team/channel and create
4. Copy the webhook URL
"""

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class TeamsAction:
    """Action button for Teams Adaptive Card."""
    title: str
    url: str
    style: str = "default"  # default, positive, destructive


@dataclass
class TeamsMessage:
    """Teams message content using Adaptive Card format."""
    title: str
    facts: list[tuple[str, str]] = field(default_factory=list)
    text: str | None = None
    color: str = "Attention"  # Good, Attention, Warning, Accent, Default
    alert_id: str | None = None  # For linking to dashboard
    actions: list[TeamsAction] = field(default_factory=list)


class TeamsWebhookChannel:
    """Send messages to Microsoft Teams via Workflows webhook."""

    def __init__(self, webhook_url: str):
        """
        Initialize Teams webhook channel.

        Args:
            webhook_url: The Workflows webhook URL from Teams
        """
        self.webhook_url = webhook_url

    def _build_adaptive_card(
        self,
        title: str,
        facts: list[tuple[str, str]],
        text: str | None = None,
        color: str = "Attention",
        actions: list[TeamsAction] | None = None,
    ) -> dict:
        """Build an Adaptive Card payload for Teams Workflows."""
        body = [
            {
                "type": "TextBlock",
                "text": title,
                "weight": "Bolder",
                "size": "Large",
                "color": color,
                "wrap": True,
            }
        ]

        if facts:
            body.append({
                "type": "FactSet",
                "facts": [{"title": k, "value": v} for k, v in facts],
            })

        if text:
            body.append({
                "type": "Container",
                "style": "warning" if color == "Attention" else "default",
                "items": [
                    {
                        "type": "TextBlock",
                        "text": text,
                        "wrap": True,
                    }
                ],
            })

        body.append({
            "type": "TextBlock",
            "text": f"Sent: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "size": "Small",
            "isSubtle": True,
            "wrap": True,
        })

        card = {
            "type": "AdaptiveCard",
            "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
            "version": "1.4",
            "body": body,
        }

        # Add action buttons if provided
        if actions:
            card["actions"] = [
                {
                    "type": "Action.OpenUrl",
                    "title": action.title,
                    "url": action.url,
                    "style": action.style,
                }
                for action in actions
            ]

        return card

    def _build_wrapped_payload(self, card: dict) -> dict:
        """Wrap Adaptive Card in message/attachments format for Workflows."""
        return {
            "type": "message",
            "attachments": [
                {
                    "contentType": "application/vnd.microsoft.card.adaptive",
                    "contentUrl": None,
                    "content": card,
                }
            ],
        }

    def _send_request(self, payload: dict) -> tuple[bool, int, str]:
        """Send HTTP request and return (success, status_code, response_text)."""
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                return True, response.status, response.read().decode("utf-8", errors="ignore")

        except urllib.error.HTTPError as e:
            return False, e.code, e.read().decode("utf-8", errors="ignore")[:200]
        except urllib.error.URLError as e:
            return False, 0, str(e.reason)
        except Exception as e:
            return False, 0, str(e)

    def send(self, message: TeamsMessage) -> bool:
        """
        Send a message to Teams.

        Args:
            message: The message to send

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.webhook_url:
            print("  Teams: No webhook URL configured")
            return False

        card = self._build_adaptive_card(
            title=message.title,
            facts=message.facts,
            text=message.text,
            color=message.color,
            actions=message.actions if message.actions else None,
        )

        # Try wrapped format first (works with most Workflows setups)
        payload = self._build_wrapped_payload(card)
        success, status, response_text = self._send_request(payload)

        if success and status in (200, 202):
            print("  Teams message sent")
            return True

        # Try unwrapped Adaptive Card format as fallback
        print(f"  Teams: Wrapped format failed ({status}), trying direct card...")
        success, status, response_text = self._send_request(card)

        if success and status in (200, 202):
            print("  Teams message sent (direct card)")
            return True

        print(f"  Teams failed: {status} - {response_text}")
        return False

    def send_simple(
        self,
        title: str,
        text: str,
        color: str = "Attention",
    ) -> bool:
        """
        Send a simple message to Teams.

        Args:
            title: Message title
            text: Message body
            color: Card color (Good, Attention, Warning, Accent, Default)

        Returns:
            True if sent successfully, False otherwise
        """
        return self.send(TeamsMessage(
            title=title,
            text=text,
            color=color,
        ))

    def send_card(
        self,
        title: str,
        facts: list[tuple[str, str]],
        text: str | None = None,
        color: str = "Attention",
        theme_color: str | None = None,  # Ignored, kept for backwards compatibility
    ) -> bool:
        """
        Send a card with key-value facts to Teams.

        Args:
            title: Card title
            facts: List of (name, value) tuples
            text: Optional additional text
            color: Card color (Good, Attention, Warning, Accent, Default)
            theme_color: Deprecated, ignored (was for old MessageCard format)

        Returns:
            True if sent successfully, False otherwise
        """
        return self.send(TeamsMessage(
            title=title,
            facts=facts,
            text=text,
            color=color,
        ))

    def is_configured(self) -> bool:
        """Check if channel is configured."""
        return bool(self.webhook_url)

    def send_status_update(
        self,
        alert_id: str,
        status: str,
        title: str,
        updated_by: str = "Dashboard User",
        resolution_reason: str | None = None,
        details_url: str | None = None,
    ) -> bool:
        """
        Send a status update card for an alert (thread-reply style).

        This sends a follow-up message to notify the channel that an alert
        has been acknowledged or resolved.

        Args:
            alert_id: The alert ID being updated
            status: New status (acknowledged, resolved, snoozed)
            title: Brief description of the alert (for reference)
            updated_by: Who performed the action
            resolution_reason: Optional reason (for resolved alerts)
            details_url: Optional URL to view full details

        Returns:
            True if sent successfully, False otherwise
        """
        if not self.webhook_url:
            return False

        # Determine color and icon based on status
        status_config = {
            "acknowledged": ("Accent", "Acknowledged"),
            "resolved": ("Good", "Resolved"),
            "snoozed": ("Warning", "Snoozed"),
        }
        color, status_display = status_config.get(status.lower(), ("Default", status.title()))

        facts = [
            ("Alert", title[:50] + "..." if len(title) > 50 else title),
            ("Status", status_display),
            ("By", updated_by),
        ]

        if resolution_reason:
            # Format the reason nicely
            reason_display = resolution_reason.replace("_", " ").title()
            facts.append(("Reason", reason_display))

        actions = []
        if details_url:
            actions.append(TeamsAction(
                title="View Details",
                url=details_url,
                style="default",
            ))

        return self.send(TeamsMessage(
            title=f"Alert {status_display}",
            facts=facts,
            color=color,
            alert_id=alert_id,
            actions=actions,
        ))


def test_webhook(webhook_url: str) -> bool:
    """
    Send a test message to verify webhook configuration.

    Usage:
        python -c "from common.channels.teams import test_webhook; test_webhook('YOUR_URL')"
    """
    channel = TeamsWebhookChannel(webhook_url)

    print("Sending test to Workflows webhook...")

    success = channel.send(TeamsMessage(
        title="✅ ASP Alerts - Test Message",
        facts=[
            ("Status", "Webhook configured correctly"),
            ("Time", datetime.now().strftime('%Y-%m-%d %H:%M:%S')),
        ],
        text="If you see this in Teams, your webhook is working!",
        color="Good",
    ))

    if success:
        print("✅ SUCCESS! Check your Teams channel for the test message.")
    else:
        print("❌ FAILED - see error above")

    return success


def build_teams_actions(
    alert_id: str,
    base_url: str,
    api_key: str | None = None,
    include_resolve_options: bool = False,
) -> list[TeamsAction]:
    """Build standard action buttons for an alert.

    Args:
        alert_id: The alert ID for URL construction
        base_url: Dashboard base URL (e.g., http://localhost:5000)
        api_key: Optional API key for authentication
        include_resolve_options: If True, adds quick-resolve buttons

    Returns:
        List of TeamsAction buttons for alert management
    """
    # Build query string for API key if provided
    key_param = f"?key={api_key}" if api_key else ""
    key_suffix = f"&key={api_key}" if api_key else ""

    actions = [
        TeamsAction(
            title="Acknowledge",
            url=f"{base_url}/api/ack/{alert_id}{key_param}",
            style="positive",
        ),
        TeamsAction(
            title="Snooze 4h",
            url=f"{base_url}/api/snooze/{alert_id}?hours=4{key_suffix}",
            style="default",
        ),
        TeamsAction(
            title="View / Resolve",
            url=f"{base_url}/asp-alerts/alerts/{alert_id}",
            style="default",
        ),
    ]

    if include_resolve_options:
        # Add quick-resolve buttons for common resolutions
        # Note: Teams Adaptive Cards support up to 6 actions
        actions.extend([
            TeamsAction(
                title="Approved",
                url=f"{base_url}/api/resolve/{alert_id}?reason=approved{key_suffix}",
                style="positive",
            ),
            TeamsAction(
                title="Discussed",
                url=f"{base_url}/api/resolve/{alert_id}?reason=discussed_with_team{key_suffix}",
                style="default",
            ),
        ])

    return actions


def build_resolve_actions(
    alert_id: str,
    base_url: str,
    api_key: str | None = None,
) -> list[TeamsAction]:
    """Build resolution-specific action buttons.

    Args:
        alert_id: The alert ID for URL construction
        base_url: Dashboard base URL (e.g., http://localhost:5000)
        api_key: Optional API key for authentication

    Returns:
        List of TeamsAction buttons for common resolution reasons
    """
    key_suffix = f"&key={api_key}" if api_key else ""

    return [
        TeamsAction(
            title="Approved",
            url=f"{base_url}/api/resolve/{alert_id}?reason=approved{key_suffix}",
            style="positive",
        ),
        TeamsAction(
            title="Messaged Team",
            url=f"{base_url}/api/resolve/{alert_id}?reason=messaged_team{key_suffix}",
            style="default",
        ),
        TeamsAction(
            title="Discussed",
            url=f"{base_url}/api/resolve/{alert_id}?reason=discussed_with_team{key_suffix}",
            style="default",
        ),
        TeamsAction(
            title="Suggested Alt",
            url=f"{base_url}/api/resolve/{alert_id}?reason=suggested_alternative{key_suffix}",
            style="default",
        ),
        TeamsAction(
            title="View Details",
            url=f"{base_url}/asp-alerts/alerts/{alert_id}",
            style="default",
        ),
    ]
