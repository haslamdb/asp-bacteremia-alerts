"""
Pre-operative compliance checker for surgical prophylaxis.

Checks prophylaxis status at key trigger points:
- T-24h: Informational, pharmacy awareness
- T-2h: Pre-op holding arrival
- T-60m: Approaching OR
- T-0: Entering OR (critical)
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Optional

from .schedule_monitor import ScheduledSurgery
from .location_tracker import PatientLocationUpdate, LocationState

logger = logging.getLogger(__name__)


class AlertSeverity(Enum):
    """Alert severity levels for prophylaxis compliance."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class AlertTrigger(Enum):
    """Alert trigger points in surgical workflow."""

    T24 = "t24"          # 24 hours before surgery
    T2 = "t2"            # 2 hours before (pre-op arrival)
    T60 = "t60"          # 60 minutes before (approaching OR)
    T0 = "t0"            # Entering OR (critical)
    PREOP_ARRIVAL = "preop_arrival"  # Triggered by ADT location
    OR_ENTRY = "or_entry"            # Triggered by ADT location


@dataclass
class PreOpCheckResult:
    """Result of a pre-operative prophylaxis check."""

    # Patient/case info
    journey_id: Optional[str] = None
    case_id: Optional[str] = None
    patient_mrn: str = ""
    patient_name: Optional[str] = None

    # Trigger info
    trigger: AlertTrigger = AlertTrigger.T0
    trigger_time: datetime = field(default_factory=datetime.now)

    # Prophylaxis status
    prophylaxis_indicated: bool = False
    order_exists: bool = False
    administered: bool = False
    minutes_to_or: Optional[int] = None

    # Alert decision
    alert_required: bool = False
    alert_severity: AlertSeverity = AlertSeverity.INFO
    recommendation: str = ""

    # Additional context
    excluded: bool = False
    exclusion_reason: Optional[str] = None
    therapeutic_abx_active: bool = False
    procedure_description: Optional[str] = None
    first_line_agents: list[str] = field(default_factory=list)

    # Details for logging
    check_details: dict = field(default_factory=dict)


