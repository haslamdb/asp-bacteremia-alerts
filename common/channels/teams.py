"""Microsoft Teams webhook channel.

Send messages to Teams channels via incoming webhooks.

To set up a webhook in Teams:
1. Go to the channel where you want to receive alerts
2. Click the ... menu > Connectors (or "Workflows" in new Teams)
3. Add "Incoming Webhook" and configure it
4. Copy the webhook URL
"""

import json
import urllib.request
import urllib.error
from dataclasses import dataclass, field


@dataclass
class TeamsMessage:
    """Teams message content using Adaptive Card format."""
    title: str
    text: str
    theme_color: str = "d63333"  # Red by default for alerts
    sections: list[dict] = field(default_factory=list)


class TeamsWebhookChannel:
    """Send messages to Microsoft Teams via webhook."""

    def __init__(self, webhook_url: str):
        """
        Initialize Teams webhook channel.

        Args:
            webhook_url: The incoming webhook URL from Teams
        """
        self.webhook_url = webhook_url

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

        # Build MessageCard payload (legacy format, widely supported)
        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": message.theme_color,
            "summary": message.title,
            "sections": [
                {
                    "activityTitle": message.title,
                    "text": message.text,
                    "markdown": True,
                }
            ] + message.sections,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    print("  Teams message sent")
                    return True
                else:
                    print(f"  Teams: Unexpected status {response.status}")
                    return False

        except urllib.error.HTTPError as e:
            print(f"  Teams failed: HTTP {e.code} - {e.reason}")
            return False
        except urllib.error.URLError as e:
            print(f"  Teams failed: {e.reason}")
            return False
        except Exception as e:
            print(f"  Teams failed: {e}")
            return False

    def send_simple(
        self,
        title: str,
        text: str,
        theme_color: str = "d63333",
    ) -> bool:
        """
        Send a simple message to Teams.

        Args:
            title: Message title
            text: Message body (supports markdown)
            theme_color: Hex color for the message accent

        Returns:
            True if sent successfully, False otherwise
        """
        return self.send(TeamsMessage(
            title=title,
            text=text,
            theme_color=theme_color,
        ))

    def send_card(
        self,
        title: str,
        facts: list[tuple[str, str]],
        text: str | None = None,
        theme_color: str = "d63333",
    ) -> bool:
        """
        Send a card with key-value facts to Teams.

        Args:
            title: Card title
            facts: List of (name, value) tuples
            text: Optional additional text
            theme_color: Hex color for the card accent

        Returns:
            True if sent successfully, False otherwise
        """
        sections = [
            {
                "activityTitle": title,
                "facts": [{"name": k, "value": v} for k, v in facts],
                "markdown": True,
            }
        ]

        if text:
            sections.append({"text": text, "markdown": True})

        payload = {
            "@type": "MessageCard",
            "@context": "http://schema.org/extensions",
            "themeColor": theme_color,
            "summary": title,
            "sections": sections,
        }

        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                self.webhook_url,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    print("  Teams card sent")
                    return True
                else:
                    print(f"  Teams: Unexpected status {response.status}")
                    return False

        except urllib.error.HTTPError as e:
            print(f"  Teams failed: HTTP {e.code} - {e.reason}")
            return False
        except urllib.error.URLError as e:
            print(f"  Teams failed: {e.reason}")
            return False
        except Exception as e:
            print(f"  Teams failed: {e}")
            return False

    def is_configured(self) -> bool:
        """Check if channel is configured."""
        return bool(self.webhook_url)
