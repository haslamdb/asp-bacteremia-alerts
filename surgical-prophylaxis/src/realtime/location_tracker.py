"""
Patient location tracking state machine for surgical workflow.

Tracks patients as they move through the surgical pathway:
UNKNOWN -> PRE_OP_HOLDING -> OR_SUITE -> PACU -> DISCHARGED

Triggers compliance checks at key transition points.
"""

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Optional, Awaitable

from .hl7_parser import HL7Message, extract_adt_a02_data

logger = logging.getLogger(__name__)


class LocationState(Enum):
    """Patient location states in surgical workflow."""

    UNKNOWN = "unknown"
    INPATIENT = "inpatient"      # General inpatient unit
    PRE_OP_HOLDING = "pre_op"    # Pre-operative holding - triggers T-2h check
    OR_SUITE = "or_suite"        # Operating room - triggers T-0 critical check
    PACU = "pacu"                # Post-anesthesia care unit
    DISCHARGED = "discharged"   # Patient left surgical pathway

    @classmethod
    def from_string(cls, value: str) -> "LocationState":
        """Convert string to LocationState."""
        for state in cls:
            if state.value == value:
                return state
        return cls.UNKNOWN


@dataclass
class LocationPatterns:
    """Configurable patterns for matching location codes to states."""

    # Patterns are checked in order - first match wins
    pre_op_patterns: list[str] = field(
        default_factory=lambda: [
            r"PREOP",
            r"PHOLD",
            r"PRE-OP",
            r"SURG\s*PREP",
            r"PRESURG",
            r"SDS",  # Same Day Surgery
            r"ASC",  # Ambulatory Surgery Center
            r"PRE\s*ADMISSION",
        ]
    )

    or_patterns: list[str] = field(
        default_factory=lambda: [
            r"^OR\d*$",
            r"^OR\s",
            r"OPER",
            r"SURG\s*SUITE",
            r"THEATER",
            r"PROC\s*ROOM",
            r"CATH\s*LAB",
            r"IR\s*SUITE",
        ]
    )

    pacu_patterns: list[str] = field(
        default_factory=lambda: [
            r"PACU",
            r"RECOVERY",
            r"POST\s*ANES",
            r"POST\s*OP",
            r"STAGE\s*2",
            r"PHASE\s*II",
        ]
    )

    inpatient_patterns: list[str] = field(
        default_factory=lambda: [
            r"^\d+[A-Z]?$",  # Unit numbers like "4A", "7"
            r"WARD",
            r"UNIT",
            r"MED\s*SURG",
            r"ICU",
            r"PICU",
            r"NICU",
        ]
    )

    discharge_patterns: list[str] = field(
        default_factory=lambda: [
            r"DISCH",
            r"HOME",
            r"TRANSFER",
            r"EXPIRED",
            r"DECEASED",
        ]
    )

    def match_location(self, location_code: str) -> LocationState:
        """Match a location code to a state using configured patterns."""
        location_upper = location_code.upper().strip()

        # Check patterns in priority order
        pattern_groups = [
            (self.or_patterns, LocationState.OR_SUITE),
            (self.pre_op_patterns, LocationState.PRE_OP_HOLDING),
            (self.pacu_patterns, LocationState.PACU),
            (self.discharge_patterns, LocationState.DISCHARGED),
            (self.inpatient_patterns, LocationState.INPATIENT),
        ]

        for patterns, state in pattern_groups:
            for pattern in patterns:
                if re.search(pattern, location_upper, re.IGNORECASE):
                    return state

        return LocationState.UNKNOWN


@dataclass
class PatientLocationUpdate:
    """Represents a patient location change event."""

    patient_mrn: str
    new_location_code: str
    new_location_state: LocationState
    prior_location_code: Optional[str] = None
    prior_location_state: Optional[LocationState] = None
    event_time: Optional[datetime] = None
    message_control_id: Optional[str] = None
    visit_number: Optional[str] = None
    patient_name: Optional[str] = None


# Type alias for state transition callback
StateTransitionCallback = Callable[[PatientLocationUpdate], Awaitable[None]]


