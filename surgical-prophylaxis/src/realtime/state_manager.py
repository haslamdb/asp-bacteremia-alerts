"""
State manager for surgical prophylaxis journey tracking.

Coordinates between schedule monitor, location tracker, and pre-op checker
to maintain the complete patient journey through the surgical workflow.
"""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Any

from .location_tracker import LocationState, PatientLocationUpdate
from .schedule_monitor import ScheduledSurgery
from .preop_checker import PreOpCheckResult, AlertTrigger

logger = logging.getLogger(__name__)


@dataclass
class SurgicalJourney:
    """Represents a patient's complete journey through the surgical workflow."""

    journey_id: str
    case_id: str
    patient_mrn: str
    patient_name: Optional[str] = None

    # Procedure details
    procedure_description: Optional[str] = None
    procedure_cpt_codes: list[str] = field(default_factory=list)
    scheduled_time: Optional[datetime] = None

    # Current state
    current_state: LocationState = LocationState.UNKNOWN

    # Prophylaxis status
    prophylaxis_indicated: Optional[bool] = None
    order_exists: bool = False
    administered: bool = False

    # Alert tracking
    alert_t24_sent: bool = False
    alert_t24_time: Optional[datetime] = None
    alert_t2_sent: bool = False
    alert_t2_time: Optional[datetime] = None
    alert_t60_sent: bool = False
    alert_t60_time: Optional[datetime] = None
    alert_t0_sent: bool = False
    alert_t0_time: Optional[datetime] = None

    # Special flags
    is_emergency: bool = False
    already_on_therapeutic_abx: bool = False
    excluded: bool = False
    exclusion_reason: Optional[str] = None

    # Timestamps
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None

    # FHIR/HL7 references
    fhir_appointment_id: Optional[str] = None
    fhir_encounter_id: Optional[str] = None
    hl7_visit_number: Optional[str] = None

    @classmethod
    def from_scheduled_surgery(cls, surgery: ScheduledSurgery) -> "SurgicalJourney":
        """Create a journey from a scheduled surgery."""
        return cls(
            journey_id=str(uuid.uuid4())[:8],
            case_id=surgery.case_id,
            patient_mrn=surgery.patient_mrn,
            patient_name=surgery.patient_name,
            procedure_description=surgery.procedure_description,
            procedure_cpt_codes=surgery.procedure_cpt_codes,
            scheduled_time=surgery.scheduled_time,
            prophylaxis_indicated=surgery.prophylaxis_indicated,
            order_exists=surgery.prophylaxis_order_exists,
            administered=surgery.prophylaxis_administered,
            fhir_appointment_id=surgery.fhir_appointment_id,
        )

    @property
    def is_active(self) -> bool:
        """Check if journey is still active."""
        return self.completed_at is None

    @property
    def needs_alert(self) -> bool:
        """Check if journey might need an alert (basic check)."""
        if self.excluded or self.administered:
            return False
        if self.prophylaxis_indicated is False:
            return False
        return not self.order_exists


