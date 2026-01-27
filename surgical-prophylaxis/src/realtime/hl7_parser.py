"""
HL7 v2.x message parsing utilities.

Parses ADT (patient tracking) and ORM (scheduling) messages
for real-time surgical prophylaxis monitoring.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# HL7 delimiters (standard)
SEGMENT_DELIMITER = "\r"
FIELD_DELIMITER = "|"
COMPONENT_DELIMITER = "^"
REPETITION_DELIMITER = "~"
ESCAPE_CHAR = "\\"
SUBCOMPONENT_DELIMITER = "&"


@dataclass
class HL7Segment:
    """Represents a single HL7 segment."""

    segment_type: str
    fields: list[str] = field(default_factory=list)

    def get_field(self, index: int, default: str = "") -> str:
        """Get field by 1-based index (HL7 convention)."""
        # HL7 fields are 1-indexed, but segment type is "field 0"
        actual_index = index
        if actual_index < len(self.fields):
            return self.fields[actual_index] or default
        return default

    def get_component(
        self, field_index: int, component_index: int, default: str = ""
    ) -> str:
        """Get component within a field (both 1-based)."""
        field_value = self.get_field(field_index)
        components = field_value.split(COMPONENT_DELIMITER)
        comp_idx = component_index - 1
        if 0 <= comp_idx < len(components):
            return components[comp_idx] or default
        return default

    def get_all_components(self, field_index: int) -> list[str]:
        """Get all components of a field."""
        field_value = self.get_field(field_index)
        return field_value.split(COMPONENT_DELIMITER)


@dataclass
class HL7Message:
    """Parsed HL7 message with easy field access."""

    raw: str
    segments: dict[str, list[HL7Segment]] = field(default_factory=dict)
    message_type: str = ""
    message_event: str = ""
    message_control_id: str = ""
    message_datetime: Optional[datetime] = None

    def get_segment(self, segment_type: str, index: int = 0) -> Optional[HL7Segment]:
        """Get a segment by type and occurrence index."""
        segments = self.segments.get(segment_type, [])
        if index < len(segments):
            return segments[index]
        return None

    def get_all_segments(self, segment_type: str) -> list[HL7Segment]:
        """Get all segments of a given type."""
        return self.segments.get(segment_type, [])

    @property
    def patient_mrn(self) -> str:
        """Extract patient MRN from PID segment."""
        pid = self.get_segment("PID")
        if not pid:
            return ""
        # PID-3: Patient identifier list (MRN is typically first)
        # Format: ID^^^AssigningAuthority^IDType
        pid_3 = pid.get_field(3)
        # Handle repeating identifiers
        identifiers = pid_3.split(REPETITION_DELIMITER)
        for identifier in identifiers:
            components = identifier.split(COMPONENT_DELIMITER)
            # Look for MRN type or take first identifier
            if len(components) >= 5 and components[4].upper() in ("MR", "MRN"):
                return components[0]
        # Fall back to first identifier
        if identifiers:
            return identifiers[0].split(COMPONENT_DELIMITER)[0]
        return ""

    @property
    def patient_name(self) -> str:
        """Extract patient name from PID segment."""
        pid = self.get_segment("PID")
        if not pid:
            return ""
        # PID-5: Patient name (Last^First^Middle^Suffix^Prefix)
        name_components = pid.get_all_components(5)
        if len(name_components) >= 2:
            return f"{name_components[1]} {name_components[0]}"  # First Last
        elif name_components:
            return name_components[0]
        return ""

    @property
    def visit_number(self) -> str:
        """Extract visit/encounter number from PV1 segment."""
        pv1 = self.get_segment("PV1")
        if not pv1:
            return ""
        # PV1-19: Visit number
        return pv1.get_field(19)

    @property
    def current_location(self) -> str:
        """Extract current patient location from PV1 segment."""
        pv1 = self.get_segment("PV1")
        if not pv1:
            return ""
        # PV1-3: Assigned patient location (Point of Care^Room^Bed^Facility)
        return pv1.get_field(3)

    @property
    def current_location_code(self) -> str:
        """Extract just the point of care from current location."""
        pv1 = self.get_segment("PV1")
        if not pv1:
            return ""
        # PV1-3.1: Point of care (first component)
        return pv1.get_component(3, 1)

    @property
    def prior_location(self) -> str:
        """Extract prior patient location from PV1 segment."""
        pv1 = self.get_segment("PV1")
        if not pv1:
            return ""
        # PV1-6: Prior patient location
        return pv1.get_field(6)

    @property
    def attending_physician(self) -> tuple[str, str]:
        """Extract attending physician (ID, name) from PV1."""
        pv1 = self.get_segment("PV1")
        if not pv1:
            return ("", "")
        # PV1-7: Attending doctor (ID^Last^First^Middle^Suffix^Prefix^Degree)
        components = pv1.get_all_components(7)
        physician_id = components[0] if components else ""
        physician_name = ""
        if len(components) >= 3:
            physician_name = f"{components[2]} {components[1]}"
        return (physician_id, physician_name)


def parse_hl7_message(raw_message: str) -> HL7Message:
    """
    Parse a raw HL7 v2.x message into structured format.

    Args:
        raw_message: Raw HL7 message string

    Returns:
        Parsed HL7Message object
    """
    # Normalize line endings
    raw_message = raw_message.replace("\r\n", "\r").replace("\n", "\r")

    # Remove MLLP framing if present
    raw_message = raw_message.strip("\x0b\x1c\r")

    message = HL7Message(raw=raw_message)
    lines = raw_message.split(SEGMENT_DELIMITER)

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # MSH segment is special - field delimiter IS the first field
        if line.startswith("MSH"):
            segment_type = "MSH"
            # MSH-1 is the field separator itself
            # Fields start after "MSH|"
            fields = ["", FIELD_DELIMITER] + line[4:].split(FIELD_DELIMITER)
        else:
            parts = line.split(FIELD_DELIMITER)
            segment_type = parts[0]
            fields = parts

        segment = HL7Segment(segment_type=segment_type, fields=fields)

        if segment_type not in message.segments:
            message.segments[segment_type] = []
        message.segments[segment_type].append(segment)

    # Extract common fields from MSH
    msh = message.get_segment("MSH")
    if msh:
        # MSH-9: Message type (MessageType^TriggerEvent)
        msg_type_field = msh.get_field(9)
        type_parts = msg_type_field.split(COMPONENT_DELIMITER)
        message.message_type = type_parts[0] if type_parts else ""
        message.message_event = type_parts[1] if len(type_parts) > 1 else ""

        # MSH-10: Message control ID
        message.message_control_id = msh.get_field(10)

        # MSH-7: Message date/time
        dt_str = msh.get_field(7)
        message.message_datetime = parse_hl7_datetime(dt_str)

    return message


def parse_hl7_datetime(dt_string: str) -> Optional[datetime]:
    """
    Parse HL7 datetime format (yyyyMMddHHmmss or variations).

    Args:
        dt_string: HL7 datetime string

    Returns:
        datetime object or None if parsing fails
    """
    if not dt_string:
        return None

    # Remove timezone suffix if present
    dt_string = dt_string.split("+")[0].split("-")[0]

    # Try various formats
    formats = [
        "%Y%m%d%H%M%S",     # yyyyMMddHHmmss
        "%Y%m%d%H%M%S.%f",  # With fractional seconds
        "%Y%m%d%H%M",       # yyyyMMddHHmm
        "%Y%m%d",           # yyyyMMdd
    ]

    for fmt in formats:
        try:
            # Truncate string to expected length
            expected_len = len(datetime.now().strftime(fmt).replace(".", ""))
            truncated = dt_string[:expected_len] if "." not in fmt else dt_string
            return datetime.strptime(truncated, fmt)
        except ValueError:
            continue

    logger.warning(f"Failed to parse HL7 datetime: {dt_string}")
    return None


def extract_adt_a02_data(message: HL7Message) -> dict:
    """
    Extract relevant data from an ADT^A02 (patient transfer) message.

    Args:
        message: Parsed HL7 message

    Returns:
        Dictionary with transfer details
    """
    return {
        "message_type": "ADT",
        "event_type": "A02",
        "message_control_id": message.message_control_id,
        "message_time": message.message_datetime,
        "patient_mrn": message.patient_mrn,
        "patient_name": message.patient_name,
        "visit_number": message.visit_number,
        "current_location": message.current_location,
        "current_location_code": message.current_location_code,
        "prior_location": message.prior_location,
    }


def extract_orm_o01_data(message: HL7Message) -> dict:
    """
    Extract relevant data from an ORM^O01 (general order) message.

    For OR scheduling, we look for procedure/surgery orders.

    Args:
        message: Parsed HL7 message

    Returns:
        Dictionary with order details
    """
    result = {
        "message_type": "ORM",
        "event_type": "O01",
        "message_control_id": message.message_control_id,
        "message_time": message.message_datetime,
        "patient_mrn": message.patient_mrn,
        "patient_name": message.patient_name,
        "visit_number": message.visit_number,
        "orders": [],
    }

    # Extract ORC (Common Order) and OBR (Observation Request) segments
    orc_segments = message.get_all_segments("ORC")
    obr_segments = message.get_all_segments("OBR")

    for i, orc in enumerate(orc_segments):
        order = {
            "order_control": orc.get_field(1),  # NW=New, CA=Cancel, etc.
            "placer_order_number": orc.get_field(2),
            "filler_order_number": orc.get_field(3),
            "order_status": orc.get_field(5),
            "scheduled_datetime": parse_hl7_datetime(orc.get_component(7, 4)),
        }

        # Get corresponding OBR segment
        if i < len(obr_segments):
            obr = obr_segments[i]
            order["procedure_code"] = obr.get_component(4, 1)
            order["procedure_name"] = obr.get_component(4, 2)
            order["scheduled_datetime"] = (
                parse_hl7_datetime(obr.get_field(36)) or order["scheduled_datetime"]
            )

        result["orders"].append(order)

    return result


def extract_siu_s12_data(message: HL7Message) -> dict:
    """
    Extract relevant data from an SIU^S12 (schedule notification) message.

    Args:
        message: Parsed HL7 message

    Returns:
        Dictionary with scheduling details
    """
    result = {
        "message_type": "SIU",
        "event_type": "S12",
        "message_control_id": message.message_control_id,
        "message_time": message.message_datetime,
        "patient_mrn": message.patient_mrn,
        "patient_name": message.patient_name,
        "visit_number": message.visit_number,
        "appointments": [],
    }

    # Extract SCH (Scheduling Activity Information) segments
    sch_segments = message.get_all_segments("SCH")

    for sch in sch_segments:
        appointment = {
            "placer_appointment_id": sch.get_component(1, 1),
            "filler_appointment_id": sch.get_component(2, 1),
            "event_reason": sch.get_field(6),
            "appointment_type": sch.get_component(8, 1),
            "appointment_duration": sch.get_field(9),
        }

        # SCH-11: Appointment timing (start^end)
        timing = sch.get_field(11)
        timing_parts = timing.split(COMPONENT_DELIMITER)
        if timing_parts:
            appointment["start_time"] = parse_hl7_datetime(timing_parts[0])
            if len(timing_parts) > 1:
                appointment["end_time"] = parse_hl7_datetime(timing_parts[1])

        result["appointments"].append(appointment)

    # Extract AIS (Appointment Information - Service) for procedure details
    ais_segments = message.get_all_segments("AIS")
    for i, ais in enumerate(ais_segments):
        if i < len(result["appointments"]):
            result["appointments"][i]["service_code"] = ais.get_component(3, 1)
            result["appointments"][i]["service_name"] = ais.get_component(3, 2)

    # Extract AIL (Appointment Information - Location) for OR location
    ail_segments = message.get_all_segments("AIL")
    for i, ail in enumerate(ail_segments):
        if i < len(result["appointments"]):
            result["appointments"][i]["location"] = ail.get_component(3, 1)

    return result


def build_ack_message(
    original_message: HL7Message,
    ack_code: str = "AA",
    error_message: str = "",
) -> str:
    """
    Build an HL7 ACK message in response to a received message.

    Args:
        original_message: The message being acknowledged
        ack_code: AA=Accept, AE=Error, AR=Reject
        error_message: Error description if ack_code is AE or AR

    Returns:
        HL7 ACK message string
    """
    now = datetime.now().strftime("%Y%m%d%H%M%S")

    msh = original_message.get_segment("MSH")
    sending_app = msh.get_field(3) if msh else "AEGIS"
    sending_facility = msh.get_field(4) if msh else "AEGIS"
    receiving_app = msh.get_field(5) if msh else ""
    receiving_facility = msh.get_field(6) if msh else ""

    ack = (
        f"MSH|^~\\&|{sending_app}|{sending_facility}|{receiving_app}|{receiving_facility}|"
        f"{now}||ACK^{original_message.message_event}|{original_message.message_control_id}|P|2.5\r"
        f"MSA|{ack_code}|{original_message.message_control_id}"
    )

    if error_message:
        ack += f"|{error_message}"

    return ack