class PreOpChecker:
    """
    Real-time pre-operative compliance checker.

    Determines if prophylaxis alerts should be sent based on:
    - Time until surgery
    - Current prophylaxis order status
    - Medication administration status
    - Patient exclusions (therapeutic antibiotics, documented infection, etc.)
    """

    def __init__(
        self,
        guidelines_config: Optional[Any] = None,
        fhir_client: Optional[Any] = None,
    ):
        self.guidelines_config = guidelines_config
        self.fhir_client = fhir_client

    async def check_at_trigger(
        self,
        surgery: ScheduledSurgery,
        trigger: AlertTrigger,
        location_update: Optional[PatientLocationUpdate] = None,
    ) -> PreOpCheckResult:
        """
        Perform prophylaxis check at a specific trigger point.

        Args:
            surgery: The scheduled surgery
            trigger: The trigger point (T24, T2, T60, T0, etc.)
            location_update: Optional location update that triggered the check

        Returns:
            PreOpCheckResult with alert decision
        """
        result = PreOpCheckResult(
            case_id=surgery.case_id,
            patient_mrn=surgery.patient_mrn,
            patient_name=surgery.patient_name,
            trigger=trigger,
            trigger_time=datetime.now(),
            minutes_to_or=surgery.minutes_until_surgery,
            procedure_description=surgery.procedure_description,
        )

        # Check for exclusions first
        if await self._check_exclusions(surgery, result):
            return result

        # Determine if prophylaxis is indicated
        result.prophylaxis_indicated = await self._check_indication(surgery, result)

        if not result.prophylaxis_indicated:
            result.recommendation = "Prophylaxis not indicated for this procedure"
            return result

        # Check order and administration status
        await self._check_prophylaxis_status(surgery, result)

        # Determine alert based on trigger and status
        self._determine_alert(result, trigger)

        return result

    async def check_on_preop_arrival(
        self,
        location_update: PatientLocationUpdate,
        surgery: Optional[ScheduledSurgery] = None,
    ) -> PreOpCheckResult:
        """
        Check prophylaxis status when patient arrives at pre-op.

        This is a T-2h equivalent check triggered by actual location.

        Args:
            location_update: The location change event
            surgery: Optional associated surgery (will be looked up if not provided)

        Returns:
            PreOpCheckResult with alert decision
        """
        trigger = AlertTrigger.PREOP_ARRIVAL

        if surgery is None:
            # Create minimal check result
            result = PreOpCheckResult(
                patient_mrn=location_update.patient_mrn,
                patient_name=location_update.patient_name,
                trigger=trigger,
                trigger_time=location_update.event_time or datetime.now(),
                alert_required=True,
                alert_severity=AlertSeverity.WARNING,
                recommendation=(
                    "Patient arrived at pre-op but no scheduled surgery found. "
                    "Verify prophylaxis requirements."
                ),
            )
            return result

        return await self.check_at_trigger(surgery, trigger, location_update)

    async def check_on_or_entry(
        self,
        location_update: PatientLocationUpdate,
        surgery: Optional[ScheduledSurgery] = None,
    ) -> PreOpCheckResult:
        """
        Critical check when patient enters the OR.

        This is the T-0 moment - if prophylaxis isn't ready, immediate action needed.

        Args:
            location_update: The location change event
            surgery: Optional associated surgery

        Returns:
            PreOpCheckResult with alert decision
        """
        trigger = AlertTrigger.OR_ENTRY

        if surgery is None:
            # Critical - patient in OR with no surgery record
            result = PreOpCheckResult(
                patient_mrn=location_update.patient_mrn,
                patient_name=location_update.patient_name,
                trigger=trigger,
                trigger_time=location_update.event_time or datetime.now(),
                alert_required=True,
                alert_severity=AlertSeverity.CRITICAL,
                recommendation=(
                    "CRITICAL: Patient entering OR without scheduled surgery record. "
                    "Verify patient identity and prophylaxis requirements immediately."
                ),
            )
            return result

        result = await self.check_at_trigger(surgery, trigger, location_update)

        # Escalate severity for OR entry
        if result.alert_required and result.alert_severity != AlertSeverity.INFO:
            result.alert_severity = AlertSeverity.CRITICAL

        return result

    async def _check_exclusions(
        self,
        surgery: ScheduledSurgery,
        result: PreOpCheckResult,
    ) -> bool:
        """
        Check if case should be excluded from prophylaxis monitoring.

        Returns True if excluded (no alert needed).
        """
        # Check if already marked as excluded
        if hasattr(surgery, "excluded") and surgery.excluded:
            result.excluded = True
            result.exclusion_reason = getattr(surgery, "exclusion_reason", "Previously excluded")
            return True

        # Check for therapeutic antibiotics
        if await self._has_therapeutic_antibiotics(surgery.patient_mrn):
            result.excluded = True
            result.exclusion_reason = "Active therapeutic antibiotic therapy"
            result.therapeutic_abx_active = True
            return True

        # Additional exclusion checks could go here
        # e.g., documented active infection, contraindications

        return False

    async def _check_indication(
        self,
        surgery: ScheduledSurgery,
        result: PreOpCheckResult,
    ) -> bool:
        """
        Determine if prophylaxis is indicated for this procedure.

        Uses guidelines config to match CPT codes to recommendations.
        """
        if surgery.prophylaxis_indicated:
            # Already determined (e.g., from FHIR data)
            return True

        if not self.guidelines_config:
            # No guidelines config - assume indicated for surgical procedures
            logger.warning("No guidelines config, assuming prophylaxis indicated")
            return True

        # Check each CPT code against guidelines
        for cpt_code in surgery.procedure_cpt_codes:
            requirements = self.guidelines_config.get_procedure_requirements(cpt_code)
            if requirements:
                result.first_line_agents = requirements.first_line_agents
                if requirements.prophylaxis_indicated:
                    return True

        # No matching CPT - check if this looks like a surgical procedure
        # This is a fallback for procedures not in guidelines
        if surgery.procedure_cpt_codes:
            # Has CPT codes but none matched - likely no prophylaxis needed
            return False

        # No CPT codes available - be conservative, assume indicated
        logger.warning(
            f"No CPT codes for surgery {surgery.case_id}, assuming prophylaxis indicated"
        )
        return True

    async def _check_prophylaxis_status(
        self,
        surgery: ScheduledSurgery,
        result: PreOpCheckResult,
    ) -> None:
        """
        Check current prophylaxis order and administration status.

        Updates result with order_exists and administered flags.
        """
        # Check cached status on surgery object
        result.order_exists = surgery.prophylaxis_order_exists
        result.administered = surgery.prophylaxis_administered

        # Optionally refresh from FHIR
        if self.fhir_client and not result.order_exists:
            try:
                # Check for recent prophylaxis orders
                orders = await self._get_prophylaxis_orders(surgery.patient_mrn)
                if orders:
                    result.order_exists = True
                    surgery.prophylaxis_order_exists = True

                # Check for administrations
                admins = await self._get_prophylaxis_administrations(surgery.patient_mrn)
                if admins:
                    result.administered = True
                    surgery.prophylaxis_administered = True

            except Exception as e:
                logger.error(f"Error checking FHIR prophylaxis status: {e}")
                result.check_details["fhir_error"] = str(e)

    async def _has_therapeutic_antibiotics(self, patient_mrn: str) -> bool:
        """Check if patient is on therapeutic (non-prophylactic) antibiotics."""
        if not self.fhir_client:
            return False

        try:
            # This would check for active antibiotic orders
            # with therapeutic indications (not prophylaxis)
            # Implementation depends on FHIR client capabilities
            return False
        except Exception as e:
            logger.error(f"Error checking therapeutic antibiotics: {e}")
            return False

    async def _get_prophylaxis_orders(self, patient_mrn: str) -> list[dict]:
        """Get prophylaxis medication orders for patient."""
        if not self.fhir_client:
            return []

        try:
            if hasattr(self.fhir_client, "get_medication_orders"):
                return self.fhir_client.get_medication_orders(
                    patient_mrn,
                    since_hours=24,
                    prophylaxis_only=True,
                )
            return []
        except Exception as e:
            logger.error(f"Error getting prophylaxis orders: {e}")
            return []

    async def _get_prophylaxis_administrations(self, patient_mrn: str) -> list[dict]:
        """Get prophylaxis medication administrations for patient."""
        if not self.fhir_client:
            return []

        try:
            if hasattr(self.fhir_client, "get_medication_administrations"):
                return self.fhir_client.get_medication_administrations(
                    patient_mrn,
                    since_hours=4,  # Prophylaxis given within 4 hours
                    prophylaxis_only=True,
                )
            return []
        except Exception as e:
            logger.error(f"Error getting prophylaxis administrations: {e}")
            return []

    def _determine_alert(
        self,
        result: PreOpCheckResult,
        trigger: AlertTrigger,
    ) -> None:
        """
        Determine if an alert is needed and its severity.

        Updates result with alert_required, alert_severity, and recommendation.
        """
        # Already administered - no alert needed
        if result.administered:
            result.alert_required = False
            result.recommendation = "Prophylaxis already administered"
            return

        # Order exists but not yet given
        if result.order_exists and not result.administered:
            if trigger in (AlertTrigger.T0, AlertTrigger.OR_ENTRY):
                # Critical - entering OR without administration
                result.alert_required = True
                result.alert_severity = AlertSeverity.CRITICAL
                result.recommendation = (
                    "CRITICAL: Prophylaxis ordered but NOT ADMINISTERED. "
                    "Patient entering OR. Give prophylaxis immediately or document reason for delay."
                )
            elif trigger in (AlertTrigger.T60,):
                result.alert_required = True
                result.alert_severity = AlertSeverity.WARNING
                result.recommendation = (
                    "Prophylaxis ordered but not yet administered. "
                    "Surgery approaching - ensure timely administration."
                )
            else:
                result.alert_required = False  # Order exists, give time
                result.recommendation = "Prophylaxis ordered, awaiting administration"
            return

        # No order exists
        if not result.order_exists:
            if trigger in (AlertTrigger.T0, AlertTrigger.OR_ENTRY):
                result.alert_required = True
                result.alert_severity = AlertSeverity.CRITICAL
                result.recommendation = self._build_critical_recommendation(result)
            elif trigger in (AlertTrigger.T60, AlertTrigger.T2, AlertTrigger.PREOP_ARRIVAL):
                result.alert_required = True
                result.alert_severity = AlertSeverity.WARNING
                result.recommendation = self._build_warning_recommendation(result)
            elif trigger == AlertTrigger.T24:
                result.alert_required = True
                result.alert_severity = AlertSeverity.INFO
                result.recommendation = self._build_info_recommendation(result)
            return

    def _build_critical_recommendation(self, result: PreOpCheckResult) -> str:
        """Build recommendation text for critical alerts."""
        rec = "CRITICAL: No prophylaxis order found. Patient entering OR."

        if result.first_line_agents:
            agents = ", ".join(result.first_line_agents)
            rec += f"\n\nRecommended: {agents}"

        rec += "\n\nActions:\n"
        rec += "1. Order prophylaxis immediately OR\n"
        rec += "2. Document clinical reason for withholding"

        return rec

    def _build_warning_recommendation(self, result: PreOpCheckResult) -> str:
        """Build recommendation text for warning alerts."""
        rec = "Prophylaxis not yet ordered. Surgery approaching."

        if result.first_line_agents:
            agents = ", ".join(result.first_line_agents)
            rec += f"\n\nRecommended: {agents}"

        if result.minutes_to_or:
            rec += f"\n\nTime to OR: ~{result.minutes_to_or} minutes"

        return rec

    def _build_info_recommendation(self, result: PreOpCheckResult) -> str:
        """Build recommendation text for informational alerts."""
        rec = "Surgery scheduled for tomorrow. Consider prophylaxis ordering."

        if result.first_line_agents:
            agents = ", ".join(result.first_line_agents)
            rec += f"\n\nRecommended: {agents}"

        if result.procedure_description:
            rec += f"\n\nProcedure: {result.procedure_description}"

        return rec


def create_preop_checker(
    guidelines_config: Optional[Any] = None,
    fhir_client: Optional[Any] = None,
) -> PreOpChecker:
    """Factory function to create a PreOpChecker with optional dependencies."""
    return PreOpChecker(
        guidelines_config=guidelines_config,
        fhir_client=fhir_client,
    )
