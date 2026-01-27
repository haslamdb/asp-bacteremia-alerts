"""
Epic Secure Chat integration for surgical prophylaxis alerts.

Uses SMART Backend Services authentication and FHIR Communication
resources to send secure messages to providers via Epic InBasket.
"""

import base64
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Any
from urllib.parse import urljoin

try:
    import jwt
    HAS_JWT = True
except ImportError:
    HAS_JWT = False

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

logger = logging.getLogger(__name__)


# Epic deep link templates
EPIC_DEEP_LINKS = {
    "order_prophylaxis": (
        "epic://Hyperspace/Content/OrderEntry?"
        "orderSetId={order_set_id}&patientId={patient_id}"
    ),
    "view_patient": (
        "epic://Hyperspace/Content/PatientSummary?"
        "patientId={patient_id}"
    ),
    "view_mar": (
        "epic://Hyperspace/Content/MAR?"
        "patientId={patient_id}"
    ),
    "order_entry": (
        "epic://Hyperspace/Content/OrderEntry?"
        "patientId={patient_id}"
    ),
}

# Default prophylaxis order set IDs (institution-specific)
DEFAULT_ORDER_SET_IDS = {
    "surgical_prophylaxis": "12345",  # Replace with actual order set ID
    "cefazolin_prophylaxis": "12346",
    "vancomycin_prophylaxis": "12347",
}


@dataclass
class EpicChatConfig:
    """Configuration for Epic Secure Chat."""

    enabled: bool = False
    client_id: str = ""
    private_key_path: str = ""
    fhir_base_url: str = ""
    token_endpoint: str = ""
    audience: str = ""  # Usually same as token endpoint

    # Optional overrides
    prophylaxis_order_set_id: str = ""
    sender_practitioner_id: str = ""  # System sender ID

    @classmethod
    def from_env(cls) -> "EpicChatConfig":
        """Create config from environment variables."""
        return cls(
            enabled=os.getenv("EPIC_CHAT_ENABLED", "").lower() == "true",
            client_id=os.getenv("EPIC_CHAT_CLIENT_ID", ""),
            private_key_path=os.getenv("EPIC_CHAT_PRIVATE_KEY_PATH", ""),
            fhir_base_url=os.getenv("EPIC_FHIR_BASE_URL", ""),
            token_endpoint=os.getenv("EPIC_TOKEN_ENDPOINT", ""),
            audience=os.getenv("EPIC_TOKEN_AUDIENCE", ""),
            prophylaxis_order_set_id=os.getenv("EPIC_PROPHYLAXIS_ORDER_SET_ID", ""),
            sender_practitioner_id=os.getenv("EPIC_SENDER_PRACTITIONER_ID", ""),
        )


@dataclass
class ChatMessage:
    """Represents a message to send via Epic Secure Chat."""

    recipient_provider_id: str
    recipient_name: Optional[str] = None
    subject: str = ""
    message_body: str = ""
    patient_id: Optional[str] = None
    patient_mrn: Optional[str] = None
    action_links: list[tuple[str, str]] = None  # List of (label, url) tuples

    def __post_init__(self):
        if self.action_links is None:
            self.action_links = []