class LocationTracker:
    """
    Tracks patient locations and triggers callbacks on state transitions.

    Usage:
        tracker = LocationTracker()
        tracker.on_pre_op_arrival = handle_pre_op_arrival
        tracker.on_or_entry = handle_or_entry
        await tracker.process_adt(hl7_message)
    """

    def __init__(
        self,
        patterns: Optional[LocationPatterns] = None,
    ):
        self.patterns = patterns or LocationPatterns()

        # State transition callbacks
        self.on_pre_op_arrival: Optional[StateTransitionCallback] = None
        self.on_or_entry: Optional[StateTransitionCallback] = None
        self.on_pacu_arrival: Optional[StateTransitionCallback] = None
        self.on_discharge: Optional[StateTransitionCallback] = None

        # Track current state per patient (MRN -> state)
        self._patient_states: dict[str, LocationState] = {}

    def get_patient_state(self, patient_mrn: str) -> LocationState:
        """Get current state for a patient."""
        return self._patient_states.get(patient_mrn, LocationState.UNKNOWN)

    def set_patient_state(self, patient_mrn: str, state: LocationState) -> None:
        """Set state for a patient (used when loading from database)."""
        self._patient_states[patient_mrn] = state

    async def process_adt(self, message: HL7Message) -> Optional[PatientLocationUpdate]:
        """
        Process an ADT message and trigger appropriate callbacks.

        Args:
            message: Parsed HL7 ADT message

        Returns:
            PatientLocationUpdate if a state change occurred, None otherwise
        """
        # Only handle A02 (transfer) messages for now
        # Could extend to A01 (admit), A03 (discharge), etc.
        if message.message_event not in ("A02", "A01", "A03", "A08"):
            logger.debug(
                f"Ignoring ADT event {message.message_event}, only handling A02/A01/A03/A08"
            )
            return None

        data = extract_adt_a02_data(message)
        patient_mrn = data.get("patient_mrn")

        if not patient_mrn:
            logger.warning(
                f"No patient MRN in ADT message {message.message_control_id}"
            )
            return None

        # Determine new location state
        current_location = data.get("current_location_code", "")
        new_state = self.patterns.match_location(current_location)

        # Get prior state
        prior_state = self._patient_states.get(patient_mrn, LocationState.UNKNOWN)
        prior_location = data.get("prior_location", "")

        # Create update record
        update = PatientLocationUpdate(
            patient_mrn=patient_mrn,
            new_location_code=current_location,
            new_location_state=new_state,
            prior_location_code=prior_location,
            prior_location_state=prior_state,
            event_time=data.get("message_time") or datetime.now(),
            message_control_id=data.get("message_control_id"),
            visit_number=data.get("visit_number"),
            patient_name=data.get("patient_name"),
        )

        # Update state
        self._patient_states[patient_mrn] = new_state

        # Handle state transition
        await self._handle_state_transition(prior_state, new_state, update)

        logger.info(
            f"Patient {patient_mrn} location: {current_location} -> {new_state.value} "
            f"(was {prior_state.value})"
        )

        return update

    async def _handle_state_transition(
        self,
        prior_state: LocationState,
        new_state: LocationState,
        update: PatientLocationUpdate,
    ) -> None:
        """Handle state transitions and fire appropriate callbacks."""

        # Pre-op arrival (from anywhere except OR/PACU)
        if (
            new_state == LocationState.PRE_OP_HOLDING
            and prior_state not in (LocationState.OR_SUITE, LocationState.PACU)
        ):
            if self.on_pre_op_arrival:
                try:
                    await self.on_pre_op_arrival(update)
                except Exception as e:
                    logger.error(f"Error in on_pre_op_arrival callback: {e}")

        # OR entry (critical moment)
        elif new_state == LocationState.OR_SUITE and prior_state != LocationState.OR_SUITE:
            if self.on_or_entry:
                try:
                    await self.on_or_entry(update)
                except Exception as e:
                    logger.error(f"Error in on_or_entry callback: {e}")

        # PACU arrival (surgery complete)
        elif new_state == LocationState.PACU and prior_state != LocationState.PACU:
            if self.on_pacu_arrival:
                try:
                    await self.on_pacu_arrival(update)
                except Exception as e:
                    logger.error(f"Error in on_pacu_arrival callback: {e}")

        # Discharge
        elif new_state == LocationState.DISCHARGED:
            if self.on_discharge:
                try:
                    await self.on_discharge(update)
                except Exception as e:
                    logger.error(f"Error in on_discharge callback: {e}")

    def classify_location(self, location_code: str) -> LocationState:
        """
        Classify a location code without tracking state.

        Useful for testing or one-off lookups.
        """
        return self.patterns.match_location(location_code)

    def clear_patient(self, patient_mrn: str) -> None:
        """Remove a patient from tracking (e.g., after discharge)."""
        self._patient_states.pop(patient_mrn, None)

    def clear_all(self) -> None:
        """Clear all tracked patients."""
        self._patient_states.clear()

    @property
    def tracked_patients(self) -> dict[str, LocationState]:
        """Get all currently tracked patients and their states."""
        return self._patient_states.copy()


def create_location_tracker_from_config(config: dict) -> LocationTracker:
    """
    Create a LocationTracker with patterns from configuration.

    Args:
        config: Configuration dictionary with pattern lists

    Returns:
        Configured LocationTracker
    """
    patterns = LocationPatterns(
        pre_op_patterns=config.get("pre_op_patterns", LocationPatterns().pre_op_patterns),
        or_patterns=config.get("or_patterns", LocationPatterns().or_patterns),
        pacu_patterns=config.get("pacu_patterns", LocationPatterns().pacu_patterns),
        inpatient_patterns=config.get("inpatient_patterns", LocationPatterns().inpatient_patterns),
        discharge_patterns=config.get("discharge_patterns", LocationPatterns().discharge_patterns),
    )
    return LocationTracker(patterns=patterns)
