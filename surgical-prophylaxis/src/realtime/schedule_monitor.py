"""
Schedule monitor for tracking upcoming surgeries.

Polls FHIR Appointment resources and processes HL7 ORM/SIU messages
to maintain a list of upcoming surgeries that need prophylaxis monitoring.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Optional, Awaitable

from .hl7_parser import HL7Message, extract_orm_o01_data, extract_siu_s12_data

logger = logging.getLogger(__name__)


@dataclass
class ScheduledSurgery:
    """Represents a scheduled surgery for prophylaxis monitoring."""

    case_id: str
    patient_mrn: str
    patient_name: Optional[str] = None

    # Procedure details
    procedure_description: Optional[str] = None
    procedure_cpt_codes: list[str] = field(default_factory=list)
    scheduled_time: Optional[datetime] = None
    estimated_duration_minutes: Optional[int] = None
    or_location: Optional[str] = None

    # Staff
    surgeon_id: Optional[str] = None
    surgeon_name: Optional[str] = None
    anesthesiologist_id: Optional[str] = None
    anesthesiologist_name: Optional[str] = None

    # Prophylaxis status
    prophylaxis_indicated: bool = False
    prophylaxis_requirements: Optional[dict] = None
    prophylaxis_order_exists: bool = False
    prophylaxis_administered: bool = False

    # Alert tracking
    alert_t24_sent: bool = False
    alert_t2_sent: bool = False
    alert_t60_sent: bool = False
    alert_t0_sent: bool = False

    # Source tracking
    source: str = "unknown"  # 'fhir_appointment', 'hl7_orm', 'hl7_siu', 'manual'
    fhir_appointment_id: Optional[str] = None
    hl7_message_id: Optional[str] = None

    # Journey tracking
    journey_id: Optional[str] = None

    # Timestamps
    first_seen_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @property
    def minutes_until_surgery(self) -> Optional[int]:
        """Calculate minutes until scheduled surgery time."""
        if not self.scheduled_time:
            return None
        delta = self.scheduled_time - datetime.now()
        return int(delta.total_seconds() / 60)

    @property
    def is_past(self) -> bool:
        """Check if surgery time has passed."""
        if not self.scheduled_time:
            return False
        return self.scheduled_time < datetime.now()

    @property
    def is_today(self) -> bool:
        """Check if surgery is scheduled for today."""
        if not self.scheduled_time:
            return False
        return self.scheduled_time.date() == datetime.now().date()


# Type alias for surgery callback
SurgeryCallback = Callable[[ScheduledSurgery], Awaitable[None]]


class ScheduleMonitor:
    """
    Monitors the OR schedule for upcoming surgeries.

    Integrates with:
    - FHIR Appointment resources (primary)
    - HL7 ORM O01 messages (backup)
    - HL7 SIU S12 messages (backup)
    """

    def __init__(
        self,
        fhir_client: Optional[Any] = None,
        poll_interval_minutes: int = 15,
        lookahead_hours: int = 48,
    ):
        self.fhir_client = fhir_client
        self.poll_interval_minutes = poll_interval_minutes
        self.lookahead_hours = lookahead_hours

        # Scheduled surgeries cache (case_id -> ScheduledSurgery)
        self._surgeries: dict[str, ScheduledSurgery] = {}

        # Callbacks
        self.on_new_surgery: Optional[SurgeryCallback] = None
        self.on_surgery_updated: Optional[SurgeryCallback] = None
        self.on_surgery_cancelled: Optional[SurgeryCallback] = None

        # Polling control
        self._polling = False
        self._poll_task: Optional[asyncio.Task] = None

    async def start_polling(self) -> None:
        """Start background FHIR polling."""
        if self._polling:
            logger.warning("Polling already started")
            return

        self._polling = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info(
            f"Schedule monitor started, polling every {self.poll_interval_minutes} minutes"
        )

    async def stop_polling(self) -> None:
        """Stop background FHIR polling."""
        self._polling = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("Schedule monitor stopped")

    async def _poll_loop(self) -> None:
        """Background polling loop."""
        while self._polling:
            try:
                await self.poll_fhir_schedule()
            except Exception as e:
                logger.error(f"Error polling FHIR schedule: {e}")

            # Wait for next poll interval
            await asyncio.sleep(self.poll_interval_minutes * 60)

    async def poll_fhir_schedule(self) -> list[ScheduledSurgery]:
        """
        Poll FHIR Appointment resources for upcoming surgeries.

        Returns:
            List of new or updated scheduled surgeries
        """
        if not self.fhir_client:
            logger.warning("No FHIR client configured, skipping poll")
            return []

        start_time = datetime.now()
        end_time = start_time + timedelta(hours=self.lookahead_hours)

        logger.debug(
            f"Polling FHIR appointments from {start_time} to {end_time}"
        )

        try:
            appointments = await self._fetch_fhir_appointments(start_time, end_time)
        except Exception as e:
            logger.error(f"Failed to fetch FHIR appointments: {e}")
            return []

        new_or_updated = []

        for appointment in appointments:
            surgery = self._appointment_to_surgery(appointment)
            if surgery:
                existing = self._surgeries.get(surgery.case_id)

                if not existing:
                    # New surgery
                    surgery.first_seen_at = datetime.now()
                    surgery.updated_at = datetime.now()
                    self._surgeries[surgery.case_id] = surgery
                    new_or_updated.append(surgery)

                    if self.on_new_surgery:
                        try:
                            await self.on_new_surgery(surgery)
                        except Exception as e:
                            logger.error(f"Error in on_new_surgery callback: {e}")

                elif self._surgery_changed(existing, surgery):
                    # Update existing
                    surgery.first_seen_at = existing.first_seen_at
                    surgery.updated_at = datetime.now()
                    surgery.alert_t24_sent = existing.alert_t24_sent
                    surgery.alert_t2_sent = existing.alert_t2_sent
                    surgery.alert_t60_sent = existing.alert_t60_sent
                    surgery.alert_t0_sent = existing.alert_t0_sent
                    surgery.journey_id = existing.journey_id
                    self._surgeries[surgery.case_id] = surgery
                    new_or_updated.append(surgery)

                    if self.on_surgery_updated:
                        try:
                            await self.on_surgery_updated(surgery)
                        except Exception as e:
                            logger.error(f"Error in on_surgery_updated callback: {e}")

        logger.info(
            f"FHIR poll complete: {len(appointments)} appointments, "
            f"{len(new_or_updated)} new/updated"
        )

        return new_or_updated

    async def _fetch_fhir_appointments(
        self,
        start_time: datetime,
        end_time: datetime,
    ) -> list[dict]:
        """
        Fetch FHIR Appointment resources.

        Override this method to use your FHIR client implementation.
        """
        # This is a placeholder - actual implementation depends on FHIR client
        # Expected return: list of FHIR Appointment resources
        params = {
            "service-type": "surgery",
            "date": [
                f"ge{start_time.isoformat()}",
                f"le{end_time.isoformat()}",
            ],
            "status": "booked,arrived,checked-in",
            "_include": "Appointment:patient",
            "_count": 100,
        }

        # Use FHIR client to fetch appointments
        if hasattr(self.fhir_client, "get_appointments"):
            return await self.fhir_client.get_appointments(params)
        elif hasattr(self.fhir_client, "_get_all_pages"):
            # Synchronous client - wrap in executor
            import asyncio
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.fhir_client._get_all_pages("Appointment", params)
            )

        return []

    def _appointment_to_surgery(self, appointment: dict) -> Optional[ScheduledSurgery]:
        """Convert FHIR Appointment to ScheduledSurgery."""
        try:
            appointment_id = appointment.get("id", "")
            if not appointment_id:
                return None

            # Extract patient info from participants
            patient_mrn = ""
            patient_name = ""
            surgeon_id = ""
            surgeon_name = ""
            anesthesiologist_id = ""
            anesthesiologist_name = ""

            for participant in appointment.get("participant", []):
                actor = participant.get("actor", {})
                actor_ref = actor.get("reference", "")
                actor_type = participant.get("type", [{}])[0].get("coding", [{}])[0].get("code", "")

                if "Patient/" in actor_ref:
                    patient_mrn = self._extract_patient_mrn(actor_ref)
                    patient_name = actor.get("display", "")
                elif actor_type == "ATND" or "surgeon" in actor_type.lower():
                    surgeon_id = actor_ref.replace("Practitioner/", "")
                    surgeon_name = actor.get("display", "")
                elif "anes" in actor_type.lower():
                    anesthesiologist_id = actor_ref.replace("Practitioner/", "")
                    anesthesiologist_name = actor.get("display", "")

            if not patient_mrn:
                logger.warning(f"No patient MRN in appointment {appointment_id}")
                return None

            # Extract scheduled time
            scheduled_time = None
            start = appointment.get("start")
            if start:
                scheduled_time = datetime.fromisoformat(start.replace("Z", "+00:00"))

            # Extract procedure info from service type
            procedure_description = ""
            procedure_cpt_codes = []
            for service_type in appointment.get("serviceType", []):
                for coding in service_type.get("coding", []):
                    if coding.get("system", "").endswith("cpt"):
                        procedure_cpt_codes.append(coding.get("code", ""))
                    if coding.get("display"):
                        procedure_description = coding["display"]
                if service_type.get("text"):
                    procedure_description = procedure_description or service_type["text"]

            # Extract location
            or_location = ""
            for participant in appointment.get("participant", []):
                actor = participant.get("actor", {})
                if "Location/" in actor.get("reference", ""):
                    or_location = actor.get("display", "")

            # Extract duration
            duration_minutes = appointment.get("minutesDuration")

            return ScheduledSurgery(
                case_id=appointment_id,
                patient_mrn=patient_mrn,
                patient_name=patient_name,
                procedure_description=procedure_description,
                procedure_cpt_codes=procedure_cpt_codes,
                scheduled_time=scheduled_time,
                estimated_duration_minutes=duration_minutes,
                or_location=or_location,
                surgeon_id=surgeon_id,
                surgeon_name=surgeon_name,
                anesthesiologist_id=anesthesiologist_id,
                anesthesiologist_name=anesthesiologist_name,
                source="fhir_appointment",
                fhir_appointment_id=appointment_id,
            )

        except Exception as e:
            logger.error(f"Error converting appointment to surgery: {e}")
            return None

    def _extract_patient_mrn(self, patient_ref: str) -> str:
        """Extract patient MRN from FHIR reference."""
        # This is a placeholder - actual implementation may need to
        # fetch the Patient resource to get the MRN
        return patient_ref.replace("Patient/", "")

    def _surgery_changed(
        self,
        existing: ScheduledSurgery,
        new: ScheduledSurgery,
    ) -> bool:
        """Check if surgery details have changed."""
        return (
            existing.scheduled_time != new.scheduled_time
            or existing.or_location != new.or_location
            or existing.surgeon_id != new.surgeon_id
            or existing.procedure_description != new.procedure_description
        )

    async def process_scheduling_message(
        self,
        message: HL7Message,
    ) -> Optional[ScheduledSurgery]:
        """
        Process an HL7 scheduling message (ORM or SIU).

        Args:
            message: Parsed HL7 message

        Returns:
            ScheduledSurgery if created/updated, None otherwise
        """
        if message.message_type == "ORM":
            return await self._process_orm_message(message)
        elif message.message_type == "SIU":
            return await self._process_siu_message(message)
        else:
            logger.debug(f"Ignoring message type {message.message_type}")
            return None

    async def _process_orm_message(
        self,
        message: HL7Message,
    ) -> Optional[ScheduledSurgery]:
        """Process ORM^O01 message for surgery scheduling."""
        data = extract_orm_o01_data(message)
        patient_mrn = data.get("patient_mrn")

        if not patient_mrn:
            return None

        for order in data.get("orders", []):
            # Look for new surgical orders
            if order.get("order_control") not in ("NW", "SC"):  # New or Schedule
                continue

            scheduled_time = order.get("scheduled_datetime")
            if not scheduled_time:
                continue

            case_id = f"hl7-{order.get('placer_order_number', '')}"

            surgery = ScheduledSurgery(
                case_id=case_id,
                patient_mrn=patient_mrn,
                patient_name=data.get("patient_name"),
                procedure_description=order.get("procedure_name"),
                procedure_cpt_codes=[order.get("procedure_code")] if order.get("procedure_code") else [],
                scheduled_time=scheduled_time,
                source="hl7_orm",
                hl7_message_id=data.get("message_control_id"),
            )

            # Check if exists
            existing = self._surgeries.get(case_id)

            if not existing:
                surgery.first_seen_at = datetime.now()
                surgery.updated_at = datetime.now()
                self._surgeries[case_id] = surgery

                if self.on_new_surgery:
                    try:
                        await self.on_new_surgery(surgery)
                    except Exception as e:
                        logger.error(f"Error in on_new_surgery callback: {e}")
            else:
                surgery.first_seen_at = existing.first_seen_at
                surgery.updated_at = datetime.now()
                surgery.alert_t24_sent = existing.alert_t24_sent
                surgery.alert_t2_sent = existing.alert_t2_sent
                surgery.alert_t60_sent = existing.alert_t60_sent
                surgery.alert_t0_sent = existing.alert_t0_sent
                surgery.journey_id = existing.journey_id
                self._surgeries[case_id] = surgery

                if self.on_surgery_updated:
                    try:
                        await self.on_surgery_updated(surgery)
                    except Exception as e:
                        logger.error(f"Error in on_surgery_updated callback: {e}")

            return surgery

        return None

    async def _process_siu_message(
        self,
        message: HL7Message,
    ) -> Optional[ScheduledSurgery]:
        """Process SIU^S12 message for schedule notification."""
        data = extract_siu_s12_data(message)
        patient_mrn = data.get("patient_mrn")

        if not patient_mrn:
            return None

        for appointment in data.get("appointments", []):
            scheduled_time = appointment.get("start_time")
            if not scheduled_time:
                continue

            case_id = f"siu-{appointment.get('filler_appointment_id', '')}"

            surgery = ScheduledSurgery(
                case_id=case_id,
                patient_mrn=patient_mrn,
                patient_name=data.get("patient_name"),
                procedure_description=appointment.get("service_name"),
                procedure_cpt_codes=[appointment.get("service_code")] if appointment.get("service_code") else [],
                scheduled_time=scheduled_time,
                or_location=appointment.get("location"),
                source="hl7_siu",
                hl7_message_id=data.get("message_control_id"),
            )

            existing = self._surgeries.get(case_id)

            if not existing:
                surgery.first_seen_at = datetime.now()
                surgery.updated_at = datetime.now()
                self._surgeries[case_id] = surgery

                if self.on_new_surgery:
                    try:
                        await self.on_new_surgery(surgery)
                    except Exception as e:
                        logger.error(f"Error in on_new_surgery callback: {e}")

            return surgery

        return None

    def get_surgery(self, case_id: str) -> Optional[ScheduledSurgery]:
        """Get a scheduled surgery by case ID."""
        return self._surgeries.get(case_id)

    def get_surgeries_for_patient(self, patient_mrn: str) -> list[ScheduledSurgery]:
        """Get all scheduled surgeries for a patient."""
        return [s for s in self._surgeries.values() if s.patient_mrn == patient_mrn]

    def get_upcoming_surgeries(self, hours: int = 24) -> list[ScheduledSurgery]:
        """Get surgeries scheduled within the next N hours."""
        cutoff = datetime.now() + timedelta(hours=hours)
        return [
            s for s in self._surgeries.values()
            if s.scheduled_time and datetime.now() < s.scheduled_time <= cutoff
        ]

    def get_surgeries_needing_alerts(self) -> dict[str, list[ScheduledSurgery]]:
        """
        Get surgeries that need alerts at each trigger point.

        Returns:
            Dict with keys 't24', 't2', 't60', 't0' containing surgeries
            that need alerts at each trigger point.
        """
        now = datetime.now()
        result = {
            "t24": [],
            "t2": [],
            "t60": [],
            "t0": [],
        }

        for surgery in self._surgeries.values():
            if not surgery.scheduled_time or surgery.is_past:
                continue

            minutes_until = surgery.minutes_until_surgery

            # T-24h: 24 hours before surgery
            if (
                not surgery.alert_t24_sent
                and minutes_until is not None
                and 23 * 60 < minutes_until <= 25 * 60  # 23-25 hour window
            ):
                result["t24"].append(surgery)

            # T-2h: 2 hours before surgery
            elif (
                not surgery.alert_t2_sent
                and minutes_until is not None
                and 90 < minutes_until <= 150  # 1.5-2.5 hour window
            ):
                result["t2"].append(surgery)

            # T-60m: 60 minutes before surgery
            elif (
                not surgery.alert_t60_sent
                and minutes_until is not None
                and 45 < minutes_until <= 75  # 45-75 minute window
            ):
                result["t60"].append(surgery)

            # T-0: At surgery time (within 15 minutes)
            elif (
                not surgery.alert_t0_sent
                and minutes_until is not None
                and -15 < minutes_until <= 15  # Within 15 minutes either way
            ):
                result["t0"].append(surgery)

        return result

    def mark_alert_sent(
        self,
        case_id: str,
        trigger: str,
    ) -> None:
        """Mark that an alert has been sent for a surgery."""
        surgery = self._surgeries.get(case_id)
        if not surgery:
            return

        if trigger == "t24":
            surgery.alert_t24_sent = True
        elif trigger == "t2":
            surgery.alert_t2_sent = True
        elif trigger == "t60":
            surgery.alert_t60_sent = True
        elif trigger == "t0":
            surgery.alert_t0_sent = True

    def update_prophylaxis_status(
        self,
        case_id: str,
        order_exists: Optional[bool] = None,
        administered: Optional[bool] = None,
    ) -> None:
        """Update prophylaxis status for a surgery."""
        surgery = self._surgeries.get(case_id)
        if not surgery:
            return

        if order_exists is not None:
            surgery.prophylaxis_order_exists = order_exists
        if administered is not None:
            surgery.prophylaxis_administered = administered

    def remove_surgery(self, case_id: str) -> None:
        """Remove a surgery from tracking."""
        self._surgeries.pop(case_id, None)

    def clear_past_surgeries(self, hours_after: int = 24) -> int:
        """
        Remove surgeries that ended more than N hours ago.

        Returns number removed.
        """
        cutoff = datetime.now() - timedelta(hours=hours_after)
        to_remove = [
            case_id
            for case_id, surgery in self._surgeries.items()
            if surgery.scheduled_time and surgery.scheduled_time < cutoff
        ]

        for case_id in to_remove:
            del self._surgeries[case_id]

        return len(to_remove)

    @property
    def all_surgeries(self) -> list[ScheduledSurgery]:
        """Get all tracked surgeries."""
        return list(self._surgeries.values())