class StateManager:
    """
    Manages surgical journey state across all tracking components.

    Responsibilities:
    - Create and track surgical journeys
    - Coordinate state updates from multiple sources
    - Persist journey state to database
    - Provide journey lookup for alerts
    """

    def __init__(self, db_path: Optional[str] = None):
        if db_path is None:
            aegis_dir = Path.home() / ".aegis"
            aegis_dir.mkdir(exist_ok=True)
            db_path = str(aegis_dir / "surgical_prophylaxis.db")

        self.db_path = db_path
        self._init_db()

        # In-memory cache of active journeys (patient_mrn -> journey)
        self._active_journeys: dict[str, SurgicalJourney] = {}

        # Index by case_id for quick lookup
        self._journeys_by_case: dict[str, SurgicalJourney] = {}

    def _init_db(self) -> None:
        """Initialize realtime schema."""
        schema_path = Path(__file__).parent.parent.parent / "schema_realtime.sql"
        if schema_path.exists():
            with open(schema_path) as f:
                schema = f.read()
            with sqlite3.connect(self.db_path) as conn:
                conn.executescript(schema)

    def _get_conn(self) -> sqlite3.Connection:
        """Get database connection with row factory."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def create_journey(self, surgery: ScheduledSurgery) -> SurgicalJourney:
        """
        Create a new surgical journey from a scheduled surgery.

        Args:
            surgery: The scheduled surgery

        Returns:
            The created SurgicalJourney
        """
        journey = SurgicalJourney.from_scheduled_surgery(surgery)

        # Link back to surgery
        surgery.journey_id = journey.journey_id

        # Add to caches
        self._active_journeys[journey.patient_mrn] = journey
        self._journeys_by_case[journey.case_id] = journey

        # Persist
        self._save_journey(journey)

        logger.info(
            f"Created journey {journey.journey_id} for patient {journey.patient_mrn}"
        )

        return journey

    def get_journey(self, journey_id: str) -> Optional[SurgicalJourney]:
        """Get a journey by ID."""
        # Check cache first
        for journey in self._active_journeys.values():
            if journey.journey_id == journey_id:
                return journey

        # Load from database
        return self._load_journey(journey_id)

    def get_journey_for_patient(self, patient_mrn: str) -> Optional[SurgicalJourney]:
        """Get the active journey for a patient."""
        # Check cache
        if patient_mrn in self._active_journeys:
            return self._active_journeys[patient_mrn]

        # Load from database
        return self._load_journey_for_patient(patient_mrn)

    def get_journey_for_case(self, case_id: str) -> Optional[SurgicalJourney]:
        """Get the journey for a specific case."""
        # Check cache
        if case_id in self._journeys_by_case:
            return self._journeys_by_case[case_id]

        # Load from database
        return self._load_journey_for_case(case_id)

    def update_location(
        self,
        location_update: PatientLocationUpdate,
    ) -> Optional[SurgicalJourney]:
        """
        Update journey state based on a location change.

        Args:
            location_update: The location update event

        Returns:
            Updated SurgicalJourney if found, None otherwise
        """
        journey = self.get_journey_for_patient(location_update.patient_mrn)

        if not journey:
            logger.debug(
                f"No active journey for patient {location_update.patient_mrn}"
            )
            return None

        # Update state
        journey.current_state = location_update.new_location_state
        journey.updated_at = datetime.now()

        if location_update.visit_number:
            journey.hl7_visit_number = location_update.visit_number

        # Persist
        self._save_journey(journey)

        # Record location history
        self._save_location_history(journey.journey_id, location_update)

        logger.debug(
            f"Journey {journey.journey_id} updated to state {journey.current_state.value}"
        )

        return journey

    def update_prophylaxis_status(
        self,
        journey_id: str,
        order_exists: Optional[bool] = None,
        administered: Optional[bool] = None,
    ) -> Optional[SurgicalJourney]:
        """
        Update prophylaxis status for a journey.

        Args:
            journey_id: The journey ID
            order_exists: Whether a prophylaxis order exists
            administered: Whether prophylaxis has been administered

        Returns:
            Updated SurgicalJourney if found, None otherwise
        """
        journey = self.get_journey(journey_id)

        if not journey:
            return None

        if order_exists is not None:
            journey.order_exists = order_exists
        if administered is not None:
            journey.administered = administered

        journey.updated_at = datetime.now()

        # Persist
        self._save_journey(journey)

        return journey

    def mark_alert_sent(
        self,
        journey_id: str,
        trigger: AlertTrigger,
    ) -> None:
        """Mark that an alert was sent for a specific trigger."""
        journey = self.get_journey(journey_id)

        if not journey:
            return

        now = datetime.now()

        if trigger == AlertTrigger.T24:
            journey.alert_t24_sent = True
            journey.alert_t24_time = now
        elif trigger in (AlertTrigger.T2, AlertTrigger.PREOP_ARRIVAL):
            journey.alert_t2_sent = True
            journey.alert_t2_time = now
        elif trigger == AlertTrigger.T60:
            journey.alert_t60_sent = True
            journey.alert_t60_time = now
        elif trigger in (AlertTrigger.T0, AlertTrigger.OR_ENTRY):
            journey.alert_t0_sent = True
            journey.alert_t0_time = now

        journey.updated_at = now
        self._save_journey(journey)

    def record_check_result(
        self,
        journey_id: str,
        result: PreOpCheckResult,
        alert_id: Optional[str] = None,
    ) -> None:
        """Record a pre-op check result in the database."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO preop_checks (
                    journey_id, trigger_type, trigger_time,
                    prophylaxis_indicated, order_exists, administered,
                    minutes_to_or, alert_required, alert_severity,
                    recommendation, alert_id, therapeutic_abx_active,
                    check_details
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journey_id,
                    result.trigger.value,
                    result.trigger_time.isoformat(),
                    result.prophylaxis_indicated,
                    result.order_exists,
                    result.administered,
                    result.minutes_to_or,
                    result.alert_required,
                    result.alert_severity.value if result.alert_required else None,
                    result.recommendation,
                    alert_id,
                    result.therapeutic_abx_active,
                    json.dumps(result.check_details),
                ),
            )
            conn.commit()

    def complete_journey(
        self,
        journey_id: str,
        reason: str = "completed",
    ) -> Optional[SurgicalJourney]:
        """
        Mark a journey as complete.

        Args:
            journey_id: The journey ID
            reason: Reason for completion (completed, cancelled, etc.)

        Returns:
            The completed SurgicalJourney
        """
        journey = self.get_journey(journey_id)

        if not journey:
            return None

        journey.completed_at = datetime.now()
        journey.updated_at = journey.completed_at

        # Remove from active caches
        self._active_journeys.pop(journey.patient_mrn, None)
        self._journeys_by_case.pop(journey.case_id, None)

        # Persist
        self._save_journey(journey)

        logger.info(f"Journey {journey_id} completed: {reason}")

        return journey

    def get_active_journeys(self) -> list[SurgicalJourney]:
        """Get all active (non-completed) journeys."""
        return list(self._active_journeys.values())

    def get_journeys_needing_checks(self) -> list[SurgicalJourney]:
        """Get journeys that may need prophylaxis checks."""
        return [
            j for j in self._active_journeys.values()
            if j.needs_alert and not j.excluded
        ]

    def load_active_journeys(self) -> int:
        """
        Load active journeys from database into memory.

        Called on startup to restore state.

        Returns:
            Number of journeys loaded
        """
        self._active_journeys.clear()
        self._journeys_by_case.clear()

        with self._get_conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM surgical_journeys
                WHERE completed_at IS NULL
                ORDER BY scheduled_time
                """
            ).fetchall()

        for row in rows:
            journey = self._row_to_journey(dict(row))
            self._active_journeys[journey.patient_mrn] = journey
            self._journeys_by_case[journey.case_id] = journey

        logger.info(f"Loaded {len(self._active_journeys)} active journeys")

        return len(self._active_journeys)

    # Database operations

    def _save_journey(self, journey: SurgicalJourney) -> None:
        """Save or update a journey in the database."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO surgical_journeys (
                    journey_id, case_id, patient_mrn, patient_name,
                    procedure_description, procedure_cpt_codes, scheduled_time,
                    current_state, prophylaxis_indicated, order_exists, administered,
                    alert_t24_sent, alert_t24_time, alert_t2_sent, alert_t2_time,
                    alert_t60_sent, alert_t60_time, alert_t0_sent, alert_t0_time,
                    is_emergency, already_on_therapeutic_abx, excluded, exclusion_reason,
                    created_at, updated_at, completed_at,
                    fhir_appointment_id, fhir_encounter_id, hl7_visit_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    journey.journey_id,
                    journey.case_id,
                    journey.patient_mrn,
                    journey.patient_name,
                    journey.procedure_description,
                    json.dumps(journey.procedure_cpt_codes),
                    journey.scheduled_time.isoformat() if journey.scheduled_time else None,
                    journey.current_state.value,
                    journey.prophylaxis_indicated,
                    journey.order_exists,
                    journey.administered,
                    journey.alert_t24_sent,
                    journey.alert_t24_time.isoformat() if journey.alert_t24_time else None,
                    journey.alert_t2_sent,
                    journey.alert_t2_time.isoformat() if journey.alert_t2_time else None,
                    journey.alert_t60_sent,
                    journey.alert_t60_time.isoformat() if journey.alert_t60_time else None,
                    journey.alert_t0_sent,
                    journey.alert_t0_time.isoformat() if journey.alert_t0_time else None,
                    journey.is_emergency,
                    journey.already_on_therapeutic_abx,
                    journey.excluded,
                    journey.exclusion_reason,
                    journey.created_at.isoformat(),
                    journey.updated_at.isoformat(),
                    journey.completed_at.isoformat() if journey.completed_at else None,
                    journey.fhir_appointment_id,
                    journey.fhir_encounter_id,
                    journey.hl7_visit_number,
                ),
            )
            conn.commit()

    def _save_location_history(
        self,
        journey_id: str,
        update: PatientLocationUpdate,
    ) -> None:
        """Save a location change to history."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO patient_locations (
                    patient_mrn, journey_id, location_code,
                    location_description, location_state,
                    event_time, message_time, hl7_message_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    update.patient_mrn,
                    journey_id,
                    update.new_location_code,
                    None,  # description
                    update.new_location_state.value,
                    update.event_time.isoformat() if update.event_time else datetime.now().isoformat(),
                    datetime.now().isoformat(),
                    update.message_control_id,
                ),
            )
            conn.commit()

    def _load_journey(self, journey_id: str) -> Optional[SurgicalJourney]:
        """Load a journey from database by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM surgical_journeys WHERE journey_id = ?",
                (journey_id,),
            ).fetchone()

        if not row:
            return None

        return self._row_to_journey(dict(row))

    def _load_journey_for_patient(self, patient_mrn: str) -> Optional[SurgicalJourney]:
        """Load the most recent active journey for a patient."""
        with self._get_conn() as conn:
            row = conn.execute(
                """
                SELECT * FROM surgical_journeys
                WHERE patient_mrn = ? AND completed_at IS NULL
                ORDER BY scheduled_time DESC
                LIMIT 1
                """,
                (patient_mrn,),
            ).fetchone()

        if not row:
            return None

        journey = self._row_to_journey(dict(row))

        # Add to cache
        self._active_journeys[patient_mrn] = journey
        self._journeys_by_case[journey.case_id] = journey

        return journey

    def _load_journey_for_case(self, case_id: str) -> Optional[SurgicalJourney]:
        """Load a journey by case ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM surgical_journeys WHERE case_id = ?",
                (case_id,),
            ).fetchone()

        if not row:
            return None

        return self._row_to_journey(dict(row))

    def _row_to_journey(self, row: dict) -> SurgicalJourney:
        """Convert a database row to SurgicalJourney."""
        return SurgicalJourney(
            journey_id=row["journey_id"],
            case_id=row["case_id"],
            patient_mrn=row["patient_mrn"],
            patient_name=row["patient_name"],
            procedure_description=row["procedure_description"],
            procedure_cpt_codes=json.loads(row["procedure_cpt_codes"]) if row["procedure_cpt_codes"] else [],
            scheduled_time=datetime.fromisoformat(row["scheduled_time"]) if row["scheduled_time"] else None,
            current_state=LocationState.from_string(row["current_state"]),
            prophylaxis_indicated=row["prophylaxis_indicated"],
            order_exists=bool(row["order_exists"]),
            administered=bool(row["administered"]),
            alert_t24_sent=bool(row["alert_t24_sent"]),
            alert_t24_time=datetime.fromisoformat(row["alert_t24_time"]) if row["alert_t24_time"] else None,
            alert_t2_sent=bool(row["alert_t2_sent"]),
            alert_t2_time=datetime.fromisoformat(row["alert_t2_time"]) if row["alert_t2_time"] else None,
            alert_t60_sent=bool(row["alert_t60_sent"]),
            alert_t60_time=datetime.fromisoformat(row["alert_t60_time"]) if row["alert_t60_time"] else None,
            alert_t0_sent=bool(row["alert_t0_sent"]),
            alert_t0_time=datetime.fromisoformat(row["alert_t0_time"]) if row["alert_t0_time"] else None,
            is_emergency=bool(row["is_emergency"]),
            already_on_therapeutic_abx=bool(row["already_on_therapeutic_abx"]),
            excluded=bool(row["excluded"]),
            exclusion_reason=row["exclusion_reason"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            fhir_appointment_id=row["fhir_appointment_id"],
            fhir_encounter_id=row["fhir_encounter_id"],
            hl7_visit_number=row["hl7_visit_number"],
        )