class EpicSecureChat:
    """
    Epic Secure Chat client using SMART Backend Services.

    Authenticates using JWT bearer tokens and sends messages
    via FHIR Communication resources.
    """

    def __init__(self, config: Optional[EpicChatConfig] = None):
        self.config = config or EpicChatConfig.from_env()
        self._access_token: Optional[str] = None
        self._token_expiry: Optional[datetime] = None
        self._private_key: Optional[str] = None

        if not HAS_JWT:
            logger.warning("PyJWT not installed, Epic Chat authentication disabled")
        if not HAS_REQUESTS:
            logger.warning("requests not installed, Epic Chat disabled")

    @property
    def is_configured(self) -> bool:
        """Check if Epic Chat is properly configured."""
        return (
            self.config.enabled
            and bool(self.config.client_id)
            and bool(self.config.private_key_path)
            and bool(self.config.fhir_base_url)
            and HAS_JWT
            and HAS_REQUESTS
        )

    async def authenticate(self) -> bool:
        """
        Authenticate using SMART Backend Services.

        Uses JWT bearer token flow:
        1. Create signed JWT assertion
        2. Exchange for access token

        Returns:
            True if authentication successful
        """
        if not self.is_configured:
            logger.warning("Epic Chat not configured")
            return False

        # Check if we have a valid token
        if self._access_token and self._token_expiry:
            if datetime.now() < self._token_expiry - timedelta(minutes=5):
                return True

        try:
            # Load private key if not loaded
            if not self._private_key:
                self._private_key = self._load_private_key()

            # Create JWT assertion
            assertion = self._create_jwt_assertion()

            # Exchange for access token
            token_response = self._request_access_token(assertion)

            if token_response:
                self._access_token = token_response.get("access_token")
                expires_in = token_response.get("expires_in", 3600)
                self._token_expiry = datetime.now() + timedelta(seconds=expires_in)
                logger.info("Epic Chat authentication successful")
                return True

            return False

        except Exception as e:
            logger.error(f"Epic Chat authentication failed: {e}")
            return False

    def _load_private_key(self) -> str:
        """Load private key from file."""
        key_path = Path(self.config.private_key_path)
        if not key_path.exists():
            raise FileNotFoundError(f"Private key not found: {key_path}")

        return key_path.read_text()

    def _create_jwt_assertion(self) -> str:
        """Create a signed JWT assertion for authentication."""
        now = int(time.time())

        payload = {
            "iss": self.config.client_id,
            "sub": self.config.client_id,
            "aud": self.config.audience or self.config.token_endpoint,
            "jti": f"{now}-{id(self)}",  # Unique token ID
            "exp": now + 300,  # 5 minute expiry
            "iat": now,
        }

        return jwt.encode(
            payload,
            self._private_key,
            algorithm="RS384",
            headers={"alg": "RS384", "typ": "JWT"},
        )

    def _request_access_token(self, assertion: str) -> Optional[dict]:
        """Exchange JWT assertion for access token."""
        data = {
            "grant_type": "client_credentials",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
            "scope": "system/Communication.write system/Practitioner.read",
        }

        response = requests.post(
            self.config.token_endpoint,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )

        if response.status_code == 200:
            return response.json()
        else:
            logger.error(
                f"Token request failed: {response.status_code} - {response.text}"
            )
            return None

    async def send_message(
        self,
        message: ChatMessage,
    ) -> Optional[str]:
        """
        Send a message via Epic Secure Chat.

        Args:
            message: The message to send

        Returns:
            FHIR Communication ID if successful, None otherwise
        """
        if not await self.authenticate():
            logger.error("Cannot send message - authentication failed")
            return None

        try:
            # Build FHIR Communication resource
            communication = self._build_communication_resource(message)

            # Post to FHIR server
            response = requests.post(
                urljoin(self.config.fhir_base_url, "Communication"),
                json=communication,
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Content-Type": "application/fhir+json",
                },
                timeout=30,
            )

            if response.status_code in (200, 201):
                result = response.json()
                comm_id = result.get("id")
                logger.info(f"Message sent via Epic Chat: {comm_id}")
                return comm_id
            else:
                logger.error(
                    f"Failed to send message: {response.status_code} - {response.text}"
                )
                return None

        except Exception as e:
            logger.error(f"Error sending Epic Chat message: {e}")
            return None

    def _build_communication_resource(self, message: ChatMessage) -> dict:
        """Build a FHIR Communication resource for the message."""
        communication = {
            "resourceType": "Communication",
            "status": "completed",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/communication-category",
                            "code": "alert",
                            "display": "Alert",
                        }
                    ],
                    "text": "Surgical Prophylaxis Alert",
                }
            ],
            "priority": "urgent",
            "subject": None,
            "recipient": [
                {
                    "reference": f"Practitioner/{message.recipient_provider_id}",
                    "display": message.recipient_name or "Provider",
                }
            ],
            "sender": {
                "reference": f"Practitioner/{self.config.sender_practitioner_id}",
                "display": "AEGIS Surgical Prophylaxis Monitor",
            },
            "payload": [],
            "sent": datetime.now().isoformat(),
        }

        # Add patient reference if available
        if message.patient_id:
            communication["subject"] = {
                "reference": f"Patient/{message.patient_id}",
            }
            if message.patient_mrn:
                communication["subject"]["display"] = f"MRN: {message.patient_mrn}"

        # Build message content
        content_parts = []

        # Subject line
        if message.subject:
            content_parts.append(f"**{message.subject}**")
            content_parts.append("")

        # Message body
        if message.message_body:
            content_parts.append(message.message_body)
            content_parts.append("")

        # Action links
        if message.action_links:
            content_parts.append("**Quick Actions:**")
            for label, url in message.action_links:
                content_parts.append(f"- [{label}]({url})")

        # Add payload
        communication["payload"].append({
            "contentString": "\n".join(content_parts),
        })

        return communication

    async def lookup_provider(
        self,
        provider_id: str,
    ) -> Optional[dict]:
        """
        Look up provider information from Epic.

        Args:
            provider_id: The Epic Practitioner ID

        Returns:
            Provider info dict or None
        """
        if not await self.authenticate():
            return None

        try:
            response = requests.get(
                urljoin(self.config.fhir_base_url, f"Practitioner/{provider_id}"),
                headers={
                    "Authorization": f"Bearer {self._access_token}",
                    "Accept": "application/fhir+json",
                },
                timeout=30,
            )

            if response.status_code == 200:
                practitioner = response.json()
                name_parts = practitioner.get("name", [{}])[0]
                return {
                    "id": provider_id,
                    "name": self._format_name(name_parts),
                    "specialty": self._extract_specialty(practitioner),
                }

            return None

        except Exception as e:
            logger.error(f"Error looking up provider: {e}")
            return None

    def _format_name(self, name_parts: dict) -> str:
        """Format a FHIR name into display string."""
        given = " ".join(name_parts.get("given", []))
        family = name_parts.get("family", "")
        return f"{given} {family}".strip()

    def _extract_specialty(self, practitioner: dict) -> Optional[str]:
        """Extract specialty from practitioner resource."""
        qualifications = practitioner.get("qualification", [])
        for qual in qualifications:
            code = qual.get("code", {})
            if code.get("text"):
                return code["text"]
        return None

    def build_action_links(
        self,
        patient_id: str,
        order_set_id: Optional[str] = None,
    ) -> list[tuple[str, str]]:
        """
        Build action links for a message.

        Args:
            patient_id: The Epic patient ID
            order_set_id: Optional order set ID to use

        Returns:
            List of (label, url) tuples
        """
        links = []

        # Order prophylaxis link
        order_set = order_set_id or self.config.prophylaxis_order_set_id or DEFAULT_ORDER_SET_IDS.get("surgical_prophylaxis", "")
        if order_set:
            links.append((
                "Order Prophylaxis",
                EPIC_DEEP_LINKS["order_prophylaxis"].format(
                    order_set_id=order_set,
                    patient_id=patient_id,
                ),
            ))

        # View patient
        links.append((
            "View Patient",
            EPIC_DEEP_LINKS["view_patient"].format(patient_id=patient_id),
        ))

        # View MAR
        links.append((
            "View MAR",
            EPIC_DEEP_LINKS["view_mar"].format(patient_id=patient_id),
        ))

        return links


def create_epic_chat() -> EpicSecureChat:
    """Factory function to create EpicSecureChat from environment."""
    return EpicSecureChat(EpicChatConfig.from_env())


async def send_prophylaxis_alert(
    chat: EpicSecureChat,
    provider_id: str,
    provider_name: str,
    patient_id: str,
    patient_mrn: str,
    subject: str,
    message_body: str,
) -> Optional[str]:
    """
    Convenience function to send a prophylaxis alert.

    Args:
        chat: EpicSecureChat instance
        provider_id: Recipient provider ID
        provider_name: Recipient provider name
        patient_id: Patient FHIR ID
        patient_mrn: Patient MRN
        subject: Message subject
        message_body: Message body

    Returns:
        Communication ID if successful
    """
    if not chat.is_configured:
        logger.warning("Epic Chat not configured, skipping send")
        return None

    action_links = chat.build_action_links(patient_id)

    message = ChatMessage(
        recipient_provider_id=provider_id,
        recipient_name=provider_name,
        subject=subject,
        message_body=message_body,
        patient_id=patient_id,
        patient_mrn=patient_mrn,
        action_links=action_links,
    )

    return await chat.send_message(message)
