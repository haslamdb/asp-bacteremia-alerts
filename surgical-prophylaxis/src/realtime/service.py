"""
Main service orchestrator for real-time surgical prophylaxis monitoring.

Ties together all components:
- HL7 Listener: Receives ADT and scheduling messages
- Location Tracker: Tracks patient journey through surgical workflow
- Schedule Monitor: Polls FHIR for upcoming surgeries
- Pre-Op Checker: Evaluates prophylaxis compliance
- Escalation Engine: Routes alerts with automatic escalation
- State Manager: Coordinates journey state
- Epic Chat: Sends secure messages
"""

import asyncio
import logging
import os
import signal
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .hl7_parser import HL7Message
from .hl7_listener import HL7MLLPServer, MessageHandler, HL7ListenerConfig
from .location_tracker import LocationTracker, LocationPatterns, PatientLocationUpdate, LocationState
from .schedule_monitor import ScheduleMonitor, ScheduledSurgery
from .preop_checker import PreOpChecker, PreOpCheckResult, AlertTrigger, AlertSeverity
from .escalation_engine import EscalationEngine, EscalationRecord, DeliveryChannel, RecipientRole
from .state_manager import StateManager, SurgicalJourney
from .epic_chat import EpicSecureChat, EpicChatConfig, ChatMessage

logger = logging.getLogger(__name__)


@dataclass
class ServiceConfig:
    """Configuration for the real-time prophylaxis service."""

    # HL7 settings
    hl7_enabled: bool = True
    hl7_host: str = "0.0.0.0"
    hl7_port: int = 2575

    # FHIR polling settings
    fhir_schedule_poll_interval: int = 15  # minutes
    fhir_prophylaxis_poll_interval: int = 5  # minutes
    fhir_lookahead_hours: int = 48

    # Alert settings
    alert_t24_enabled: bool = True
    alert_t2_enabled: bool = True
    alert_t60_enabled: bool = True
    alert_t0_enabled: bool = True

    # Channel settings
    epic_chat_enabled: bool = False
    teams_enabled: bool = True
    teams_webhook_url: str = ""

    # Database
    db_path: Optional[str] = None

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        """Create configuration from environment variables."""
        aegis_dir = Path.home() / ".aegis"
        aegis_dir.mkdir(exist_ok=True)

        return cls(
            hl7_enabled=os.getenv("HL7_ENABLED", "true").lower() == "true",
            hl7_host=os.getenv("HL7_LISTENER_HOST", "0.0.0.0"),
            hl7_port=int(os.getenv("HL7_LISTENER_PORT", "2575")),
            fhir_schedule_poll_interval=int(os.getenv("FHIR_SCHEDULE_POLL_INTERVAL", "15")),
            fhir_prophylaxis_poll_interval=int(os.getenv("FHIR_PROPHYLAXIS_POLL_INTERVAL", "5")),
            fhir_lookahead_hours=int(os.getenv("FHIR_LOOKAHEAD_HOURS", "48")),
            alert_t24_enabled=os.getenv("ALERT_T24_ENABLED", "true").lower() == "true",
            alert_t2_enabled=os.getenv("ALERT_T2_ENABLED", "true").lower() == "true",
            alert_t60_enabled=os.getenv("ALERT_T60_ENABLED", "true").lower() == "true",
            alert_t0_enabled=os.getenv("ALERT_T0_ENABLED", "true").lower() == "true",
            epic_chat_enabled=os.getenv("EPIC_CHAT_ENABLED", "false").lower() == "true",
            teams_enabled=os.getenv("TEAMS_FALLBACK_ENABLED", "true").lower() == "true",
            teams_webhook_url=os.getenv("TEAMS_SURGICAL_PROPHYLAXIS_WEBHOOK", ""),
            db_path=str(aegis_dir / "surgical_prophylaxis.db"),
        )


