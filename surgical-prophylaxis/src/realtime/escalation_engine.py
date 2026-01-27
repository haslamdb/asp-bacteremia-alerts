"""
Escalation engine for surgical prophylaxis alerts.

Routes alerts to appropriate recipients based on trigger type,
handles automatic escalation after timeout, and tracks responses.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Optional, Awaitable

from .preop_checker import PreOpCheckResult, AlertSeverity, AlertTrigger

logger = logging.getLogger(__name__)


class RecipientRole(Enum):
    """Roles that can receive prophylaxis alerts."""

    PREOP_RN = "preop_rn"
    PREOP_PHARMACY = "preop_pharmacy"
    ANESTHESIA = "anesthesia"
    SURGEON = "surgeon"
    ASP = "asp"  # Antimicrobial Stewardship Program


class DeliveryChannel(Enum):
    """Channels for delivering alerts."""

    EPIC_CHAT = "epic_chat"
    TEAMS = "teams"
    PAGE = "page"
    DASHBOARD = "dashboard"
    EMAIL = "email"


@dataclass
class EscalationRule:
    """Defines escalation behavior for an alert type."""

    trigger: AlertTrigger
    primary_role: RecipientRole
    escalation_delay_minutes: int = 30
    escalation_role: Optional[RecipientRole] = None
    secondary_escalation_delay_minutes: int = 15
    secondary_escalation_role: Optional[RecipientRole] = None
    channels: list[DeliveryChannel] = field(default_factory=list)
    requires_acknowledgment: bool = True

    def __post_init__(self):
        if not self.channels:
            self.channels = [DeliveryChannel.DASHBOARD]


@dataclass
class EscalationRecord:
    """Tracks an active escalation."""

    escalation_id: str
    alert_id: str
    journey_id: Optional[str]
    trigger: AlertTrigger
    current_level: int = 1
    current_role: RecipientRole = RecipientRole.PREOP_RN
    current_recipient_id: Optional[str] = None
    current_recipient_name: Optional[str] = None

    # Timing
    created_at: datetime = field(default_factory=datetime.now)
    sent_at: Optional[datetime] = None
    next_escalation_at: Optional[datetime] = None

    # Delivery
    channels_sent: list[DeliveryChannel] = field(default_factory=list)
    delivery_status: str = "pending"  # pending, sent, delivered, failed

    # Response
    response_at: Optional[datetime] = None
    response_action: Optional[str] = None
    response_by: Optional[str] = None
    acknowledged: bool = False
    escalated: bool = False


# Default escalation rules per trigger type
DEFAULT_ESCALATION_RULES: dict[AlertTrigger, EscalationRule] = {
    AlertTrigger.T24: EscalationRule(
        trigger=AlertTrigger.T24,
        primary_role=RecipientRole.PREOP_PHARMACY,
        escalation_delay_minutes=0,  # No escalation for T-24h
        escalation_role=None,
        channels=[DeliveryChannel.DASHBOARD],
        requires_acknowledgment=False,
    ),
    AlertTrigger.T2: EscalationRule(
        trigger=AlertTrigger.T2,
        primary_role=RecipientRole.PREOP_RN,
        escalation_delay_minutes=30,
        escalation_role=RecipientRole.ANESTHESIA,
        channels=[DeliveryChannel.EPIC_CHAT, DeliveryChannel.TEAMS, DeliveryChannel.DASHBOARD],
        requires_acknowledgment=True,
    ),
    AlertTrigger.PREOP_ARRIVAL: EscalationRule(
        trigger=AlertTrigger.PREOP_ARRIVAL,
        primary_role=RecipientRole.PREOP_RN,
        escalation_delay_minutes=30,
        escalation_role=RecipientRole.ANESTHESIA,
        channels=[DeliveryChannel.EPIC_CHAT, DeliveryChannel.TEAMS, DeliveryChannel.DASHBOARD],
        requires_acknowledgment=True,
    ),
    AlertTrigger.T60: EscalationRule(
        trigger=AlertTrigger.T60,
        primary_role=RecipientRole.ANESTHESIA,
        escalation_delay_minutes=15,
        escalation_role=RecipientRole.SURGEON,
        secondary_escalation_delay_minutes=10,
        secondary_escalation_role=RecipientRole.ASP,
        channels=[DeliveryChannel.EPIC_CHAT, DeliveryChannel.TEAMS, DeliveryChannel.DASHBOARD],
        requires_acknowledgment=True,
    ),
    AlertTrigger.T0: EscalationRule(
        trigger=AlertTrigger.T0,
        primary_role=RecipientRole.ANESTHESIA,
        escalation_delay_minutes=5,
        escalation_role=RecipientRole.ASP,
        channels=[
            DeliveryChannel.EPIC_CHAT,
            DeliveryChannel.TEAMS,
            DeliveryChannel.PAGE,
            DeliveryChannel.DASHBOARD,
        ],
        requires_acknowledgment=True,
    ),
    AlertTrigger.OR_ENTRY: EscalationRule(
        trigger=AlertTrigger.OR_ENTRY,
        primary_role=RecipientRole.ANESTHESIA,
        escalation_delay_minutes=5,
        escalation_role=RecipientRole.ASP,
        channels=[
            DeliveryChannel.EPIC_CHAT,
            DeliveryChannel.TEAMS,
            DeliveryChannel.PAGE,
            DeliveryChannel.DASHBOARD,
        ],
        requires_acknowledgment=True,
    ),
}


# Type alias for channel send functions
ChannelSender = Callable[[PreOpCheckResult, RecipientRole, str, str], Awaitable[bool]]


class EscalationEngine:
    """
    Manages alert escalation for surgical prophylaxis.

    Responsibilities:
    - Route alerts to appropriate recipients
    - Track acknowledgments and responses
    - Automatically escalate after timeout
    - Manage multiple delivery channels
    """

    def __init__(
        self,
        rules: Optional[dict[AlertTrigger, EscalationRule]] = None,
        alert_store: Optional[Any] = None,
    ):
        self.rules = rules or DEFAULT_ESCALATION_RULES.copy()
        self.alert_store = alert_store

        # Active escalations (alert_id -> EscalationRecord)
        self._active_escalations: dict[str, EscalationRecord] = {}

        # Channel senders (channel -> async function)
        self._channel_senders: dict[DeliveryChannel, ChannelSender] = {}

        # Provider lookup (role -> provider info)
        self._provider_lookup: Optional[Callable] = None

        # Background escalation task
        self._escalation_task: Optional[asyncio.Task] = None
        self._running = False

    def register_channel_sender(
        self,
        channel: DeliveryChannel,
        sender: ChannelSender,
    ) -> None:
        """Register a function to send alerts via a specific channel."""
        self._channel_senders[channel] = sender

    def set_provider_lookup(
        self,
        lookup: Callable[[RecipientRole, str], tuple[str, str]],
    ) -> None:
        """
        Set function to look up provider info for a role.

        Function should return (provider_id, provider_name) for a given role
        and context (e.g., OR location, surgeon ID).
        """
        self._provider_lookup = lookup

    async def send_alert(
        self,
        check_result: PreOpCheckResult,
        trigger: AlertTrigger,
    ) -> Optional[EscalationRecord]:
        """
        Send an alert and set up escalation tracking.

        Args:
            check_result: The pre-op check result
            trigger: The trigger that caused this alert

        Returns:
            EscalationRecord if alert was sent, None otherwise
        """
        if not check_result.alert_required:
            logger.debug(f"No alert required for {check_result.case_id}")
            return None

        rule = self.rules.get(trigger)
        if not rule:
            logger.warning(f"No escalation rule for trigger {trigger}")
            return None

        # Create escalation record
        alert_id = self._generate_alert_id(check_result, trigger)
        record = EscalationRecord(
            escalation_id=f"esc-{alert_id}",
            alert_id=alert_id,
            journey_id=check_result.journey_id,
            trigger=trigger,
            current_role=rule.primary_role,
            created_at=datetime.now(),
        )

        # Look up recipient
        if self._provider_lookup:
            try:
                provider_id, provider_name = self._provider_lookup(
                    rule.primary_role,
                    check_result.case_id,
                )
                record.current_recipient_id = provider_id
                record.current_recipient_name = provider_name
            except Exception as e:
                logger.error(f"Error looking up provider: {e}")

        # Send via configured channels
        await self._send_via_channels(check_result, record, rule.channels)

        # Schedule escalation if needed
        if rule.requires_acknowledgment and rule.escalation_role:
            record.next_escalation_at = datetime.now() + timedelta(
                minutes=rule.escalation_delay_minutes
            )

        # Store in alert store if available
        if self.alert_store:
            await self._save_to_alert_store(check_result, record)

        # Track active escalation
        self._active_escalations[alert_id] = record

        logger.info(
            f"Alert {alert_id} sent to {record.current_role.value} "
            f"for patient {check_result.patient_mrn}"
        )

        return record

    async def _send_via_channels(
        self,
        check_result: PreOpCheckResult,
        record: EscalationRecord,
        channels: list[DeliveryChannel],
    ) -> None:
        """Send alert via multiple channels."""
        for channel in channels:
            if channel not in self._channel_senders:
                logger.warning(f"No sender registered for channel {channel}")
                continue

            try:
                success = await self._channel_senders[channel](
                    check_result,
                    record.current_role,
                    record.current_recipient_id or "",
                    record.current_recipient_name or "",
                )
                if success:
                    record.channels_sent.append(channel)
                    logger.debug(f"Alert sent via {channel.value}")
            except Exception as e:
                logger.error(f"Error sending via {channel}: {e}")

        record.sent_at = datetime.now()
        record.delivery_status = "sent" if record.channels_sent else "failed"

    async def _save_to_alert_store(
        self,
        check_result: PreOpCheckResult,
        record: EscalationRecord,
    ) -> None:
        """Save alert to the common alert store."""
        if not self.alert_store:
            return

        try:
            from common.alert_store.models import AlertType

            content = {
                "trigger": record.trigger.value,
                "severity": check_result.alert_severity.value,
                "procedure": check_result.procedure_description,
                "minutes_to_or": check_result.minutes_to_or,
                "prophylaxis_indicated": check_result.prophylaxis_indicated,
                "order_exists": check_result.order_exists,
                "administered": check_result.administered,
                "first_line_agents": check_result.first_line_agents,
                "current_recipient_role": record.current_role.value,
                "current_recipient_name": record.current_recipient_name,
            }

            stored = self.alert_store.save_alert(
                alert_type=AlertType.SURGICAL_PROPHYLAXIS,
                source_id=record.alert_id,
                severity=check_result.alert_severity.value,
                patient_mrn=check_result.patient_mrn,
                patient_name=check_result.patient_name,
                title=self._build_alert_title(check_result, record),
                summary=check_result.recommendation[:200] if check_result.recommendation else "",
                content=content,
            )

            if stored:
                self.alert_store.mark_sent(stored.id)

        except Exception as e:
            logger.error(f"Error saving to alert store: {e}")

    def _build_alert_title(
        self,
        check_result: PreOpCheckResult,
        record: EscalationRecord,
    ) -> str:
        """Build a concise alert title."""
        severity_prefix = {
            AlertSeverity.CRITICAL: "CRITICAL: ",
            AlertSeverity.WARNING: "WARNING: ",
            AlertSeverity.INFO: "",
        }.get(check_result.alert_severity, "")

        return f"{severity_prefix}Surgical Prophylaxis - {check_result.patient_mrn}"

    def _generate_alert_id(
        self,
        check_result: PreOpCheckResult,
        trigger: AlertTrigger,
    ) -> str:
        """Generate a unique alert ID."""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        return f"sp-{check_result.patient_mrn}-{trigger.value}-{timestamp}"

    async def acknowledge_alert(
        self,
        alert_id: str,
        acknowledged_by: Optional[str] = None,
    ) -> bool:
        """
        Acknowledge an alert, stopping further escalation.

        Args:
            alert_id: The alert ID to acknowledge
            acknowledged_by: Who acknowledged the alert

        Returns:
            True if successfully acknowledged
        """
        record = self._active_escalations.get(alert_id)
        if not record:
            logger.warning(f"No active escalation found for {alert_id}")
            return False

        record.acknowledged = True
        record.response_at = datetime.now()
        record.response_action = "acknowledged"
        record.response_by = acknowledged_by
        record.next_escalation_at = None  # Cancel escalation

        # Update alert store
        if self.alert_store:
            try:
                self.alert_store.acknowledge(alert_id, acknowledged_by)
            except Exception as e:
                logger.error(f"Error acknowledging in alert store: {e}")

        logger.info(f"Alert {alert_id} acknowledged by {acknowledged_by}")
        return True

    async def record_response(
        self,
        alert_id: str,
        action: str,
        responded_by: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> bool:
        """
        Record a response action for an alert.

        Args:
            alert_id: The alert ID
            action: The action taken (e.g., 'order_placed', 'override')
            responded_by: Who responded
            notes: Optional notes

        Returns:
            True if successfully recorded
        """
        record = self._active_escalations.get(alert_id)
        if not record:
            logger.warning(f"No active escalation found for {alert_id}")
            return False

        record.response_at = datetime.now()
        record.response_action = action
        record.response_by = responded_by
        record.next_escalation_at = None  # Cancel escalation

        # Update alert store
        if self.alert_store:
            try:
                from common.alert_store.models import ResolutionReason

                # Map action to resolution reason
                reason_map = {
                    "order_placed": ResolutionReason.THERAPY_CHANGED,
                    "administered": ResolutionReason.THERAPY_CHANGED,
                    "override": ResolutionReason.APPROVED,
                    "not_indicated": ResolutionReason.APPROVED,
                }
                reason = reason_map.get(action, ResolutionReason.OTHER)
                self.alert_store.resolve(alert_id, responded_by, reason, notes)
            except Exception as e:
                logger.error(f"Error resolving in alert store: {e}")

        logger.info(f"Alert {alert_id} responded: {action} by {responded_by}")
        return True

    async def start_escalation_monitor(self) -> None:
        """Start background task to monitor and escalate alerts."""
        if self._running:
            return

        self._running = True
        self._escalation_task = asyncio.create_task(self._escalation_loop())
        logger.info("Escalation monitor started")

    async def stop_escalation_monitor(self) -> None:
        """Stop the escalation monitor."""
        self._running = False
        if self._escalation_task:
            self._escalation_task.cancel()
            try:
                await self._escalation_task
            except asyncio.CancelledError:
                pass
        logger.info("Escalation monitor stopped")

    async def _escalation_loop(self) -> None:
        """Background loop to check for escalations."""
        while self._running:
            try:
                await self._process_pending_escalations()
            except Exception as e:
                logger.error(f"Error in escalation loop: {e}")

            # Check every minute
            await asyncio.sleep(60)

    async def _process_pending_escalations(self) -> None:
        """Process any alerts that need escalation."""
        now = datetime.now()

        for alert_id, record in list(self._active_escalations.items()):
            if record.acknowledged or record.escalated:
                continue

            if record.next_escalation_at and record.next_escalation_at <= now:
                await self._escalate_alert(record)

    async def _escalate_alert(self, record: EscalationRecord) -> None:
        """Escalate an alert to the next level."""
        rule = self.rules.get(record.trigger)
        if not rule:
            return

        # Determine next escalation role
        if record.current_level == 1 and rule.escalation_role:
            next_role = rule.escalation_role
            next_delay = rule.secondary_escalation_delay_minutes
            next_next_role = rule.secondary_escalation_role
        elif record.current_level == 2 and rule.secondary_escalation_role:
            next_role = rule.secondary_escalation_role
            next_delay = 0  # No further escalation
            next_next_role = None
        else:
            # No further escalation
            record.escalated = True
            return

        # Update record
        record.current_level += 1
        record.current_role = next_role

        # Look up new recipient
        if self._provider_lookup:
            try:
                provider_id, provider_name = self._provider_lookup(
                    next_role,
                    record.journey_id or "",
                )
                record.current_recipient_id = provider_id
                record.current_recipient_name = provider_name
            except Exception as e:
                logger.error(f"Error looking up escalation provider: {e}")

        # Re-send via channels
        # Note: Would need to rebuild check_result from stored data
        # For now, just log the escalation
        logger.warning(
            f"Alert {record.alert_id} escalated to level {record.current_level} "
            f"({next_role.value})"
        )

        # Set next escalation time
        if next_delay > 0 and next_next_role:
            record.next_escalation_at = datetime.now() + timedelta(minutes=next_delay)
        else:
            record.next_escalation_at = None
            record.escalated = True

    def get_active_escalations(self) -> list[EscalationRecord]:
        """Get all active (non-acknowledged, non-escalated) escalations."""
        return [
            r for r in self._active_escalations.values()
            if not r.acknowledged and not r.escalated
        ]

    def get_escalation(self, alert_id: str) -> Optional[EscalationRecord]:
        """Get an escalation record by alert ID."""
        return self._active_escalations.get(alert_id)

    def cleanup_old_escalations(self, hours: int = 24) -> int:
        """Remove old escalation records."""
        cutoff = datetime.now() - timedelta(hours=hours)
        to_remove = [
            alert_id
            for alert_id, record in self._active_escalations.items()
            if record.created_at < cutoff
        ]

        for alert_id in to_remove:
            del self._active_escalations[alert_id]

        return len(to_remove)
