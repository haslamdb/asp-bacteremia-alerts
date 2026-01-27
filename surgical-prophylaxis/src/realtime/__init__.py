"""
Real-time surgical prophylaxis monitoring module.

Provides pre-operative alerting for surgical prophylaxis compliance,
tracking patients through the surgical workflow and alerting care teams
when prophylaxis is missing before incision.

Components:
- HL7 Listener: MLLP server for ADT/ORM messages
- Location Tracker: Patient surgical journey state machine
- Schedule Monitor: FHIR Appointment polling for upcoming surgeries
- Pre-Op Checker: Real-time compliance checking
- Escalation Engine: Time-based alert routing with automatic escalation
- Epic Secure Chat: Epic integration for secure messaging
- State Manager: Journey coordination between components
- Service: Main orchestrator
"""

from .hl7_parser import HL7Message, HL7Segment, parse_hl7_message
from .location_tracker import LocationState, LocationTracker, PatientLocationUpdate
from .schedule_monitor import ScheduledSurgery, ScheduleMonitor
from .preop_checker import PreOpCheckResult, PreOpChecker
from .escalation_engine import EscalationRule, EscalationEngine, AlertTrigger
from .state_manager import StateManager, SurgicalJourney
from .epic_chat import EpicSecureChat
from .hl7_listener import HL7MLLPServer, MessageHandler
from .service import RealtimeProphylaxisService

__all__ = [
    # HL7 Parsing
    "HL7Message",
    "HL7Segment",
    "parse_hl7_message",
    # Location Tracking
    "LocationState",
    "LocationTracker",
    "PatientLocationUpdate",
    # Schedule Monitoring
    "ScheduledSurgery",
    "ScheduleMonitor",
    # Pre-Op Checking
    "PreOpCheckResult",
    "PreOpChecker",
    # Escalation
    "EscalationRule",
    "EscalationEngine",
    "AlertTrigger",
    # State Management
    "StateManager",
    "SurgicalJourney",
    # Epic Integration
    "EpicSecureChat",
    # HL7 Server
    "HL7MLLPServer",
    "MessageHandler",
    # Main Service
    "RealtimeProphylaxisService",
]