class RealtimeProphylaxisService:
    """
    Main orchestrator for real-time surgical prophylaxis monitoring.

    Coordinates all components and manages the event loop.
    """

    def __init__(
        self,
        config: Optional[ServiceConfig] = None,
        fhir_client: Optional[Any] = None,
        alert_store: Optional[Any] = None,
        guidelines_config: Optional[Any] = None,
    ):
        self.config = config or ServiceConfig.from_env()

        # External dependencies
        self.fhir_client = fhir_client
        self.alert_store = alert_store
        self.guidelines_config = guidelines_config

        # Initialize components
        self._init_components()

        # Running state
        self._running = False
        self._tasks: list[asyncio.Task] = []

    def _init_components(self) -> None:
        """Initialize all service components."""
        # State manager (must be first as others depend on it)
        self.state_manager = StateManager(db_path=self.config.db_path)

        # Location tracker
        self.location_tracker = LocationTracker()
        self.location_tracker.on_pre_op_arrival = self._handle_preop_arrival
        self.location_tracker.on_or_entry = self._handle_or_entry
        self.location_tracker.on_pacu_arrival = self._handle_pacu_arrival

        # Schedule monitor
        self.schedule_monitor = ScheduleMonitor(
            fhir_client=self.fhir_client,
            poll_interval_minutes=self.config.fhir_schedule_poll_interval,
            lookahead_hours=self.config.fhir_lookahead_hours,
        )
        self.schedule_monitor.on_new_surgery = self._handle_new_surgery
        self.schedule_monitor.on_surgery_updated = self._handle_surgery_updated

        # Pre-op checker
        self.preop_checker = PreOpChecker(
            guidelines_config=self.guidelines_config,
            fhir_client=self.fhir_client,
        )

        # Escalation engine
        self.escalation_engine = EscalationEngine(alert_store=self.alert_store)
        self._register_channel_senders()

        # Epic Secure Chat
        self.epic_chat = EpicSecureChat(
            EpicChatConfig(enabled=self.config.epic_chat_enabled)
        )

        # HL7 Listener
        if self.config.hl7_enabled:
            hl7_config = HL7ListenerConfig(
                host=self.config.hl7_host,
                port=self.config.hl7_port,
                enabled=self.config.hl7_enabled,
            )
            handler = MessageHandler()
            handler.on_adt = self._handle_adt_message
            handler.on_orm = self._handle_scheduling_message
            handler.on_siu = self._handle_scheduling_message
            self.hl7_listener = HL7MLLPServer(handler=handler, config=hl7_config)
        else:
            self.hl7_listener = None

        # Teams channel (for fallback)
        self.teams_channel = None
        if self.config.teams_enabled and self.config.teams_webhook_url:
            try:
                from common.channels.teams import TeamsWebhookChannel
                self.teams_channel = TeamsWebhookChannel(self.config.teams_webhook_url)
            except ImportError:
                logger.warning("Teams channel not available")

    def _register_channel_senders(self) -> None:
        """Register channel senders with the escalation engine."""

        async def send_via_teams(
            result: PreOpCheckResult,
            role: RecipientRole,
            recipient_id: str,
            recipient_name: str,
        ) -> bool:
            """Send alert via Teams webhook."""
            if not self.teams_channel:
                return False

            try:
                from common.channels.teams import TeamsMessage

                message = TeamsMessage(
                    title=f"Surgical Prophylaxis Alert - {result.patient_mrn}",
                    facts=[
                        ("Patient", f"{result.patient_name} ({result.patient_mrn})"),
                        ("Procedure", result.procedure_description or "Unknown"),
                        ("Trigger", result.trigger.value),
                        ("Severity", result.alert_severity.value.upper()),
                        ("Recipient", f"{recipient_name} ({role.value})"),
                    ],
                    text=result.recommendation,
                    color="Attention" if result.alert_severity == AlertSeverity.CRITICAL else "Warning",
                )

                return self.teams_channel.send(message)
            except Exception as e:
                logger.error(f"Error sending Teams message: {e}")
                return False

        async def send_via_epic_chat(
            result: PreOpCheckResult,
            role: RecipientRole,
            recipient_id: str,
            recipient_name: str,
        ) -> bool:
            """Send alert via Epic Secure Chat."""
            if not self.epic_chat.is_configured:
                return False

            try:
                from .epic_chat import send_prophylaxis_alert

                subject = f"Surgical Prophylaxis Alert - {result.alert_severity.value.upper()}"
                comm_id = await send_prophylaxis_alert(
                    chat=self.epic_chat,
                    provider_id=recipient_id,
                    provider_name=recipient_name,
                    patient_id=result.patient_mrn,  # Would need actual FHIR ID
                    patient_mrn=result.patient_mrn,
                    subject=subject,
                    message_body=result.recommendation,
                )

                return comm_id is not None
            except Exception as e:
                logger.error(f"Error sending Epic Chat message: {e}")
                return False

        async def send_via_dashboard(
            result: PreOpCheckResult,
            role: RecipientRole,
            recipient_id: str,
            recipient_name: str,
        ) -> bool:
            """Record alert in dashboard (always succeeds)."""
            # Dashboard alerts are recorded via alert_store in escalation_engine
            return True

        # Register senders
        self.escalation_engine.register_channel_sender(
            DeliveryChannel.TEAMS,
            send_via_teams,
        )
        self.escalation_engine.register_channel_sender(
            DeliveryChannel.EPIC_CHAT,
            send_via_epic_chat,
        )
        self.escalation_engine.register_channel_sender(
            DeliveryChannel.DASHBOARD,
            send_via_dashboard,
        )

    async def start(self) -> None:
        """Start all service components."""
        if self._running:
            logger.warning("Service already running")
            return

        logger.info("Starting Real-time Surgical Prophylaxis Service")

        self._running = True

        # Load active journeys from database
        self.state_manager.load_active_journeys()

        # Start HL7 listener
        if self.hl7_listener:
            await self.hl7_listener.start()

        # Start schedule monitor polling
        await self.schedule_monitor.start_polling()

        # Start escalation monitor
        await self.escalation_engine.start_escalation_monitor()

        # Start scheduled check loop
        self._tasks.append(asyncio.create_task(self._scheduled_check_loop()))

        # Start prophylaxis status check loop
        self._tasks.append(asyncio.create_task(self._prophylaxis_status_loop()))

        logger.info("Real-time Surgical Prophylaxis Service started")

    async def stop(self) -> None:
        """Stop all service components."""
        if not self._running:
            return

        logger.info("Stopping Real-time Surgical Prophylaxis Service")

        self._running = False

        # Cancel background tasks
        for task in self._tasks:
            task.cancel()

        # Wait for tasks to finish
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()

        # Stop components
        await self.schedule_monitor.stop_polling()
        await self.escalation_engine.stop_escalation_monitor()

        if self.hl7_listener:
            await self.hl7_listener.stop()

        logger.info("Real-time Surgical Prophylaxis Service stopped")

    async def run(self) -> None:
        """Run the service until interrupted."""
        await self.start()

        # Set up signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self.stop()))

        # Wait until stopped
        while self._running:
            await asyncio.sleep(1)

    # Event handlers

    async def _handle_adt_message(self, message: HL7Message) -> None:
        """Handle an ADT message from HL7 listener."""
        location_update = await self.location_tracker.process_adt(message)

        if location_update:
            # Update journey state
            self.state_manager.update_location(location_update)

    async def _handle_scheduling_message(self, message: HL7Message) -> None:
        """Handle a scheduling message (ORM or SIU) from HL7 listener."""
        surgery = await self.schedule_monitor.process_scheduling_message(message)

        # New surgeries are handled via on_new_surgery callback

    async def _handle_new_surgery(self, surgery: ScheduledSurgery) -> None:
        """Handle a new surgery appearing in the schedule."""
        logger.info(f"New surgery: {surgery.case_id} for patient {surgery.patient_mrn}")

        # Create journey if not exists
        existing = self.state_manager.get_journey_for_case(surgery.case_id)
        if not existing:
            journey = self.state_manager.create_journey(surgery)
            surgery.journey_id = journey.journey_id

            # Check if T-24h alert needed
            if self.config.alert_t24_enabled and surgery.minutes_until_surgery:
                if 23 * 60 < surgery.minutes_until_surgery <= 25 * 60:
                    await self._check_and_alert(surgery, AlertTrigger.T24)

    async def _handle_surgery_updated(self, surgery: ScheduledSurgery) -> None:
        """Handle a surgery being updated."""
        logger.debug(f"Surgery updated: {surgery.case_id}")

        # Update journey if exists
        journey = self.state_manager.get_journey_for_case(surgery.case_id)
        if journey:
            journey.scheduled_time = surgery.scheduled_time
            journey.procedure_description = surgery.procedure_description
            journey.updated_at = datetime.now()

    async def _handle_preop_arrival(self, update: PatientLocationUpdate) -> None:
        """Handle patient arriving at pre-op holding."""
        logger.info(
            f"Patient {update.patient_mrn} arrived at pre-op ({update.new_location_code})"
        )

        if not self.config.alert_t2_enabled:
            return

        # Get associated surgery
        surgeries = self.schedule_monitor.get_surgeries_for_patient(update.patient_mrn)
        upcoming = [s for s in surgeries if not s.is_past]

        if upcoming:
            surgery = upcoming[0]  # Take soonest surgery
            await self._check_and_alert(surgery, AlertTrigger.PREOP_ARRIVAL, update)
        else:
            # No scheduled surgery - check if this is a concern
            result = await self.preop_checker.check_on_preop_arrival(update)
            if result.alert_required:
                await self.escalation_engine.send_alert(result, AlertTrigger.PREOP_ARRIVAL)

    async def _handle_or_entry(self, update: PatientLocationUpdate) -> None:
        """Handle patient entering the OR - critical moment."""
        logger.warning(
            f"CRITICAL: Patient {update.patient_mrn} entering OR ({update.new_location_code})"
        )

        if not self.config.alert_t0_enabled:
            return

        # Get associated surgery
        surgeries = self.schedule_monitor.get_surgeries_for_patient(update.patient_mrn)
        upcoming = [s for s in surgeries if not s.is_past]

        if upcoming:
            surgery = upcoming[0]
            await self._check_and_alert(surgery, AlertTrigger.OR_ENTRY, update)
        else:
            # No scheduled surgery - CRITICAL
            result = await self.preop_checker.check_on_or_entry(update)
            if result.alert_required:
                await self.escalation_engine.send_alert(result, AlertTrigger.OR_ENTRY)

    async def _handle_pacu_arrival(self, update: PatientLocationUpdate) -> None:
        """Handle patient arriving at PACU - surgery complete."""
        logger.info(f"Patient {update.patient_mrn} in PACU - surgery complete")

        # Mark journey complete
        journey = self.state_manager.get_journey_for_patient(update.patient_mrn)
        if journey:
            self.state_manager.complete_journey(journey.journey_id, "completed")

    async def _check_and_alert(
        self,
        surgery: ScheduledSurgery,
        trigger: AlertTrigger,
        location_update: Optional[PatientLocationUpdate] = None,
    ) -> None:
        """Perform a prophylaxis check and send alert if needed."""
        # Get or create journey
        journey = self.state_manager.get_journey_for_case(surgery.case_id)
        if not journey:
            journey = self.state_manager.create_journey(surgery)

        # Check if alert already sent for this trigger
        if trigger == AlertTrigger.T24 and journey.alert_t24_sent:
            return
        if trigger in (AlertTrigger.T2, AlertTrigger.PREOP_ARRIVAL) and journey.alert_t2_sent:
            return
        if trigger == AlertTrigger.T60 and journey.alert_t60_sent:
            return
        if trigger in (AlertTrigger.T0, AlertTrigger.OR_ENTRY) and journey.alert_t0_sent:
            return

        # Perform check
        result = await self.preop_checker.check_at_trigger(surgery, trigger, location_update)
        result.journey_id = journey.journey_id

        # Record check result
        alert_id = None
        if result.alert_required:
            # Send alert
            record = await self.escalation_engine.send_alert(result, trigger)
            if record:
                alert_id = record.alert_id

            # Mark alert sent on journey
            self.state_manager.mark_alert_sent(journey.journey_id, trigger)
            self.schedule_monitor.mark_alert_sent(surgery.case_id, trigger.value)

        # Record check in database
        self.state_manager.record_check_result(journey.journey_id, result, alert_id)

    async def _scheduled_check_loop(self) -> None:
        """Background loop to check surgeries at scheduled times."""
        while self._running:
            try:
                # Get surgeries needing alerts at each trigger point
                needing_alerts = self.schedule_monitor.get_surgeries_needing_alerts()

                # T-24h checks
                if self.config.alert_t24_enabled:
                    for surgery in needing_alerts.get("t24", []):
                        await self._check_and_alert(surgery, AlertTrigger.T24)

                # T-2h checks (if not using location triggers)
                if self.config.alert_t2_enabled:
                    for surgery in needing_alerts.get("t2", []):
                        await self._check_and_alert(surgery, AlertTrigger.T2)

                # T-60m checks
                if self.config.alert_t60_enabled:
                    for surgery in needing_alerts.get("t60", []):
                        await self._check_and_alert(surgery, AlertTrigger.T60)

                # T-0 checks (if not using location triggers)
                if self.config.alert_t0_enabled:
                    for surgery in needing_alerts.get("t0", []):
                        await self._check_and_alert(surgery, AlertTrigger.T0)

            except Exception as e:
                logger.error(f"Error in scheduled check loop: {e}")

            # Run every minute
            await asyncio.sleep(60)

    async def _prophylaxis_status_loop(self) -> None:
        """Background loop to refresh prophylaxis status from FHIR."""
        while self._running:
            try:
                if self.fhir_client:
                    # Refresh prophylaxis status for active journeys
                    for journey in self.state_manager.get_active_journeys():
                        if journey.prophylaxis_indicated and not journey.administered:
                            # Check for new orders/administrations
                            orders = await self.preop_checker._get_prophylaxis_orders(
                                journey.patient_mrn
                            )
                            admins = await self.preop_checker._get_prophylaxis_administrations(
                                journey.patient_mrn
                            )

                            self.state_manager.update_prophylaxis_status(
                                journey.journey_id,
                                order_exists=bool(orders),
                                administered=bool(admins),
                            )

            except Exception as e:
                logger.error(f"Error in prophylaxis status loop: {e}")

            # Run every N minutes
            await asyncio.sleep(self.config.fhir_prophylaxis_poll_interval * 60)

    # Status and statistics

    def get_status(self) -> dict:
        """Get current service status."""
        return {
            "running": self._running,
            "hl7_listener": self.hl7_listener.get_stats() if self.hl7_listener else None,
            "schedule_monitor": {
                "total_surgeries": len(self.schedule_monitor.all_surgeries),
                "upcoming_24h": len(self.schedule_monitor.get_upcoming_surgeries(24)),
            },
            "state_manager": {
                "active_journeys": len(self.state_manager.get_active_journeys()),
            },
            "escalation_engine": {
                "active_escalations": len(self.escalation_engine.get_active_escalations()),
            },
            "channels": {
                "epic_chat": self.epic_chat.is_configured,
                "teams": self.teams_channel is not None,
            },
        }


def main():
    """Entry point for running the service."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Real-time Surgical Prophylaxis Monitoring Service"
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Create and run service
    service = RealtimeProphylaxisService()

    try:
        asyncio.run(service.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
